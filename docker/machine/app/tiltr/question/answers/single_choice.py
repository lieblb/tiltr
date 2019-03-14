#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from .answer import Answer, Validness, Choice


class SingleChoiceAnswer(Answer):
	def __init__(self, driver, question, protocol):
		super().__init__(driver, question, protocol)
		assert question.__class__.__name__ == "SingleChoiceQuestion"
		self.current_answer = None

	def randomize(self, context):
		self._set_answer(*self.question.get_random_answer(context))
		return Validness.VALID

	def _set_answer(self, answer, score):
		answer_found = False
		for choice in self._parse_ui():
			self.protocol.choose(choice.label, choice.label == answer)
			if choice.label == answer:
				self.driver.find_element_by_css_selector(choice.selector).click()
				self.current_answer = answer
				self.current_score = score
				self.protocol.add("on _set_answer: current_answer == '%s'" % answer)
				answer_found = True
				break
		if not answer_found:
			raise Exception("could not find answer '%s'" % answer)

	def _parse_ui(self):
		choices = []
		for answer in self.driver.find_elements_by_css_selector('.ilc_question_SingleChoice .ilc_qanswer_Answer'):
			radio = answer.find_element_by_css_selector('input[type="radio"]')
			label = answer.find_element_by_css_selector('label[for="%s"]' % radio.get_attribute("id"))
			choices.append(Choice(
				selector="#" + radio.get_attribute("id"),
				label=label.text.strip(),
				checked=radio.is_selected()))
		return choices

	def verify(self, context, after_crash=False):
		self.protocol.add("on verify: current_answer == '%s'" % self.current_answer)
		for c in self._parse_ui():
			expected = (c.label == self.current_answer)
			self.protocol.verify(c.label, expected, c.checked, after_crash=after_crash)
		context.coverage.case_occurred(self.question, "verify", self.current_answer)

	def _get_answer_dimensions(self, context, language):
		return dict(
			(choice, 1 if choice == self.current_answer else 0)
			for choice in self.question.choices.keys())
