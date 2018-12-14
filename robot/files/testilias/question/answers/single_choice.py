#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from .answer import Answer, Validness, Choice


class SingleChoiceAnswer(Answer):
	def __init__(self, driver, question, protocol):
		assert question.__class__.__name__ == "SingleChoiceQuestion"
		self.driver = driver
		self.question = question
		self.current_answer = None
		self.current_score = None
		self.protocol = protocol

	def randomize(self, context):
		self._set_answer(*self.question.get_random_answer(context))
		return Validness.VALID

	def _set_answer(self, answer, score):
		for choice in self._parse_ui():
			self.protocol.choose(choice.label, choice.label == answer)
			if choice.label == answer:
				self.driver.find_element_by_css_selector(choice.selector).click()
		self.current_answer = answer
		self.current_score = score

	def _parse_ui(self):
		choices = []
		for answer in self.driver.find_elements_by_css_selector('.ilc_question_SingleChoice .ilc_qanswer_Answer'):
			radio = answer.find_element_by_css_selector('input[type="radio"]')
			label = answer.find_element_by_css_selector('label[for="%s"]' % radio.get_attribute("id"))
			c = Choice(
				selector="#" + radio.get_attribute("id"),
				label=label.text.strip(),
				checked=radio.is_selected())
			choices.append(c)
		return choices

	def verify(self, context, after_crash=False):
		for c in self._parse_ui():
			if c.label == self.current_answer:
				expected = True
			else:
				expected = False
			self.protocol.verify(c.label, expected, c.checked, after_crash=after_crash)
		context.coverage.case_occurred(self.question, "verify", self.current_answer)

	def to_dict(self, context, language):
		answers = dict()
		for choice in self.question.choices.keys():
			if choice == self.current_answer:
				answers[choice] = 1
			else:
				answers[choice] = 0
		return dict(
			title=self.question.title,
			answers=answers,
			protocol=self.protocol.to_dict())
