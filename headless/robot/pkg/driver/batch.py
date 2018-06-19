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

import asyncio
import requests
import json
import traceback

import time
import datetime
import uuid


def take_exam(args):
	asyncio.set_event_loop(asyncio.new_event_loop())

	command = args["command"]
	machine = command.machine
	batch_id = args["batch_id"]
	report = args["report"]

	result_json = None
	report("master", "passing take_exam to %s." % machine)
	sleep_time = 1

	try:
		r = requests.post("http://%s:8888/start/%s" % (machine, batch_id),
			data={"command_json": command.to_json()})
		if r.status_code != 200:
			raise Exception("start call failed: %s" % r.status_code)

		report("master", "test started on %s." % machine)

		index = 0

		while result_json is None:
			time.sleep(sleep_time)

			r = requests.get("http://%s:8888/monitor/%s/%d" % (machine, batch_id, index))
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
		self.browser = None
		self.screenshot = None

		self.batch_id = datetime.datetime.today().strftime('%Y%m%d%H%M%S-') + str(uuid.uuid4())
		self._is_done = False
		self.print_mutex = Lock()
		self.protocols = dict(header=[], prolog=[], epilog=[], result=[], readjustment=[])

	def get_id(self):
		return self.batch_id

	def run(self):
		asyncio.set_event_loop(asyncio.new_event_loop())

		try:
			self.report_master("connecting to ILIAS %s." % self.ilias_version)

			# moz:webdriverClick needed for file uploads to work.
			capabilities = {"moz:webdriverClick": False}

			with Browser(headless=True, capabilities=capabilities, wait_time=self.wait_time) as browser:
				self.browser = browser

				test_driver = TestDriver(browser, self.test, self.report_master)

				with Login(browser, self.report_master, "root", "odysseus"):
					self._run_tests(browser, test_driver)
		finally:
			self.browser = None

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
		self.sockets.remove(socket)

	def report_master(self, message):
		self.report("master", message)

		if self.browser:
			try:
				self.screenshot = self.browser.driver.get_screenshot_as_base64()
			except:
				self.report("master", "failed to create screenshot.")

	def report_done(self):
		self._is_done = True

		self.flush()

		encoded = json.dumps(dict(command="done"))
		for socket in self.sockets:
			try:
				socket.write_message(encoded)
			except:
				pass

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

	def _had_webdriver_errors(self, all_expected_results):
		for recorded_result in all_expected_results:
			if recorded_result.has_error(ErrorDomain.webdriver):
				return True
		return False

	def _check_results(self, users, test_driver, workbook, all_recorded_results):
		all_assertions_ok = True

		for user, recorded_result in zip(users, all_recorded_results):
			self.report_master("checking results for user %s." % user.get_username())

			# fetch and check results.
			ilias_result = workbook_to_result(
				workbook, user.get_username(), self.report_master)

			# check score via gui participants tab as well.
			ilias_result.add(("exam", "score", "gui"), test_driver.get_score(user.get_username()))

			def report(message):
				if message:
					self.protocols[user.get_username()].append(message)

			self.protocols[user.get_username()].extend(["", "results:"])
			if not recorded_result.check_against(ilias_result, report, self.workarounds):
				all_assertions_ok = False

		return all_assertions_ok

	def _check_readjustment(self, browser, test_driver, questions, all_recorded_results):
		protocol = self.protocols["readjustment"]

		def report(s):
			protocol.append(s)

		index = 0

		while True:
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

			# close stats window.
			browser.find_by_css("#adjustment_stats_container_aggr_usr_answ a").first.click()

			question.readjust_scores(browser, report)

			index += 1

		for question_title, question in questions.items():
			for result in all_recorded_results:
				for key, value in result.properties.items():
					if key[0] == "question" and key[1] == question_title:
						pass
						# question.compute_score()

		#	for dimension_title, dimension_value in encoded["answers"].items():
		#		result.add("question.%s.%s" % (question_title, dimension_title), dimension_value)


	def _run_tests(self, browser, test_driver):
		success = "FAIL"
		xls = ""
		performance_data = []

		users = []

		self.report_master("starting batch %s." % self.batch_id)
		try:
			self.report_master("running with workaround settings:")
			self.workarounds.print_status(self.report_master)

			self.report_master("verifying admin settings.")

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
			prolog.extend(verify_admin_settings(browser, self.workarounds))

			self.report_master("creating users.")
			# create users for test.
			for i in range(len(self.machines)):
				user = TemporaryUser()
				user.create(self.browser, self.report_master, i)
				users.append(user)
			self.report_master("done creating users.")

			# print('switching to test "%s".' % test.get_title())
			# goto test.
			if not test_driver.goto():
				# if test does not exist, add it first.
				test_driver.import_test()
			else:
				test_driver.make_online()
				test_driver.delete_all_participants()
		
			# grab question definitions from UI.
			questions = test_driver.get_question_definitions()

			# now run exams.
			take_exam_args = []
			for i, machine, user in zip(range(len(users)), self.machines.values(), users):
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
							questions=questions,
							workarounds=self.workarounds,
							wait_time=self.wait_time)))

			pool = ThreadPool(len(users))
			try:
				all_recorded_results = pool.map(take_exam, take_exam_args)
				pool.close()
				pool.join()
			except:
				traceback.print_exc()
				self.report_master("one of the machines failed: %s." % traceback.format_exc())
				raise Exception("aborted due to error in machines %s." % traceback.format_exc())

			for user, recorded_result in zip(users, all_recorded_results):
				self.protocols[user.get_username()] = recorded_result.protocol

			if self._had_webdriver_errors(all_recorded_results):
				# there were webdriver problems during the test (e.g. we could not control Firefox
				# properly), which means this result is not a valid test. do not mark this as a FAIL.
				success = "CRASH"
				raise Exception("aborted due to webdriver errors")

			xls, workbook = test_driver.fetch_exported_workbook(self.batch_id, self.workarounds)

			all_assertions_ok = self._check_results(
				users, test_driver, workbook, all_recorded_results)

			if all_assertions_ok:
				success = "OK"

			#self._check_readjustment(browser, test_driver, questions, all_recorded_results)

			for recorded_result in all_recorded_results:
				performance_data.extend(recorded_result.performance)

		except:
			traceback.print_exc()
			self.report_master("exception received: %s." % traceback.format_exc())
			self.protocols["result"].append("error: %s" % traceback.format_exc())

		finally:
			self.protocols["result"].append("done with status %s." % success)

			try:
				with open_results() as db:
					db.put(batch_id=self.batch_id, success=success, xls=xls,
						protocol=self._make_protocol(users), num_users=len(users))
					db.put_performance_data(performance_data)
			finally:
				self.report_master("finished with status %s." % success)

				try:
					self.report_done()
				except:
					print("failed to report done status %s." % success)

				for user in users:
					user.destroy(self.browser, self.report_master)
