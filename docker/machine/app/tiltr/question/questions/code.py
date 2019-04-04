#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from decimal import *

from .question import Question
from tiltr.data.exceptions import *


class CodeQuestion(Question):
	def __init__(self, driver, title, settings):
		super().__init__(title)
		self.length = int(settings.max_long_text_length)

	def get_maximum_score(self, context):
		return Decimal(0)

	def create_answer(self, driver, *args):
		from ..answers.code import CodeAnswer
		return CodeAnswer(driver, self, *args)

	def initialize_coverage(self, coverage, context):
		pass

	def add_export_coverage(self, coverage, answers, language):
		pass

	def get_random_answer(self, context):
		text = context.produce_text(self.length, context.long_text_random_chars)
		return text, self.compute_score(text, context)

	def readjust_scores(self, driver, context, report):
		return False, list()

	def compute_score(self, answers, context):
		return Decimal(0)
