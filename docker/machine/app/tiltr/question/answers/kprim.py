#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import json
from selenium.webdriver.common.action_chains import ActionChains

from .answer import Answer, Validness


class KPrimAnswer(Answer):
	def __init__(self, driver, question, protocol):
		super().__init__(driver, question, protocol)
		assert question.__class__.__name__ == "KPrimQuestion"
		self.current_answers = None
		self.n_rows = 4

	def randomize(self, context):
		self._set_answers(*self.question.get_random_answer(context))
		return Validness()

	def _set_answers(self, answers, score):
		ui = self._parse_ui()
		chain = ActionChains(self.driver)

		assert len(answers) == self.n_rows
		for index, radios, answer in zip(range(self.n_rows), ui, answers):
			self.protocol.choose(index, answer)
			chain.click(radios[answer])

		chain.perform()

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
		names = [c.name for c in self.question.scoring.choices]
		return dict(zip(names, [int(x) for x in self.current_answers]))

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

	def _get_answer_dimensions(self, context, language):
		return self._get_binary_answers()
