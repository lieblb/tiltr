#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import json


class Coverage:
	def __init__(self, questions=None, context=None, from_dict=None):
		if from_dict:
			self._cases = set(tuple(x) for x in from_dict["cases"])
			self._occurred = set(tuple(x) for x in from_dict["occurred"])
		else:
			self._cases = set()
			self._occurred = set()
			if questions:
				for question in questions.values():
					question.initialize_coverage(self, context)

	def case_occurred(self, question, *args):
		self._occurred.add(tuple([question.title] + list(args)))

	def add_case(self, question, *args):
		self._cases.add(tuple([question.title] + list(args)))

	def as_dict(self):
		return dict(
			cases=list(self._cases),
			occurred=list(self._occurred))

	def get_cases(self):
		return list(self._cases)

	def get_occurrences(self):
		return list(self._occurred)

	def extend(self, coverage):
		self._cases.update(coverage._cases)
		self._occurred.update(coverage._occurred)

	def get_percentage(self):
		if len(self._cases) == 0:
			return 0
		n = 0
		for occurred in self._occurred:
			if occurred in self._cases:
				n += 1
		return (n * 100.0) / len(self._cases)