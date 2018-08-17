#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing import Lock
import threading

from splinter import Browser

from ..exceptions import ErrorDomain
from ..result import Result, Origin
from ..result import open_results
from ..result.workbook import workbook_to_result, check_workbook_consistency

from .commands import TakeExamCommand
from .drivers import Login, TemporaryUser, TestDriver, Test, verify_admin_settings
from .utils import wait_for_page_load
from .context import RandomContext
from ..question.coverage import Coverage

from ..question import *  # for pickling

import selenium
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import WebDriverException

import asyncio
import requests
import json
import traceback

import time
import datetime
import uuid

from collections import defaultdict
from contextlib import contextmanager

monitor_mutex = Lock()


def encode_success(success):
	return "/".join(success)


def take_exam(args):
	asyncio.set_event_loop(asyncio.new_event_loop())

	command = args["command"]
	machine = command.machine
	batch_id = args["batch_id"]
	report = args["report"]

	result_json = None
	report("master", "passing take_exam to %s." % machine)

	try:
		r = requests.post("http://%s:8888/start/%s" % (machine, batch_id),
			data={"command_json": command.to_json()})
		if r.status_code != 200:
			raise InteractionException("start call failed: %s" % r.status_code)

		report("master", "test started on %s." % machine)

		index = 0

		while result_json is None:
			# we don't want too much traffic for updating machine states. only check
			# one at a time.
			monitor_mutex.acquire()
			try:
				time.sleep(1)
				r = requests.get("http://%s:8888/monitor/%s/%d" % (machine, batch_id, index))
			finally:
				monitor_mutex.release()

			if r.status_code != 200:
				raise InteractionException("monitor call failed: %s" % r.status_code)
		
			messages = json.loads(r.text)

			for command, payload in messages:
				if command == "ECHO":
					report(machine, payload)
				elif command == "DONE":
					result_json = payload
				elif command == "ERROR":
					raise Exception(payload)
				else:
					raise InteractionException("unknown command %s" % command)

			index += len(messages)

	except:
		traceback.print_exc()
		try:
			report("master", "machine %s failed: %s" % (machine, traceback.format_exc()))
		except:
			print("report failed.")
		return Result.from_error(Origin.recorded, ErrorDomain.integrity, traceback.format_exc())

	report("master", "received take_exam results from %s." % machine)
	return Result(from_json=result_json)


class MasterContext:
	def __init__(self, batch, protocol):
		self.batch = batch
		self.protocol = protocol
		self.driver = None
		self.test_driver = None
		self.screenshot_url = None

	def report(self, message):
		try:
			url = self.driver.current_url
			if url != self.screenshot_url:
				self.batch.screenshot = self.driver.get_screenshot_as_base64()
				self.screenshot_url = url
		except:
			self.batch.report("master", "failed to create screenshot.")

		self.batch.report("master", message)
		self.protocol(message)


@contextmanager
def in_master(batch, protocol):
	context = MasterContext(batch, protocol)

	# moz:webdriverClick needed for file uploads to work.
	capabilities = {"moz:webdriverClick": False}

	log_path = "tmp/geckodriver.master.log"
	open(log_path, 'w').close()  # empty log file

	batch.report("master", "connecting to client browser...")
	with Browser(headless=True, capabilities=capabilities, log_path=log_path, wait_time=batch.wait_time) as browser:
		context.driver = browser.driver

		test_driver = TestDriver(browser.driver, batch.test, batch.workarounds, context.report)
		context.test_driver = test_driver

		with Login(browser.driver, context.report, "root", "odysseus") as login:
			context.language = login.language
			yield context


def remove_trailing_zeros(s):
	parts = s.split(".")
	if len(parts) == 2 and all(x == "0" for x in parts[1]):
		# e.g. 2.00 -> 2
		return parts[0]
	elif len(parts) == 2 and s[-1] == "0":
		# e.g. 2.10 -> 2.1
		while s[-1] == "0":
			s = s[:-1]
		return s
	else:
		return s


def get_most_severe_error(results):
	return most_severe(r.get_most_severe_error() for r in results)


class Run:
	def __init__(self, batch):
		self.success = ("FAIL", "unknown")

		self.xls = b""
		self.performance_data = []
		self.coverage = Coverage()
		self.users = []
		self.protocols = defaultdict(list)
		self.questions = None
		self.language = None

		self.batch = batch
		self.machines = batch.machines
		self.settings = batch.settings
		self.workarounds = batch.workarounds
		self.batch_id = batch.batch_id
		self.ilias_version = batch.ilias_version
		self.test = batch.test
		self.wait_time = batch.wait_time

	def _make_protocol(self, users):
		sections = ["header",
			"result",
			"preferences-workarounds",
			"preferences-settings",
			"master",
			"readjustment",
			"log"]
		sections.extend(user.get_username() for user in self.users)

		parts = list()

		for section in sections:
			part = self.protocols[section]
			if part:
				parts.append("-" * 80)
				parts.append(section)
				parts.append("-" * 80)
				parts.append("")
				parts.extend(part)
				parts.append("")

		return "\n".join(parts)

	def _check_results(self, index, master, workbook, all_recorded_results):
		all_assertions_ok = True

		gui_scores = master.test_driver.get_gui_scores([user.get_username() for user in self.users])

		for user, recorded_result in zip(self.users, all_recorded_results):
			master.report("checking results for user %s." % user.get_username())

			# fetch and check results.
			ilias_result = workbook_to_result(
				workbook, user.get_username(), master.report)

			# check score via gui participants tab as well.
			ilias_result.add(("exam", "score", "gui"), gui_scores[user.get_username()])

			def report(message):
				if message:
					self.protocols[user.get_username()].append(message)

			self.protocols[user.get_username()].extend(["", "- results for evaluation %d:" % index])
			if not recorded_result.check_against(ilias_result, report, self.workarounds):
				all_assertions_ok = False

			for question_title, answers in ilias_result.get_answers().items():
				question = self.questions[question_title]
				question.add_export_coverage(self.coverage, answers, self.language)

		return all_assertions_ok

	def _check_readjustment(self, index, master, all_recorded_results):
		protocol = self.protocols["readjustment"]

		def report(s):
			protocol.append(s)

		if protocol:
			report("")
		report("-- readjustment #%d" % (index + 1))

		index = 0
		retries = 0

		while True:
			with wait_for_page_load(master.driver):
				master.test_driver.goto_scoring_adjustment()

			links = []
			for a in master.driver.find_element_by_name("questionbrowser").find_elements_by_css_selector("table a"):
				question_title = a.text.strip()
				if question_title in self.questions:
					links.append((a, self.questions[question_title]))

			if index >= len(links):
				break

			link, question = links[index]
			with wait_for_page_load(master.driver):
				link.click()

			master.report('readjusting scores for question "%s"' % question.title)

			# close stats window.
			master.driver.execute_script("""
			document.getElementsByClassName("ilOverlay")[0].style.display = "none";
			""")

			try:
				question.readjust_scores(master.driver, report)

				master.report("trying to save.")
				with wait_for_page_load(master.driver):
					master.driver.find_element_by_name("cmd[savescoringfortest]").click()
			except TimeoutException:
				retries += 1
				if retries >= 1:
					raise InteractionException("failed to readjust scores. giving up.")
				else:
					master.report("readjustment failed, retrying.")
				continue

			index += 1
			retries = 0

		report("")
		context = RandomContext(self.questions, self.workarounds)

		# recompute user score's for all questions.
		for question_title, question in self.questions.items():
			for user, result in zip(self.users, all_recorded_results):
				answers = dict()
				for key, value in result.properties.items():
					if key[0] == "question" and key[1] == question_title and key[2] == "answer":
						dimension = key[3]
						answers[dimension] = value
				score = question.compute_score(answers, context)
				score = remove_trailing_zeros(str(score))
				result.update(("question", question_title, "score"), score)
				report("recomputed score for %s / %s as %s based on answer %s" % (
					user.get_username(), question_title, score, json.dumps(answers)))

		# recompute total scores.
		for result in all_recorded_results:
			score = Decimal(0)
			for key, value in result.properties.items():
				if key[0] == "question" and key[2] == "score":
					score += Decimal(value)
			score = remove_trailing_zeros(str(score))
			result.update(("exam", "score", "total"), score)
			result.update(("exam", "score", "gui"), score)

	def prepare(self, master):
		self.language = master.language
		master.report("running with admin language '%s'" % self.language)

		master.report("running with workarounds:")
		self.workarounds.print_status(master.report)
		self.workarounds.print_status(self.protocols["preferences-workarounds"].append)

		master.report("running with settings:")
		self.settings.print_status(master.report)
		self.settings.print_status(self.protocols["preferences-settings"].append)

		header = self.protocols["header"]
		header.append("Tested on ILIAS %s." % self.ilias_version)
		header.append('Using test "%s".' % self.test.get_title())
		header.append("")

		self.protocols["settings"].extend(
			verify_admin_settings(master.driver, self.workarounds, master.report))

		master.report("creating users.")
		# create users for test.
		for i in range(len(self.machines)):
			user = TemporaryUser()
			user.create(master.driver, master.report, i)
			self.users.append(user)
		master.report("done creating users.")

		# print('switching to test "%s".' % test.get_title())
		# goto test.
		if not master.test_driver.goto():
			# if test does not exist, add it first.
			master.test_driver.import_test()
		else:
			master.test_driver.delete_all_participants()
		master.test_driver.configure()

		# grab question definitions from UI.
		self.questions = master.test_driver.get_question_definitions()

	def run_exams(self):
		# now run exams.
		take_exam_args = []
		for i, machine, user in zip(range(len(self.users)), self.machines.values(), self.users):
			take_exam_args.append(
				dict(
					batch_id=self.batch_id,
					report=self.report,
					command=TakeExamCommand(
						machine=machine,
						machine_index=i + 1,
						username=user.get_username(),
						password=user.get_password(),
						test_id=self.test.get_id(),
						questions=self.questions,
						settings=self.settings,
						workarounds=self.workarounds,
						wait_time=self.wait_time,
						admin_lang=self.language)))

		pool = ThreadPool(len(self.users))
		try:
			all_recorded_results = pool.map(take_exam, take_exam_args)
			self.report("master", "waiting for results.")
			pool.close()
			pool.join()
			self.report("master", "all results arrived.")
			return all_recorded_results
		except:
			traceback.print_exc()
			self.report("master", "one of the machines failed: %s." % traceback.format_exc())
			raise Exception("aborted due to error in machines %s." % traceback.format_exc())

	def analyze(self, master, all_recorded_results):
		coverage = self.coverage
		for recorded_result in all_recorded_results:
			coverage.extend(recorded_result.coverage)

		for user, recorded_result in zip(self.users, all_recorded_results):
			self.protocols[user.get_username()] = recorded_result.protocol

		for recorded_result in all_recorded_results:
			self.performance_data.extend(recorded_result.performance)

		worst = get_most_severe_error(all_recorded_results)
		if worst.value > ErrorDomain.none.value:
			raise TestILIASException(worst)

		num_readjustments = max(0, int(self.settings.num_readjustments))
		all_assertions_ok = False

		for i in range(num_readjustments + 1):
			xls, workbook = master.test_driver.fetch_exported_workbook()
			check_workbook_consistency(workbook, master.report, self.workarounds)
			if i == 0:
				self.xls = xls

			all_assertions_ok = self._check_results(
				i, master, workbook, all_recorded_results)
			if not all_assertions_ok:
				break

			if i < num_readjustments:
				self._check_readjustment(
					i, master, all_recorded_results)

		self.add_to_protocol("result", "coverage estimated at %d%%." % coverage.get_percentage())

		if all_assertions_ok:
			self.success = ("OK",)

	def add_to_protocol(self, type, text):
		self.protocols[type].append(text)

	def protocol_master(self, text):
		self.add_to_protocol("master", text)

	def store(self):
		with open_results() as db:
			db.put(batch_id=self.batch_id, success=encode_success(self.success), xls=self.xls,
				protocol=self._make_protocol(self.users), num_users=len(self.users))
			db.put_performance_data(self.performance_data)
			db.put_coverage_data(self.coverage)

	def cleanup(self, master):
		for user in self.users:
			user.destroy(master.driver, master.report)

	def run(self):
		try:
			with in_master(self.batch, self.protocol_master) as master:
				self.prepare(master)

			all_recorded_results = self.run_exams()

			with in_master(self.batch, self.protocol_master) as master:
				self.analyze(master, all_recorded_results)

		except TestILIASException as e:
			self.success = ("FAIL", e.get_error_domain_name())
			traceback.print_exc()
			self.report("master", "exception received: %s." % traceback.format_exc())
			self.add_to_protocol("result", "error: %s" % traceback.format_exc())

		except:
			self.success = ("FAIL", "unknown")
			traceback.print_exc()
			self.report("master", "unexpected exception received: %s." % traceback.format_exc())
			self.add_to_protocol("result", "error: %s" % traceback.format_exc())

		finally:
			self.add_to_protocol("result", "done with status %s." % encode_success(self.success))

			try:
				if self.users:
					with in_master(self.batch, self.protocol_master) as master:
						self.cleanup(master)
			except:
				self.report("master", "cleanup failed: %s." % traceback.format_exc())
				traceback.print_exc()

			try:
				self.store()
			except:
				self.report("master", "error saving result to db: %s." % traceback.format_exc())
			finally:
				self.report("master", "finished with status %s." % self.success)

		return self.success

	def report(self, origin, message):
		self.add_to_protocol("log", "[%s] %s" % (origin, message))
		self.batch.report(origin, message)


class Batch(threading.Thread):
	def __init__(self, machines, ilias_version, test_name, settings, workarounds, wait_time):
		threading.Thread.__init__(self)

		self.sockets = []
		self.buffered = []
		self.print_mutex = Lock()

		self.machines = machines
		self.ilias_version = ilias_version

		self.test_name = test_name
		self.settings = settings
		self.workarounds = workarounds
		self.wait_time = wait_time

		self.machines_lookup = dict((v, k) for k, v in machines.items())
		self.machines_lookup["master"] = "master"
	
		self.test = Test(test_name)
		self.screenshot = None

		self.batch_id = datetime.datetime.today().strftime('%Y%m%d%H%M%S-') + str(uuid.uuid4())
		self._is_done = False

	def get_id(self):
		return self.batch_id

	def run(self):
		#import cProfile
		#profiler = cProfile.Profile()
		#profiler.enable()

		success = ("FAIL", "unknown")
		try:
			asyncio.set_event_loop(asyncio.new_event_loop())

			self.report("master", "connecting to ILIAS %s." % self.ilias_version)

			run = Run(self)
			success = run.run()
		finally:
			try:
				self.report_done(success)
			except:
				print("failed to report done status %s." % run.success)

		#profiler.disable()
			#profiler.print_stats(sort='time')

	def get_screenshot_as_base64(self):
		return self.screenshot

	def is_done(self):
		return self._is_done

	def report(self, origin, message):
		self.print_mutex.acquire()
		try:
			print("[%s] %s" % (origin, message))
		except UnicodeEncodeError:
			# this should not happen, as our docker-compose file sets PYTHONIOENCODING
			traceback.print_exc()
		finally:
			self.print_mutex.release()

		encoded = json.dumps(dict(
			command="report",
			origin=self.machines_lookup.get(origin, "machine_unknown"),
			message=message))

		self.buffered.append(encoded)
		self.flush()

	def flush(self):
		if self.sockets:
			for socket in self.sockets:
				try:
					for buffered in self.buffered:
						socket.write_message(buffered)
				except:
					# web socket failed. whatever.
					traceback.print_exc()

			self.buffered = []

	def add_socket(self, socket):
		self.sockets.append(socket)
		self.flush()

		if self.is_done():
			self.report_done("UNKNOWN")

	def remove_socket(self, socket):
		if socket in self.sockets:
			self.sockets.remove(socket)

	def report_done(self, success):
		self._is_done = True

		self.flush()

		encoded = json.dumps(dict(command="done", success=encode_success(success)))
		for socket in self.sockets:
			try:
				socket.write_message(encoded)
			except:
				pass
