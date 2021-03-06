#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from typing import Tuple
from decimal import *

import selenium


class Question:
	def __init__(self, title: str):
		self.title = title

	def create_answer(self, driver: selenium.webdriver.Remote, *args) -> 'Answer':
		raise NotImplementedError()

	def initialize_coverage(self, coverage: 'Coverage', context: 'TestContext'):
		raise NotImplementedError()

	def add_export_coverage(self, coverage: 'Coverage', answers, language):
		raise NotImplementedError()

	def get_random_answer(self, context: 'TestContext'):
		raise NotImplementedError()

	def readjust_scores(self, driver, actual_answers, context: 'TestContext', report):
		raise NotImplementedError()

	def compute_score(self, answers, context: 'TestContext'):
		raise NotImplementedError()

	def get_maximum_score(self, context: 'TestContext'):
		return Decimal(0)

	def explain_maximum_score(self, context: 'TestContext', report):
		pass

	def compute_score_from_result(self, result, context: 'TestContext'):
		answers = dict()
		for key, value in result.properties.items():
			if key[0] == "question" and key[1] == self.title and key[2] == "answer":
				dimension = key[3]
				answers[dimension] = value
		return self.compute_score(answers, context)

	def has_xls_score(self):
		return True

	def parse_xls_row(self, sheet, row: int) -> Tuple[str, str]:
		key = sheet.cell(row=row, column=1).value
		if key is None:
			return None

		value = sheet.cell(row=row, column=2).value
		if value is None:
			value = ""  # an empty gap in cloze question, for example

		return key, value

	def get_answer_from_details_view(self, view):
		return None

	def can_score_manually(self) -> bool:
		return False
