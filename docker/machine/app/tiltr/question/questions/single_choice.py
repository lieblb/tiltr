#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from typing import Dict
from decimal import *

from selenium.common.exceptions import NoSuchElementException
from texttable import Texttable

from .question import Question
from tiltr.data.exceptions import *
from tiltr.data.settings import Settings
from tiltr.driver.utils import set_element_value


def _readjust_score(random, score: Decimal):
	delta = Decimal(random.randint(-8, 8)) / Decimal(4)
	score += delta
	score = max(score, Decimal(0))
	return score


def _readjust_ui(context: 'TestContext', *args):
	def ilias_5_4(driver, choices):
		for tr in driver.find_elements_by_css_selector("#form_tst_question_correction table tbody tr"):
			answer_text_element, points_element = list(tr.find_elements_by_css_selector("td"))

			set_element_value(
				driver,
				points_element.find_element_by_css_selector("input"),
				str(choices[answer_text_element.text.strip()]))

	def ilias_5_3(driver, choices):
		i = 0
		while True:
			try:
				choice = driver.find_element_by_name("choice[answer][%d]" % i)
			except NoSuchElementException:
				break
			points = driver.find_element_by_name("choice[points][%d]" % i)
			set_element_value(driver, points, str(choices[choice.get_attribute("value")]))
			i += 1

	if context.ilias_version >= (5, 4):
		ilias_5_4(*args)
	else:
		ilias_5_3(*args)


class SingleChoiceQuestion(Question):
	@staticmethod
	def _get_ui(driver):
		choices = dict()

		while True:
			try:
				choice = driver.find_element_by_name("choice[answer][%d]" % len(choices))
			except NoSuchElementException:
				break
			points = driver.find_element_by_name("choice[points][%d]" % len(choices))
			choices[choice.get_attribute("value")] = Decimal(points.get_attribute("value"))

		return choices

	def __init__(self, driver, title: str, settings: Settings):
		super().__init__(title)
		self.choices = self._get_ui(driver)

	def get_maximum_score(self, context: 'TestContext'):
		return max(self.choices.values())

	def create_answer(self, driver, *args):
		from ..answers.single_choice import SingleChoiceAnswer
		return SingleChoiceAnswer(driver, self, *args)

	def initialize_coverage(self, coverage, context: 'TestContext'):
		for choice in self.choices.keys():
			coverage.add_case(self, "verify", choice)
			coverage.add_case(self, "export", choice)

	def add_export_coverage(self, coverage, answers, language: str):
		for choice, checked in answers.items():
			if checked != 0:
				coverage.case_occurred(self, "export", str(choice))
				break

	def get_random_answer(self, context: 'TestContext'):
		choice = context.random.choice(list(self.choices.keys()))
		return choice, self.choices[choice]

	def readjust_scores(self, driver, actual_answers, context: 'TestContext', report):
		choices = self.choices

		if False:
			if len(choices) != len(self.choices):
				raise IntegrityException("wrong number of choices in readjustment.")
			for key, score in self.choices.items():
				if choices[key] != score:
					raise IntegrityException("wrong choice score in readjustment.")

		table = Texttable()
		table.set_deco(Texttable.HEADER)
		table.set_cols_dtype(['t', 'a', 'a'])
		table.add_row(['', 'old', 'readjusted'])

		for key, score in list(choices.items()):
			new_score = _readjust_score(context.random, score)
			choices[key] = new_score
			table.add_row([key, score, new_score])

		report(table)

		_readjust_ui(context, driver, choices)

		return True, list()

	def compute_score(self, answers: Dict[str, Decimal], context: 'TestContext'):
		score = Decimal(0)
		for label, checked in answers.items():
			if checked:
				score += self.choices[label]
		return score
