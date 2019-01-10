#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from decimal import *

from .question import Question
from ...data.exceptions import *


class LongTextQuestion(Question):
	def __init__(self, driver, title, settings):
		self.title = title
		self.length = int(settings.max_long_text_length)

		if not driver.find_element_by_id("scoring_mode_non").is_selected():
			raise NotImplementedException("only manual scoring is supported for tests with LongTextQuestion")

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

	def readjust_scores(self, driver, random, report):
		pass

	def compute_score(self, text, context):
		return Decimal(0)
