#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from typing import Dict
from decimal import *

from selenium.common.exceptions import NoSuchElementException

from .question import Question
from tiltr.data.exceptions import *
from tiltr.driver.utils import set_element_value


class PaintQuestion(Question):
	def __init__(self, driver, title, settings):
		super().__init__(title)

		self._maximum_score = Decimal(
			driver.find_element_by_css_selector('input[name="points"]').get_attribute('value'))

	def get_maximum_score(self, context):
		return self._maximum_score

	def create_answer(self, driver, *args):
		from ..answers.paint import PaintAnswer
		return PaintAnswer(driver, self, *args)

	def initialize_coverage(self, coverage, context):
		pass

	def add_export_coverage(self, coverage, answers, language):
		pass

	def get_random_answer(self, context):
		return context.random.randint(1, 255), Decimal(0)

	def readjust_scores(self, driver, actual_answers, context, report):
		return False, list()

	def compute_score(self, answers: Dict[str, Decimal], context: 'TestContext'):
		return Decimal(0)

	def has_xls_score(self):
		return False

	def get_answer_from_details_view(self, view):
		answer_view = view.find_element_by_css_selector(".ilc_question_Standard")
		answer_view.find_element_by_css_selector("img")
		return None
