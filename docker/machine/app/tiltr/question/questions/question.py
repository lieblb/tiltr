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

	def has_xls_score(self):
		return True
