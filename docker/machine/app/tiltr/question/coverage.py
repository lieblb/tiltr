#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from typing import List, Dict, Tuple

from tiltr.question.questions.question import Question

from collections import Counter


class Coverage:
	def __init__(self, questions: List[Question] = None, context: 'TestContext' = None, from_dict: Dict = None):
		self._max_char_occ = 2
		if from_dict:
			self._cases = set(tuple(x) for x in from_dict["cases"])
			self._occurred = set(tuple(x) for x in from_dict["occurred"])
		else:
			self._cases = set()
			self._occurred = set()
			if questions:
				for question in questions.values():
					question.initialize_coverage(self, context)

	def case_occurred(self, question: Question, *args):
		self._occurred.add(tuple([question.title] + list(args)))

	def add_case(self, question: Question, *args):
		self._cases.add(tuple([question.title] + list(args)))

	def text_cases_occurred(self, text: str):
		yield ("len", len(text))

		for a, b in zip(text, text[1:]):
			yield ("2gram%s%s" % (a, b))

		counts = Counter()
		for char in text:
			counts[char] += 1

		for char, count in counts.items():
			for i in range(1, 1 + min(count, self._max_char_occ)):
				yield ("char%d" % i, char)

	def text_cases(self, max_size: int, alphabet: str, context: 'TestContext'):
		for char in alphabet:
			for i in range(1, 1 + self._max_char_occ):
				yield ("char%d" % i, char)

		for a in alphabet:
			for b in alphabet:
				yield ("2gram%s%s" % (a, b))

		for i in range(max_size):
			if i > 0 or not context.workarounds.disallow_empty_answers:
				yield ("len", i)

	def as_dict(self) -> Dict[str, List[Tuple]]:
		return dict(
			cases=list(self._cases),
			occurred=list(self._occurred))

	def get_cases(self) -> List[Tuple]:
		return list(self._cases)

	def get_occurrences(self) -> List[Tuple]:
		return list(self._occurred)

	def extend(self, coverage: 'Coverage'):
		self._cases.update(coverage._cases)
		self._occurred.update(coverage._occurred)

	def get_percentage(self) -> float:
		if len(self._cases) == 0:
			return 0
		n = 0
		for occurred in self._occurred:
			if occurred in self._cases:
				n += 1
		return (n * 100.0) / len(self._cases)
