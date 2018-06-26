#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import pickle
import traceback
import json
import random
import base64
import time
import re

from selenium.common.exceptions import WebDriverException

from .drivers import Login, TestDriver, Test
from ..result import Result, Origin, ErrorDomain
from .context import RegressionContext, RandomContext


class TakeExamCommand:
	def __init__(self, from_json=None, **kwargs):
		if from_json:
			data = json.loads(from_json)
			assert data["command"] == "take_exam"
			self.questions = pickle.loads(base64.b64decode(data["questions"].encode("utf-8")))
			self.workarounds = pickle.loads(base64.b64decode(data["workarounds"].encode("utf-8")))
		else:
			data = kwargs
			self.questions = kwargs["questions"]
			self.workarounds = kwargs["workarounds"]

		self.machine = data["machine"]
		self.machine_index = data["machine_index"]
		self.username = data["username"]
		self.password = data["password"]
		self.test_id = data["test_id"]
		self.wait_time = data["wait_time"]

		self.crash_percentage = 1

	def to_json(self):
		return json.dumps(dict(
			command="take_exam",
			machine=self.machine,
			machine_index=self.machine_index,
			username=self.username,
			password=self.password,
			test_id=self.test_id,
			questions=base64.b64encode(pickle.dumps(self.questions, pickle.HIGHEST_PROTOCOL)).decode("utf-8"),
			workarounds=base64.b64encode(pickle.dumps(self.workarounds, pickle.HIGHEST_PROTOCOL)).decode("utf-8"),
			wait_time=self.wait_time))

	def _simulate_crash(self, exam_driver):
		if random.random() * 100 < self.crash_percentage:
			exam_driver.simulate_crash(10.0)

	def _pass1(self, exam_driver, report):
		report("entering pass 1.")
		exam_driver.goto_first_question()

		while True:
			exam_driver.randomize_answer()
			self._simulate_crash(exam_driver)
			if not exam_driver.goto_next_question():
				break

	def _pass2(self, exam_driver, report):
		report("entering pass 2.")
		exam_driver.goto_first_question()

		while True:
			report("verifying answer.")
			exam_driver.verify_answer()
			if not exam_driver.goto_next_question():
				break

	def _pass3(self, exam_driver, report):
		report("entering pass 3.")
		for i in range(len(self.questions)):
			exam_driver.verify_answer()
			if random.random() < 0.5:
				exam_driver.randomize_answer()
				self._simulate_crash(exam_driver)
			exam_driver.goto_next_or_previous_question()

	def run(self, driver, report):
		report("running test on machine #%s (%s)." % (self.machine_index, self.machine))

		try:
			with Login(driver, report, self.username, self.password):
				test_driver = TestDriver(driver, Test(self.test_id), self.workarounds, report)
				test_driver.goto()

				do_regression_tests = True

				if do_regression_tests and self.machine_index == 1:
					random.seed(12345)  # make this a default regression test
					context = RegressionContext(self.questions, self.workarounds)
				else:
					random.seed()
					context = RandomContext(self.questions, self.workarounds)

				with test_driver.start(context, self.questions) as exam_driver:
					try:
						self._pass1(exam_driver, report)
						self._pass2(exam_driver, report)
						self._pass3(exam_driver, report)

						result = exam_driver.get_expected_result()
						result.attach_coverage(context.coverage)
					except WebDriverException:
						traceback.print_exc()
						report("test aborted with webdriver error: %s" % traceback.format_exc())
						r = Result.from_error(Origin.recorded, ErrorDomain.webdriver, traceback.format_exc())
						exam_driver.copy_protocol(r)
						return r
					except:
						traceback.print_exc()
						report("test aborted with error: %s" % traceback.format_exc())
						r = Result.from_error(Origin.recorded, ErrorDomain.qa, traceback.format_exc())
						exam_driver.copy_protocol(r)
						return r
		except WebDriverException:
			traceback.print_exc()
			report("test aborted with webdriver error: %s" % traceback.format_exc())
			return Result.from_error(Origin.recorded, ErrorDomain.webdriver, traceback.format_exc())
		except:
			traceback.print_exc()
			report("test aborted with error: %s" % traceback.format_exc())
			return None

		report("done running test.")
		return result
