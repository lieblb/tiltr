#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import json

from .answer import Answer, Validness


class KPrimAnswer(Answer):
	def __init__(self, driver, question, protocol):
		assert question.__class__.__name__ == "KPrimQuestion"
		self.driver = driver
		self.question = question
		self.current_answers = None
		self.current_score = None
		self.protocol = protocol
		self.n_rows = 4

	def randomize(self, context):
		self._set_answers(*self.question.get_random_answer(context))
		return Validness.VALID

	def _set_answers(self, answers, score):
		ui = self._parse_ui()

		assert len(answers) == self.n_rows
		for index, radios, answer in zip(range(self.n_rows), ui, answers):
			self.protocol.choose(index, answer)
			radios[answer].click()

		self.current_answers = answers
		self.current_score = score

	def _parse_ui(self):
		root = self.driver.find_element_by_css_selector(".ilc_question_KprimChoice")
		ui = []
		for i in range(self.n_rows):
			radios = dict()
			for radio in root.find_elements_by_name("kprim_choice_result_%d" % i):
				radios[bool(int(radio.get_attribute("value")))] = radio
			ui.append(radios)
		return ui

	def _get_binary_answers(self):
		return dict(zip(self.question.names, [int(x) for x in self.current_answers]))

	def verify(self, context, after_crash=False):
		ui = self._parse_ui()

		for i in range(self.n_rows):
			self.protocol.verify(
				str(i),
				self.current_answers[i],
				ui[i][True].is_selected(),
				after_crash=after_crash)

		context.coverage.case_occurred(
			self.question, "verify", json.dumps(self._get_binary_answers()))

	def to_dict(self, context, language):
		return dict(
			title=self.question.title,
			answers=self._get_binary_answers(),
			protocol=self.protocol.to_dict())
