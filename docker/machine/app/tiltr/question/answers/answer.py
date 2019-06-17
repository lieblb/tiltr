#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from typing import Callable, List
from decimal import *

import selenium

from collections import namedtuple

from tiltr.data.result import Result, Origin
from tiltr.question.protocol import AnswerProtocol


class Validness:
	invalid_answers: List

	def __init__(self, invalid_answers=None):
		self.invalid_answers = list(invalid_answers) if invalid_answers else None

	def is_good(self) -> bool:
		return not self.invalid_answers


class Answer:
	driver: selenium.webdriver.Remote
	question: 'Question'
	protocol: AnswerProtocol
	current_score: Decimal

	def __init__(self, driver: selenium.webdriver.Remote, question: 'Question', protocol: AnswerProtocol):
		self.driver = driver
		self.question = question
		self.protocol = protocol
		self.current_score = None

	def randomize(self, context: 'TestContext') -> Validness:
		raise NotImplementedError()

	def verify(self, context: 'TestContext', after_crash: bool = False):
		raise NotImplementedError()

	def _get_answer_dimensions(self, context: 'TestContext', language: str):
		raise NotImplementedError()

	def _get_dimension_key_type(self, key) -> str:
		return None

	def add_to_result(
		self, result, context: 'TestContext', language: str,
		clip_answer_score: Callable[[Decimal], Decimal]) -> Decimal:

		key_prefix = ("question", self.question.title, "answer")

		# format of full result key:
		# ("question", title of question, "answer", key_1, ..., key_n)

		for dimension_key, dimension_value in self._get_answer_dimensions(context, language).items():
			result.add(
				Result.key(*key_prefix, dimension_key),
				dimension_value,
				self._get_dimension_key_type(dimension_key))

		score = clip_answer_score(self.current_score)

		for key in Result.reached_score_keys(self.question.title):
			result.add(key, Result.format_score(score))

		for key in Result.maximum_score_keys(self.question.title):
			result.add(key, Result.format_score(self.question.get_maximum_score(context)))

		return score

	@property
	def protocol_lines(self):
		return [(t, self.question.title, what) for t, what in self.protocol.lines]

	@property
	def protocol_files(self):
		return self.protocol.files


Choice = namedtuple('Choice', ['selector', 'label', 'checked'])
