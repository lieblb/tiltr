#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from .answer import Answer, Validness

import json

from selenium.webdriver.common.action_chains import ActionChains
from PIL import Image
from decimal import *


class CodeAnswer(Answer):
	def __init__(self, driver, question, protocol):
		super().__init__(driver, question, protocol)
		assert question.__class__.__name__ == "CodeQuestion"
		self.current_answer = None

	def randomize(self, context):
		self._set_answer(*self.question.get_random_answer(context), context)
		return Validness.VALID

	def _set_answer(self, answer, score, context):
		answer = context.strip_whitespace(answer)

		self.driver.execute_script(
			"$('textarea[data-blocktype=2]').next()[0].CodeMirror.setValue(arguments[0])", answer)

		self.current_answer = answer
		self.current_score = score

	def verify(self, context, after_crash=False):
		actual_answer = self.driver.execute_script(
			"return $('textarea[data-blocktype=2]').next()[0].CodeMirror.getValue()")
		self.protocol.verify('code', self.current_answer, actual_answer, after_crash=after_crash)

	def _get_dimension_key_type(self, key):
		if key == 'Ihr Quelltext:':
			return 'json'
		else:
			return None

	def _get_answer_dimensions(self, context, language):
		blocks = dict()
		# for some reason, \n ends up as \r\n in XLS. that's ok.
		blocks['1'] = self.current_answer.replace('\n', '\r\n')

		answers = dict()
		answers['Ihr Quelltext:'] = json.dumps(blocks)  # e.g. {"1":"x = range(10)\r\n"}
		answers['-qpl_qst_codeqst_label_points-'] = ''

		return answers
