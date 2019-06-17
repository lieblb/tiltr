#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from typing import List, Dict

import json

from selenium.webdriver.common.action_chains import ActionChains
from decimal import *

from .answer import Answer, Validness, Choice


class MultipleChoiceAnswer(Answer):
	def __init__(self, driver, question, protocol):
		super().__init__(driver, question, protocol)
		assert question.__class__.__name__ == "MultipleChoiceQuestion"
		self.current_answers = None

	def randomize(self, context) -> Validness:
		self._set_answers(*self.question.get_random_answer(context))
		return Validness()

	def _set_answers(self, answers: Dict[str, bool], score: Decimal):
		chain = ActionChains(self.driver)

		for choice in self._parse_ui():
			checkbox = self.driver.find_element_by_css_selector(choice.selector)
			self.protocol.choose(choice.label, answers[choice.label])
			if answers[choice.label] != checkbox.is_selected():
				chain.click(checkbox)

		chain.perform()

		self.current_answers = answers
		self.current_score = score

	def _parse_ui(self) -> List[Choice]:
		choices = []
		for answer in self.driver.find_elements_by_css_selector('.ilc_question_MultipleChoice .ilc_qanswer_Answer'):
			checkbox = answer.find_element_by_css_selector('input[type="checkbox"]')
			label = answer.find_element_by_css_selector('label[for="%s"]' % checkbox.get_attribute("id"))
			choices.append(Choice(
				selector="#" + checkbox.get_attribute("id"),
				label=label.text.strip(),
				checked=checkbox.is_selected()))
		return choices

	def _get_binary_answers(self) -> Dict[str, int]:
		answers = dict()
		for choice in self.question.choices.keys():
			if self.current_answers[choice]:
				answers[choice] = 1
			else:
				answers[choice] = 0
		return answers

	def verify(self, context: 'TestContext', after_crash: bool = False):
		for c in self._parse_ui():
			self.protocol.verify(c.label, self.current_answers[c.label], c.checked, after_crash=after_crash)

		context.coverage.case_occurred(
			self.question, "verify", json.dumps(self._get_binary_answers()))

	def _get_answer_dimensions(self, context: 'TestContext', language: str) -> Dict[str, int]:
		return self._get_binary_answers()
