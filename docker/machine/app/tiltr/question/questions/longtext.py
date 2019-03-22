#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from decimal import *

from .question import Question
from ...data.exceptions import *
from tiltr.driver.utils import set_element_value


class LongTextQuestion(Question):
	@staticmethod
	def _get_ui(driver):
		if not driver.find_element_by_id("scoring_mode_non").is_selected():
			raise NotImplementedException(
				"only manual scoring is currently supported for tests with LongTextQuestions")

		return Decimal(
			driver.find_element_by_id("non_keyword_points").get_attribute('value'))

	@staticmethod
	def _set_ui(driver, score):
		points = driver.find_element_by_id("non_keyword_points")
		set_element_value(driver, points, str(score))

	def __init__(self, driver, title, settings):
		super().__init__(title)

		self.length = int(settings.max_long_text_length)
		self._maximum_score = LongTextQuestion._get_ui(driver)

	def get_maximum_score(self):
		return self._maximum_score

	def create_answer(self, driver, *args):
		from ..answers.longtext import LongTextAnswerTinyMCE
		return LongTextAnswerTinyMCE(driver, self, *args)

	def initialize_coverage(self, coverage, context):
		for args in coverage.text_cases(self.length, context):
			coverage.add_case(self, "verify", *args)
			coverage.add_case(self, "export", *args)

	def add_verify_coverage(self, coverage, answers):
		for text in answers.values():
			for args in coverage.text_cases_occurred(text):
				coverage.case_occurred(self, "verify", *args)

	def add_export_coverage(self, coverage, answers, language):
		for text in answers.values():
			for args in coverage.text_cases_occurred(text):
				coverage.case_occurred(self, "export", *args)

	def get_random_answer(self, context):
		text = context.produce_text(self.length, context.long_text_random_chars)
		return text, self.compute_score(text, context)

	def readjust_scores(self, driver, context, report):
		maximum_score = Decimal(context.random.randint(1, 100)) / Decimal(10)
		self._set_ui(driver, maximum_score)
		self._maximum_score = maximum_score
		report('readjusted score to %s.' % maximum_score)
		return True, list()

	def compute_score(self, text, context):
		return Decimal(0)
