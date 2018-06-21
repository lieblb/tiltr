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

from ..result import Result, Origin, ErrorDomain
from ..result import open_results
from ..result.workbook import workbook_to_result

from .commands import TakeExamCommand
from .drivers import Login, TemporaryUser, TestDriver, Test, verify_admin_settings
from .utils import wait_for_page_load

from ..question import *  # for pickling
from ..workarounds import Workarounds  # for pickling

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

monitor_mutex = Lock()

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
			raise Exception("start call failed: %s" % r.status_code)

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
				raise Exception("monitor call failed: %s" % r.status_code)
		
			messages = json.loads(r.text)

			for command, payload in messages:
				if command == "ECHO":
					report(machine, payload)
				elif command == "DONE":
					result_json = payload
				elif command == "ERROR":
					raise Exception(payload)
				else:
					raise Exception("unknown command %s" % command)

			index += len(messages)

	except:
		traceback.print_exc()
		report("master", "machine %s failed: %s" % (machine, traceback.format_exc()))
		return Result.from_error(Origin.recorded, ErrorDomain.qa, traceback.format_exc())

	assert result_json is not None
	report("master", "received take_exam results from %s." % machine)
	return Result(from_json=result_json)


class Run:
	def __init__(self, batch):
		self.success = "FAIL"

		self.xls = b""
		self.performance_data = []
		self.users = []
		self.protocols = dict(header=[], prolog=[], epilog=[], result=[], readjustment=[])

		self.report = batch.report

		self.machines = batch.machines
		self.workarounds = batch.workarounds
		self.batch_id = batch.batch_id
		self.ilias_version = batch.ilias_version
		self.test = batch.test
		self.wait_time = batch.wait_time

	def _had_webdriver_errors(self, all_expected_results):
		for recorded_result in all_expected_results:
			if recorded_result.has_error(ErrorDomain.webdriver):
				return True
		return False

	def _make_protocol(self, users):
		parts = list()

		parts.extend(self.protocols.get("header", []))
		parts.extend(self.protocols.get("result", []))
		parts.append("")
		parts.extend(self.protocols.get("prolog", []))
		parts.append("")

		for user in users:
			parts.append("-" * 80)
			parts.append("protocol for user %s:" % user.get_username())
			parts.extend(self.protocols.get(user.get_username(), []))
			parts.append("-" * 80)
			parts.append("")

		parts.append("")
		parts.extend(self.protocols.get("readjustment", []))

		return "\n".join(parts)

	def _check_results(self, users, test_driver, workbook, all_recorded_results, report_master):
		all_assertions_ok = True

		gui_scores = test_driver.get_gui_scores([user.get_username() for user in users])

		for user, recorded_result in zip(users, all_recorded_results):
			report_master("checking results for user %s." % user.get_username())

			# fetch and check results.
			ilias_result = workbook_to_result(
				workbook, user.get_username(), report_master)

			# check score via gui participants tab as well.
			ilias_result.add(("exam", "score", "gui"), gui_scores[user.get_username()])

			def report(message):
				if message:
					self.protocols[user.get_username()].append(message)

			self.protocols[user.get_username()].extend(["", "results:"])
			if not recorded_result.check_against(ilias_result, report, self.workarounds):
				all_assertions_ok = False

		return all_assertions_ok

	def _check_readjustment(self, driver, test_driver, questions, all_recorded_results):
		protocol = self.protocols["readjustment"]

		def report(s):
			protocol.append(s)

		index = 0
		retries = 0

		while True:
			with wait_for_page_load(browser):
				test_driver.goto_scoring_adjustment()

			links = []
			for a in browser.find_by_name("questionbrowser").first.find_by_css("table a"):
				question_title = a.text.strip()
				if question_title in questions:
					links.append((a, questions[question_title]))

			if index >= len(links):
				break

			link, question = links[index]
			with wait_for_page_load(browser):
				link.click()

			self.report_master('readjusting scores for question "%s"' % question.title)

			# close stats window.
			browser.find_by_css("#adjustment_stats_container_aggr_usr_answ a").first.click()

			save_ok = True
			try:
				question.readjust_scores(browser, report)

				with wait_for_page_load(browser):
					browser.find_by_name("cmd[savescoringfortest]").first.click()
			except TimeoutException:
				# this can take really long sometimes.
				save_ok = False

			if save_ok:
				index += 1
				retries = 0
			else:
				retries += 1
				if retries > 5:
					raise Exception("failed to readjust scores. giving up.")
				else:
					self.report_master("readjustment failed, retrying.")

		# recompute user score's for all questions.
		for question_title, question in questions.items():
			answers = dict()
			for result in all_recorded_results:
				for key, value in result.properties.items():
					if key[0] == "question" and key[1] == question_title and key[2] == "answer":
						dimension = key[3]
						answers[dimension] = value
				score = question.compute_score(answers)
				result.update(("question", question_title, "score"), score)

		# recompute total scores.
		for result in all_recorded_results:
			score = Decimal(0)
			for key, value in result.properties.items():
				if key[0] == "question" and key[2] == "score":
					score += value
			result.update(("exam", "score", "total"), score)
			result.update(("exam", "score", "gui"), score)

	def prepare(self, driver, test_driver, report_master):
		report_master("running with workaround settings:")
		self.workarounds.print_status(report_master)

		header = self.protocols["header"]
		header.append("Tested on ILIAS %s." % self.ilias_version)
		header.append('Using test "%s".' % self.test.get_title())
		header.append("")

		prolog = self.protocols["header"]
		prolog.append("-" * 80)
		prolog.append("Workarounds:")
		self.workarounds.print_status(prolog.append)

		prolog.append("-" * 80)
		prolog.append("ILIAS Settings:")
		prolog.extend(verify_admin_settings(driver, self.workarounds, report_master))

		report_master("creating users.")
		# create users for test.
		for i in range(len(self.machines)):
			user = TemporaryUser()
			user.create(driver, report_master, i)
			self.users.append(user)
		report_master("done creating users.")

		# print('switching to test "%s".' % test.get_title())
		# goto test.
		if not test_driver.goto():
			# if test does not exist, add it first.
			test_driver.import_test()
		else:
			test_driver.make_online()
			test_driver.delete_all_participants()

		# grab question definitions from UI.
		self.questions = test_driver.get_question_definitions()

	def run_exams(self, report_master):
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
						workarounds=self.workarounds,
						wait_time=self.wait_time)))

		pool = ThreadPool(len(self.users))
		try:
			self.all_recorded_results = pool.map(take_exam, take_exam_args)
			pool.close()
			pool.join()
		except:
			traceback.print_exc()
			report_master("one of the machines failed: %s." % traceback.format_exc())
			raise Exception("aborted due to error in machines %s." % traceback.format_exc())

	def analyze(self, driver, test_driver, report_master):
		for user, recorded_result in zip(self.users, self.all_recorded_results):
			self.protocols[user.get_username()] = recorded_result.protocol

		for recorded_result in self.all_recorded_results:
			self.performance_data.extend(recorded_result.performance)

		if self._had_webdriver_errors(self.all_recorded_results):
			# there were webdriver problems during the test (e.g. we could not control Firefox
			# properly), which means this result is not a valid test. do not mark this as a FAIL.
			self.success = "CRASH"
			raise Exception("aborted due to webdriver errors")

		num_readjustments = 0
		all_assertions_ok = False

		for i in range(num_readjustments + 1):
			xls, workbook = test_driver.fetch_exported_workbook(self.batch_id, self.workarounds)
			if i == 0:
				self.xls = xls

			all_assertions_ok = self._check_results(
				self.users, test_driver, workbook, self.all_recorded_results, report_master)
			if not all_assertions_ok:
				break

			if i < num_readjustments:
				self._check_readjustment(driver, test_driver, self.questions, self.all_recorded_results)

		if all_assertions_ok:
			self.success = "OK"

	def add_to_protocol(self, type, text):
		self.protocols[type].append(text)

	def store(self):
		with open_results() as db:
			db.put(batch_id=self.batch_id, success=self.success, xls=self.xls,
				protocol=self._make_protocol(self.users), num_users=len(self.users))
			db.put_performance_data(self.performance_data)

	def close(self, driver, test_driver, report_master):
		for user in self.users:
			user.destroy(driver, report_master)


class Batch(threading.Thread):
	def __init__(self, machines, ilias_version, test_name, workarounds, wait_time):
		threading.Thread.__init__(self)

		self.sockets = []
		self.buffered = []
		self.machines = machines
		self.ilias_version = ilias_version

		self.test_name = test_name
		self.workarounds = workarounds
		self.wait_time = wait_time

		self.machines_lookup = dict((v, k) for k, v in machines.items())
		self.machines_lookup["master"] = "master"
	
		self.test = Test(test_name)
		self.screenshot = None

		self.batch_id = datetime.datetime.today().strftime('%Y%m%d%H%M%S-') + str(uuid.uuid4())
		self._is_done = False
		self.print_mutex = Lock()

	def get_id(self):
		return self.batch_id

	def run(self):
		asyncio.set_event_loop(asyncio.new_event_loop())

		#import cProfile
		#profiler = cProfile.Profile()
		#profiler.enable()

		try:
			self.report("master", "connecting to ILIAS %s." % self.ilias_version)

			# moz:webdriverClick needed for file uploads to work.
			capabilities = {"moz:webdriverClick": False}

			def run_in_master(f):
				self.report("master", "connecting to client browser...")
				with Browser(headless=True, capabilities=capabilities, wait_time=self.wait_time) as browser:
					def report_master(message):
						try:
							self.screenshot = browser.driver.get_screenshot_as_base64()
						except:
							self.report("master", "failed to create screenshot.")

						self.report("master", message)

					test_driver = TestDriver(browser.driver, self.test, report_master)

					with Login(browser.driver, report_master, "root", "odysseus"):
						f(browser.driver, test_driver, report_master)

			self._run_tests(run_in_master)

		finally:
			pass

			#profiler.disable()
			#profiler.print_stats(sort='time')

	def get_screenshot_as_base64(self):
		return self.screenshot

	def report(self, origin, message):
		if message == "!screenshot":
			return

		if message == "!traceback":
			try:
				message = traceback.format_exc()
			except:
				message = "something bad happened. cannot produce a traceback."

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

	def is_done(self):
		return self._is_done

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
			self.report_done()

	def remove_socket(self, socket):
		if socket in self.sockets:
			self.sockets.remove(socket)

	def report_done(self):
		self._is_done = True

		self.flush()

		encoded = json.dumps(dict(command="done"))
		for socket in self.sockets:
			try:
				socket.write_message(encoded)
			except:
				pass

	def _run_tests(self, run_in_master):
		run = Run(self)

		self.report("master", "starting batch %s." % self.batch_id)
		try:
			run_in_master(run.prepare)
			run.run_exams(lambda s: self.report("master", s))
			run_in_master(run.analyze)

		except WebDriverException:
			traceback.print_exc()
			self.report("master", "web driver exception received: %s." % traceback.format_exc())
			run.add_to_protocol("result", "web driver error: %s" % traceback.format_exc())
			run.success = "CRASH"

		except:
			traceback.print_exc()
			self.report("master", "exception received: %s." % traceback.format_exc())
			run.add_to_protocol("result", "error: %s" % traceback.format_exc())

		finally:
			run.add_to_protocol("result", "done with status %s." % run.success)

			try:
				run.store()
			except:
				self.report("master", "error saving result to db: %s." % traceback.format_exc())
			finally:
				self.report("master", "finished with status %s." % run.success)

				try:
					self.report_done()
				except:
					print("failed to report done status %s." % run.success)

				run_in_master(run.close)
