#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from decimal import *
from selenium.common.exceptions import NoSuchElementException

from .question import Question
from tiltr.data.exceptions import *
from tiltr.driver.utils import set_element_value


class PaintQuestion(Question):
	def __init__(self, driver, title, settings):
		super().__init__(title)

	def get_maximum_score(self, context):
		return Decimal(0)

	def create_answer(self, driver, *args):
		from ..answers.paint import PaintAnswer
		return PaintAnswer(driver, self, *args)

	def initialize_coverage(self, coverage, context):
		pass

	def add_export_coverage(self, coverage, answers, language):
		pass

	def get_random_answer(self, context):
		return context.random.randint(1, 255), Decimal(0)

	def readjust_scores(self, driver, context, report):
		return False, list()

	def compute_score(self, answers, context):
		return Decimal(0)

	def has_xls_score(self):
		return False
