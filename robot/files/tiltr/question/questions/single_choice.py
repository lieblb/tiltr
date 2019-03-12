#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from decimal import *
from selenium.common.exceptions import NoSuchElementException

from .question import Question
from tiltr.data.exceptions import *
from tiltr.driver.utils import set_element_value


def readjust_score(random, score):
	delta = Decimal(random.randint(-8, 8)) / Decimal(4)
	score += delta
	score = max(score, Decimal(0))
	return score


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

	@staticmethod
	def _set_ui(driver, choices):
		i = 0
		while True:
			try:
				choice = driver.find_element_by_name("choice[answer][%d]" % i)
			except NoSuchElementException:
				break
			points = driver.find_element_by_name("choice[points][%d]" % i)
			set_element_value(driver, points, str(choices[choice.get_attribute("value")]))
			i += 1

	def __init__(self, driver, title, settings):
		super().__init__(title)

		self.choices = self._get_ui(driver)

	def create_answer(self, driver, *args):
		from ..answers.single_choice import SingleChoiceAnswer
		return SingleChoiceAnswer(driver, self, *args)

	def initialize_coverage(self, coverage, context):
		for choice in self.choices.keys():
			coverage.add_case(self, "verify", choice)
			coverage.add_case(self, "export", choice)

	def add_export_coverage(self, coverage, answers, language):
		for choice, checked in answers.items():
			if checked != 0:
				coverage.case_occurred(self, "export", str(choice))
				break

	def get_random_answer(self, context):
		choice = context.random.choice(list(self.choices.keys()))
		return choice, self.choices[choice]

	def readjust_scores(self, driver, random, report):
		report('### READJUSTING QUESTION "%s"' % self.title.upper())
		report('')

		choices = self._get_ui(driver)

		if len(choices) != len(self.choices):
			raise IntegrityException("wrong number of choices in readjustment.")
		for key, score in self.choices.items():
			if choices[key] != score:
				raise IntegrityException("wrong choice score in readjustment.")

		for key, score in list(choices.items()):
			new_score = readjust_score(random, score)
			choices[key] = new_score
			report('readjusted score for "%s / %s" from %s to %s.' % (self.title, key, score, new_score))

		self._set_ui(driver, choices)
		self.choices = choices

		return True

	def compute_score(self, answers, context):
		score = Decimal(0)
		for label, checked in answers.items():
			if checked:
				score += self.choices[label]
		return score
