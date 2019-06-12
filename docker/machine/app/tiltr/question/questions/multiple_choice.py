#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from typing import Dict
from decimal import *
import itertools
import json
from collections import namedtuple
from enum import Enum

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.select import Select
from texttable import Texttable

from .question import Question
from tiltr.driver.utils import set_element_value, wait_for_css_visible

MultipleChoiceItem = namedtuple('MultipleChoiceItem', ['checked_score', 'unchecked_score'])

class AnswerType(Enum):
	SINGLE_LINE = 0
	MULTI_LINE = 1


def _readjust_score(random, score):
	delta = Decimal(random.randint(-8, 8)) / Decimal(4)
	score += delta
	score = max(score, Decimal(0))
	return score


def _readjust_choice_item(random, scores):
	return MultipleChoiceItem(*[_readjust_score(random, scores[i]) for i in range(2)])


def _readjust_ui(context, *args):
	def ilias_5_4(driver, choices):
		for tr in driver.find_elements_by_css_selector("#form_tst_question_correction table tbody tr"):
			answer_text_element, *points_elements = list(
				tr.find_elements_by_css_selector("td"))
			assert(len(points_elements) == 2)

			item = choices[answer_text_element.text.strip()]

			for element, value in zip(points_elements, (item.checked_score, item.unchecked_score)):
				set_element_value(driver, element.find_element_by_css_selector("input"), str(value))

	def ilias_5_3(driver, choices):
		i = 0
		while True:
			try:
				choice = driver.find_element_by_name("choice[answer][%d]" % i)
			except NoSuchElementException:
				break

			item = choices[choice.get_attribute("value")]

			for name, value in (('points', item.checked_score), ('points_unchecked', item.unchecked_score)):
				points = driver.find_element_by_name("choice[%s][%d]" % (name, i))
				set_element_value(driver, points, str(value))

			i += 1

	if context.ilias_version >= (5, 4):
		ilias_5_4(*args)
	else:
		ilias_5_3(*args)


class MultipleChoiceQuestion(Question):
	@staticmethod
	def _get_ui(driver):
		choices = dict()

		answer_type = AnswerType(int(Select(driver.find_element_by_css_selector(
			"#il_prop_cont_types select")).first_selected_option.get_attribute("value")))

		while True:
			try:
				if answer_type == AnswerType.SINGLE_LINE:
					choice_element = driver.find_element_by_name("choice[answer][%d]" % len(choices))
					choice_name = choice_element.get_attribute("value")
				elif answer_type == AnswerType.MULTI_LINE:
					choice_iframe = driver.find_element_by_id("choice[answer][%d]_ifr" % len(choices))
					try:
						driver.switch_to_frame(choice_iframe)
						choice_name = driver.find_element_by_id("tinymce").text.strip()
					finally:
						driver.switch_to_default_content()
				else:
					raise RuntimeError("unsupported answer type %s" % answer_type)
			except NoSuchElementException:
				break

			values = []
			for name in ('points', 'points_unchecked'):
				points = driver.find_element_by_name("choice[%s][%d]" % (name, len(choices)))
				values.append(Decimal(points.get_attribute("value")))

			choices[choice_name] = MultipleChoiceItem(*values)

		return choices

	def __init__(self, driver, title, settings):
		super().__init__(title)
		self.choices = self._get_ui(driver)

	def get_maximum_score(self, context):
		def max_values():
			for item in self.choices.values():
				yield max(item.checked_score, item.unchecked_score)
		return sum(max_values())

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

	def readjust_scores(self, driver, actual_answers, context, report):
		choices = self.choices

		if False:
			if len(choices) != len(self.choices):
				raise IntegrityException("wrong number of choices in readjustment.")
			for key, score in self.choices.items():
				if choices[key] != score:
					raise IntegrityException("wrong choice score in readjustment.")

		table = Texttable()
		table.set_deco(Texttable.HEADER)
		table.set_cols_dtype(['t', 't', 't'])
		table.add_row(['', 'old', 'readjusted'])

		for key, score in list(choices.items()):
			new_score = _readjust_choice_item(context.random, score)
			choices[key] = new_score
			table.add_row([key, '(%f, %f)' % score, '(%f, %f)' % new_score])

		report(table)

		_readjust_ui(context, driver, choices)

		return True, list()

	def compute_score(self, answers: Dict[str, Decimal], context: 'TestContext'):
		score = Decimal(0)
		for label, checked in answers.items():
			item = self.choices[label]
			if checked:
				score += item.checked_score
			else:
				score += item.unchecked_score
		return score
