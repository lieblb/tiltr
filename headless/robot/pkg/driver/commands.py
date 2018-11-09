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
import http
import time
import re

from selenium.common.exceptions import WebDriverException

from .drivers import Login, TestDriver, Test
from ..result import Result, Origin
from .context import RegressionContext, RandomContext
from ..settings import Settings, Workarounds
from ..question.answers import Validness
from ..exceptions import ErrorDomain, TestILIASException, InteractionException


class TakeExamCommand:
	def __init__(self, from_json=None, **kwargs):
		if from_json:
			data = json.loads(from_json)
			assert data["command"] == "take_exam"
			self.questions = pickle.loads(base64.b64decode(data["questions"].encode("utf-8")))
			self.settings = Settings(from_dict=data["settings"])
			self.workarounds = Workarounds(from_dict=data["workarounds"])
		else:
			data = kwargs
			self.questions = kwargs["questions"]
			self.settings = kwargs["settings"]
			self.workarounds = kwargs["workarounds"]

		self.ilias_url = data["ilias_url"]
		self.machine = data["machine"]
		self.machine_index = data["machine_index"]
		self.username = data["username"]
		self.password = data["password"]
		self.test_id = data["test_id"]
		self.wait_time = data["wait_time"]
		self.admin_lang = data["admin_lang"]

	def to_json(self):
		return json.dumps(dict(
			command="take_exam",
			ilias_url=self.ilias_url,
			machine=self.machine,
			machine_index=self.machine_index,
			username=self.username,
			password=self.password,
			test_id=self.test_id,
			questions=base64.b64encode(pickle.dumps(self.questions, pickle.HIGHEST_PROTOCOL)).decode("utf-8"),
			settings=self.settings.to_dict(),
			workarounds=self.workarounds.to_dict(),
			wait_time=self.wait_time,
			admin_lang=self.admin_lang))

	def _simulate_crash(self, exam_driver):
		if random.random() * 100 < float(self.settings.crash_frequency):
			exam_driver.simulate_crash(
				float(self.settings.autosave_duration) +
				float(self.settings.autosave_tolerance))

	def _randomize_answer(self, exam_driver):
		while True:
			validness = exam_driver.randomize_answer()
			if validness == Validness.VALID:
				break
			exam_driver.assert_error_on_save()

	def _pass1(self, exam_driver, report):
		report("entering pass 1.")
		exam_driver.goto_first_question()

		if int(self.settings.self_test_fake_error_level) > ErrorDomain.none.value:
			raise TestILIASException(ErrorDomain(int(self.settings.self_test_fake_error_level)))

		while True:
			self._randomize_answer(exam_driver)
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
			if random.random() * 100 < float(self.settings.modify_answer_frequency):
				self._randomize_answer(exam_driver)
				self._simulate_crash(exam_driver)
			exam_driver.goto_next_or_previous_question()

	def run(self, driver, master_report):
		machine_info = "running test on machine #%s (%s)." % (self.machine_index, self.machine)
		master_report(machine_info)

		try:
			with Login(driver, master_report, self.ilias_url, self.username, self.password):
				test_driver = TestDriver(driver, Test(self.test_id), self.workarounds, self.ilias_url, master_report)
				test_driver.goto()

				do_regression_tests = True

				if do_regression_tests and self.machine_index == 1:
					random.seed(12345)  # make this a default regression test
					context = RegressionContext(self.questions, self.workarounds)
				else:
					random.seed()
					context = RandomContext(self.questions, self.workarounds)

				exam_driver = test_driver.start(context, self.questions)

				try:
					exam_driver.add_protocol(machine_info)

					def report(s):
						master_report(s)
						exam_driver.add_protocol(s)

					self._pass1(exam_driver, report)
					self._pass2(exam_driver, report)
					self._pass3(exam_driver, report)
				except TestILIASException as e:
					traceback.print_exc()
					master_report("test aborted: %s" % traceback.format_exc())
					r = Result.from_error(Origin.recorded, e.get_error_domain(), traceback.format_exc())
					exam_driver.copy_protocol(r)
					return r

				exam_driver.close()

				result = exam_driver.get_expected_result(self.admin_lang)
				result.attach_coverage(context.coverage)

		except TestILIASException as e:
			traceback.print_exc()
			master_report("test aborted: %s" % traceback.format_exc())
			return Result.from_error(Origin.recorded, e.get_error_domain(), traceback.format_exc())
		except WebDriverException as webdriver_error:
			e = InteractionException(str(webdriver_error))
			traceback.print_exc()
			master_report("test aborted: %s" % traceback.format_exc())
			return Result.from_error(Origin.recorded, e.get_error_domain(), traceback.format_exc())
		except (BrokenPipeError, http.client.RemoteDisconnected):
			master_report("test aborted: %s" % traceback.format_exc())
			return Result.from_error(Origin.recorded, ErrorDomain.interaction, traceback.format_exc())
		except:
			traceback.print_exc()
			master_report("test aborted with an unexpected error: %s" % traceback.format_exc())
			return None

		master_report("done running test.")
		return result
