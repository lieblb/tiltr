#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#


class Question:
	def __init__(self, title):
		self.title = title

	def create_answer(self, driver, *args):
		raise NotImplementedError()

	def initialize_coverage(self, coverage, context):
		raise NotImplementedError()

	def add_export_coverage(self, coverage, answers, language):
		raise NotImplementedError()

	def get_random_answer(self, context):
		raise NotImplementedError()

	def readjust_scores(self, driver, context, report):
		raise NotImplementedError()

	def compute_score(self, answers, context):
		raise NotImplementedError()

	def compute_score_from_result(self, result, context):
		answers = dict()
		for key, value in result.properties.items():
			if key[0] == "question" and key[1] == self.title and key[2] == "answer":
				dimension = key[3]
				answers[dimension] = value
		return self.compute_score(answers, context)

	def has_xls_score(self):
		return True

	def parse_xls_row(self, sheet, row):
		key = sheet.cell(row=row, column=1).value
		if key is None:
			return None

		value = sheet.cell(row=row, column=2).value
		if value is None:
			value = ""  # an empty gap in cloze question, for example

		return key, value
