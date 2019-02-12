#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from enum import Enum
from collections import namedtuple

from testilias.data.result import Result, Origin

class Validness(Enum):
	VALID = 1
	INVALID = -1


class Answer:
	def __init__(self, driver, question, protocol):
		self.driver = driver
		self.question = question
		self.protocol = protocol
		self.current_score = None

	def randomize(self, context):
		raise NotImplementedError()

	def verify(self, context, after_crash=False):
		raise NotImplementedError()

	def _get_answer_dimensions(self, context, language):
		raise NotImplementedError()

	def _get_dimension_key_type(self, key):
		return None

	def add_to_result(self, result, context, language, clip_answer_score):
		key_prefix = ("question", self.question.title, "answer")

		# format of full result key:
		# ("question", title of question, "answer", key_1, ..., key_n)

		for dimension_key, dimension_value in self._get_answer_dimensions(context, language).items():
			result.add(
				Result.key(*key_prefix, dimension_key),
				dimension_value,
				self._get_dimension_key_type(dimension_key))

		score = clip_answer_score(self.current_score)

		for channel in ("xls", "pdf"):
			result.add_as_formatted_score(
				(channel, "question", self.question.title, "score"), score)

		return score

	@property
	def protocol_lines(self):
		return [(t, self.question.title, what) for t, what in self.protocol.lines]

	@property
	def protocol_files(self):
		return self.protocol.files


Choice = namedtuple('Choice', ['selector', 'label', 'checked'])
