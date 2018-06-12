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

from drivers import Login, TestDriver, Test
from ..result import Result


def random_text(n, random_chars):
	return "".join([random.choice(random_chars) for i in xrange(n)])


def get_random_chars(allow_newlines, allow_dollar, allow_clamps):
	random_chars = u" ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789éáèêäöüÄÖÜß?!.-_:;#§\{\}[]()@+-*/~'\""
	if allow_newlines:
		random_chars += "\n"
	if allow_clamps:
		random_chars += "<>"
	if allow_dollar:
		random_chars += "$"
	return random_chars


class TestContext:
	def __init__(self, workarounds):
		self.workarounds = workarounds
		self.cloze_random_chars = get_random_chars(
			allow_newlines=False,
			allow_dollar=workarounds.supports_dollar_in_cloze,
			allow_clamps=workarounds.supports_clamps_in_cloze)
		self.long_text_random_chars = get_random_chars(
			allow_newlines=True,
			allow_dollar=True,
			allow_clamps=True)

	def strip_whitespace(self, value):
		return self.workarounds.strip_whitespace(value)


class RegressionContext(TestContext):
	def prefer_text(self):
		return True  # prefer entering random text to picking correct solution in cloze gaps

	def produce_text(self, size, random_chars):
		special = ""
		for c in "<>\n":
			if c in random_chars:
				special += c
		if len(special) == 0:
			return random_text(size, random_chars)
		s = ""
		while len(s) < size:
			if len(s) % len(special) == 0:
				s += random_text(1, random_chars)
			else:
				s += special[0]
				special = special[1:] + special[:1]
		return s


class RandomContext(TestContext):
	def prefer_text(self):
		return False

	def produce_text(self, size, random_chars):
		return random_text(random.randint(0, size), random_chars)


class TakeExamCommand:
	def __init__(self, from_json=None, **kwargs):
		if from_json:
			data = json.loads(from_json)
			assert data["command"] == "take_exam"
			self.questions = pickle.loads(data["questions"].decode('base64'))
			self.workarounds = pickle.loads(data["workarounds"].decode('base64'))
		else:
			data = kwargs
			self.questions = kwargs["questions"]
			self.workarounds = kwargs["workarounds"]

		self.machine = data["machine"]
		self.machine_index = data["machine_index"]
		self.username = data["username"]
		self.password = data["password"]
		self.test_id = data["test_id"]

	def to_json(self):
		return json.dumps(dict(
			command="take_exam",
			machine=self.machine,
			machine_index=self.machine_index,
			username=self.username,
			password=self.password,
			test_id=self.test_id,
			questions=pickle.dumps(self.questions, pickle.HIGHEST_PROTOCOL).encode('base64'),
			workarounds=pickle.dumps(self.workarounds, pickle.HIGHEST_PROTOCOL).encode('base64')))

	def _pass1(self, driver, report):
		driver.goto_first_question()

		while True:
			driver.randomize_answer()
			if not driver.goto_next_question():
				break

	def _pass2(self, driver, report):
		driver.goto_first_question()

		while True:
			report("verifying answer.")
			driver.verify_answer()
			if not driver.goto_next_question():
				break

	def _pass3(self, driver, report):
		for i in range(len(self.questions)):
			driver.verify_answer()
			if random.random() < 0.5:
				driver.randomize_answer()
			driver.goto_next_or_previous_question()

	def run(self, browser, report):
		report("running test on machine #%s (%s)." % (self.machine_index, self.machine))

		try:
			with Login(browser, report, self.username, self.password):
				test_driver = TestDriver(browser, Test(self.test_id), report)
				test_driver.goto()

				do_regression_tests = True

				if do_regression_tests and self.machine_index == 1:
					random.seed(12345)  # make this a default regression test
					context = RegressionContext(self.workarounds)
				else:
					random.seed()
					context = RandomContext(self.workarounds)
				
				with test_driver.start(context, self.questions) as exam_driver:
					try:
						self._pass1(exam_driver, report)
						self._pass2(exam_driver, report)
						self._pass3(exam_driver, report)

						result = exam_driver.get_expected_result()
					except Exception as e:
						traceback.print_exc()
						report("test aborted with error: %s" % traceback.format_exc())

						result = exam_driver.get_expected_result()
						result.add("failed_with_error", str(e))
						return result
		except:
			traceback.print_exc()
			report("test aborted with error: %s" % traceback.format_exc())
			return None

		report("done running test.")
		return result
