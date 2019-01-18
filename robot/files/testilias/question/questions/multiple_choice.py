#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from decimal import *
import itertools
import json
from collections import namedtuple
from selenium.common.exceptions import NoSuchElementException

from .question import Question


MultipleChoiceItem = namedtuple('MultipleChoiceItem', ['checked_score', 'unchecked_score'])


class MultipleChoiceQuestion(Question):
	def __init__(self, driver, title, settings):
		super().__init__(title)

		self.choices = dict()

		while True:
			try:
				choice = driver.find_element_by_name("choice[answer][%d]" % len(self.choices))
			except NoSuchElementException:
				break

			points = driver.find_element_by_name("choice[points][%d]" % len(self.choices))
			points_unchecked = driver.find_element_by_name("choice[points_unchecked][%d]" % len(self.choices))

			self.choices[choice.get_attribute("value")] = MultipleChoiceItem(
				checked_score=Decimal(points.get_attribute("value")),
				unchecked_score=Decimal(points_unchecked.get_attribute("value")))

	def create_answer(self, driver, *args):
		from ..answers.multiple_choice import MultipleChoiceAnswer
		return MultipleChoiceAnswer(driver, self, *args)

	def initialize_coverage(self, coverage, context):
		if True:  # all cases
			elements = [(False, True)] * len(self.choices)
			for combination in itertools.product(*elements):
				if context.workarounds.disallow_empty_answers or any(combination):
					solution = dict()
					for checked, label in zip(combination, self.choices.keys()):
						solution[label] = 1 if checked else 0
					coverage.add_case(self, "verify", json.dumps(solution))
					coverage.add_case(self, "export", json.dumps(solution))

		else:  # only some border cases
			best_solution = dict()
			worst_solution = dict()
			for label, choice in self.choices.items():
				best_solution[label] = choice.checked_score > choice.unchecked_score
				worst_solution[label] = not best_solution[label]

			if context.workarounds.disallow_empty_answers or any(best_solution.values()):
				coverage.add_case(self, "verify", best_solution)
				coverage.add_case(self, "export", best_solution)

			if context.workarounds.disallow_empty_answers or any(worst_solution.values()):
				coverage.add_case(self, "verify", worst_solution)
				coverage.add_case(self, "export", worst_solution)

			for i in len(self.choices):
				minimal_good_solution = dict()
				for j, (label, choice) in enumerate(self.choices.items()):
					pick = choice.checked_score > choice.unchecked_score
					pick = pick if i == j else not pick
					minimal_good_solution[label] = pick
				coverage.add_case(self, "verify", minimal_good_solution)
				coverage.add_case(self, "export", minimal_good_solution)

	def add_export_coverage(self, coverage, answers, language):
		coverage.case_occurred(self, "export", json.dumps(answers))

	def get_random_answer(self, context):
		answers = dict()

		if context.workarounds.disallow_empty_answers:
			# special case here : ILIAS 5 does not recognize an "all false" MC as valid answer and
			# will not save it (the score in XLS will be None); we need to pick at least 1 checkbox.

			# check 1 item.
			answers[context.random.choice(list(self.choices.keys()))] = True

		# check the remaining items randomly.
		for label, item in self.choices.items():
			if label not in answers:
				answers[label] = context.random.random() < 0.5

		return answers, self.compute_score(answers, context)

	def readjust_scores(self, driver, random, report):
		pass

	def compute_score(self, answers, context):
		score = Decimal(0)
		for label, checked in answers.items():
			item = self.choices[label]
			if checked:
				score += item.checked_score
			else:
				score += item.unchecked_score
		return score
