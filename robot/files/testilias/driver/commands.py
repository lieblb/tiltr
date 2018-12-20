#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import pickle
import traceback
import json
import base64
import http

from selenium.common.exceptions import WebDriverException

from .utils import get_driver_error_details
from .drivers import Login, TestDriver, Test
from testilias.data.result import Result, Origin
from testilias.data.context import RegressionContext, RandomContext
from testilias.data.exceptions import ErrorDomain, TestILIASException, InteractionException
from testilias.data.settings import Settings, Workarounds
from testilias.question.answers.answer import Validness


class ExamRobot:
	def __init__(self, exam_driver, context, report, questions, settings):
		self.exam_driver = exam_driver
		self.context = context
		self.report = report
		self.questions = questions
		self.settings = settings

	def _simulate_crash(self):
		if self.context.random.random() * 100 < float(self.settings.crash_frequency):
			self.exam_driver.simulate_crash(
				float(self.settings.autosave_duration) +
				float(self.settings.autosave_tolerance))

	def _give_answer(self):
		while True:
			validness = self.exam_driver.randomize_answer()
			if validness == Validness.VALID:
				break
			self.exam_driver.assert_error_on_save(self.context)

		self._simulate_crash()

	def _verify_answer(self):
		self.exam_driver.verify_answer()

	def _run_answer_pass(self):
		self.exam_driver.goto_first_question()

		if int(self.settings.self_test_fake_error_level) > ErrorDomain.none.value:
			raise TestILIASException(ErrorDomain(int(self.settings.self_test_fake_error_level)))

		while True:
			self._give_answer()
			if not self.exam_driver.goto_next_question():
				break

	def _run_verify_pass(self):
		self.exam_driver.goto_first_question()

		while True:
			self.report("verifying answer.")
			self._verify_answer()
			if not self.exam_driver.goto_next_question():
				break

	def _run_modify_pass(self):
		for i in range(len(self.questions)):
			self.exam_driver.verify_answer()
			if self.context.random.random() * 100 < float(self.settings.modify_answer_frequency):
				self._give_answer()
			self.exam_driver.goto_next_or_previous_question(self.context)

	def run(self, passes):
		for i, p in enumerate(passes):
			self.report("entering pass %d." % i)

			if p == 'A':
				self._run_answer_pass()
			elif p == 'V':
				self._run_verify_pass()
			elif p == 'R':
				self._run_modify_pass()
			else:
				raise RuntimeError("unknown pass type %s" % p)


class TakeExamCommand:
	def __init__(self, from_json=None, **kwargs):
		if from_json:
			data = json.loads(from_json)
			assert data["command"] == "take_exam"
			self.questions = pickle.loads(base64.b64decode(data["questions"].encode("utf-8")))
			self.exam_configuration = pickle.loads(base64.b64decode(data["exam_configuration"].encode("utf-8")))
			self.settings = Settings(from_dict=data["settings"])
			self.workarounds = Workarounds(from_dict=data["workarounds"])
		else:
			data = kwargs
			self.questions = kwargs["questions"]
			self.exam_configuration = kwargs["exam_configuration"]
			self.settings = kwargs["settings"]
			self.workarounds = kwargs["workarounds"]

		self.ilias_url = data["ilias_url"]
		self.machine = data["machine"]
		self.machine_index = data["machine_index"]
		self.username = data["username"]
		self.password = data["password"]
		self.test_id = data["test_id"]
		self.test_url = data["test_url"]
		self.wait_time = data["wait_time"]
		self.admin_lang = data["admin_lang"]

		self.n_deterministic_machines = int(self.settings.num_deterministic_machines)

	def to_json(self):
		return json.dumps(dict(
			command="take_exam",
			ilias_url=self.ilias_url,
			machine=self.machine,
			machine_index=self.machine_index,
			username=self.username,
			password=self.password,
			test_id=self.test_id,
			test_url=self.test_url,
			questions=base64.b64encode(pickle.dumps(self.questions, pickle.HIGHEST_PROTOCOL)).decode("utf-8"),
			exam_configuration=base64.b64encode(pickle.dumps(self.exam_configuration, pickle.HIGHEST_PROTOCOL)).decode("utf-8"),
			settings=self.settings.to_dict(),
			workarounds=self.workarounds.to_dict(),
			wait_time=self.wait_time,
			admin_lang=self.admin_lang))

	def _create_result_with_details(self, driver, report, e, trace):
		files = dict()
		files['trace.txt'] = trace

		url, html, alert = get_driver_error_details(driver)
		if alert:
			files['alert.txt'] = alert
		if html:
			files['error.html'] = html

		filenames = map(lambda s: '%s_%s' % (self.username, s), files.keys())
		error = 'test failed on url %s. for details, see  %s.' % (url, ', '.join(filenames))
		report(error)

		return Result.from_error(Origin.recorded, e.get_error_domain(), error, files)

	def run(self, driver, master_report):
		machine_info = "running test on machine #%s (%s)." % (self.machine_index, self.machine)
		master_report(machine_info)

		try:
			with Login(driver, master_report, self.ilias_url, self.username, self.password):
				test_driver = TestDriver(
					driver, Test(self.test_id), self.username,
					self.workarounds, self.ilias_url, master_report)
				test_driver.goto(self.test_url)

				if self.machine_index <= self.n_deterministic_machines:
					# some machines can operate deterministically as a well-defined baseline regression test
					context = RegressionContext(
						self.machine_index * 73939133, self.questions, self.settings, self.workarounds)
				else:
					context = RandomContext(self.questions, self.settings, self.workarounds)

				exam_driver = test_driver.start(context, self.questions, self.exam_configuration)

				try:
					exam_driver.add_protocol(machine_info)

					def report(s):
						master_report(s)
						exam_driver.add_protocol(s)

					robot = ExamRobot(exam_driver, context, report, self.questions, self.settings)
					robot.run(self.settings.test_passes)

				except TestILIASException as e:
					traceback.print_exc()
					r = self._create_result_with_details(driver, master_report, e, traceback.format_exc())
					exam_driver.copy_protocol(r)
					return r

				exam_driver.close()

				result = exam_driver.get_expected_result(self.admin_lang)
				result.attach_coverage(context.coverage)

		except TestILIASException as e:
			traceback.print_exc()
			return self._create_result_with_details(driver, master_report, e, traceback.format_exc())
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
