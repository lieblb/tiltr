#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from decimal import *
from collections import namedtuple
import itertools
import json

from .question import Question
from tiltr.driver.utils import set_element_value


KPrimScoring = namedtuple('KPrimScoring', ['halfpoints', 'score', 'choices'])
KPrimChoice = namedtuple('KPrimChoice', ['name', 'is_correct'])


def _print_readjustments(old_scoring, new_scoring, report):
	bool_to_str = dict(((True, "true"), (False, "false")))

	report('readjusted halfpoints from %s to %s.' % (
		bool_to_str[old_scoring.halfpoints], bool_to_str[new_scoring.halfpoints]))

	report('readjusted score from %s to %s.' % (
		old_scoring.score, new_scoring.score))

	for old_choice, new_choice in zip(old_scoring.choices, new_scoring.choices):
		assert old_choice.name == new_choice.name
		report('readjusted "%s" from %s to %s.' % (
			old_choice.name,
			bool_to_str[old_choice.is_correct],
			bool_to_str[new_choice.is_correct]))

def _readjust_ui(context, driver, scoring):
	halfpoints_checkbox = driver.find_element_by_name("score_partsol_enabled")
	if halfpoints_checkbox.is_selected() != scoring.halfpoints:
		halfpoints_checkbox.click()

	set_element_value(driver, driver.find_element_by_name("points"), str(scoring.score))

	def ilias_5_4(driver, scoring):
		choices = dict((choice.name.strip(), choice) for choice in scoring.choices)

		for tr in driver.find_elements_by_css_selector("#kprim_answers table tbody tr"):
			answer_text_element, *points_elements = list(tr.find_elements_by_css_selector("td"))
			answer_text = answer_text_element.text.strip()

			choice = choices[answer_text]
			del choices[answer_text]

			radio_value = 1 if choice.is_correct else 0

			for element in points_elements:
				radio = element.find_element_by_css_selector("input")
				if int(radio.get_attribute("value")) == radio_value:
					radio.click()
					break

		if choices:
			raise InteractionException("some choices were not listed in readjustment ui")

	def ilias_5_3(driver, scoring):
		for i, choice in enumerate(scoring.choices):
			radio_value = 1 if choice.is_correct else 0

			for radio in driver.find_elements_by_name("kprim_answers[correctness][%d]" % i):
				if int(radio.get_attribute("value")) == radio_value:
					radio.click()
					break

	if context.ilias_version >= (5, 4):
		ilias_5_4(driver, scoring)
	else:
		ilias_5_3(driver, scoring)


class KPrimQuestion(Question):
	@staticmethod
	def _get_ui(driver):
		halfpoints = driver.find_element_by_name("score_partsol_enabled").is_selected()
		score = Decimal(driver.find_element_by_name("points").get_attribute("value"))
		choices = list()

		for i in range(4):
			is_correct = None

			for radio in driver.find_elements_by_name("kprim_answers[correctness][%d]" % i):
				if int(radio.get_attribute("value")) == 1:
					is_correct = radio.is_selected()

			assert is_correct is not None

			name = driver.find_element_by_name(
				"kprim_answers[answer][%d]" % i).get_attribute("value")

			choices.append(KPrimChoice(name, is_correct))

		return KPrimScoring(
			halfpoints=halfpoints, score=score, choices=choices)

	def __init__(self, driver, title, settings):
		super().__init__(title)
		self.scoring = KPrimQuestion._get_ui(driver)

	def get_maximum_score(self, context):
		return self.scoring.score

	def create_answer(self, driver, *args):
		from ..answers.kprim import KPrimAnswer
		return KPrimAnswer(driver, self, *args)

	def initialize_coverage(self, coverage, context):
		elements = [(False, True)] * len(self.scoring.choices)
		for combination in itertools.product(*elements):
			if context.workarounds.disallow_empty_answers or any(combination):
				solution = dict()
				for checked, choice in zip(combination, self.scoring.choices):
					solution[choice.name] = 1 if checked else 0
				coverage.add_case(self, "verify", json.dumps(solution))
				coverage.add_case(self, "export", json.dumps(solution))

	def add_export_coverage(self, coverage, answers, language):
		coverage.case_occurred(self, "export", json.dumps(answers))

	def compute_score(self, answers, context):
		name_to_index = dict()
		for i, choice in enumerate(self.scoring.choices):
			name_to_index[choice.name] = i

		indexed_answers = dict()
		for name, value in answers.items():
			indexed_answers[name_to_index[name]] = value

		return self.compute_score_by_indices(indexed_answers)

	def compute_score_by_indices(self, answers):
		if not self.scoring.halfpoints:
			correct = []
			for i in range(4):
				correct.append(answers[i] == self.scoring.choices[i].is_correct)
			return self.scoring.score if all(correct) else Decimal(0)
		else:
			n_correct = 0
			for i in range(4):
				if answers[i] == self.scoring.choices[i].is_correct:
					n_correct += 1
			if n_correct == 4:
				return self.scoring.score
			elif n_correct == 3:
				return self.scoring.score / Decimal(2)
			else:
				return Decimal(0)

	def get_random_answer(self, context):
		answers = [context.random.random() < 0.5 for _ in range(4)]
		return answers, self.compute_score_by_indices(answers)

	def readjust_scores(self, driver, actual_answers, context, report):
		random = context.random

		def random_flip(f):
			if random.randint(0, 3) == 0:  # flip?
				return not f
			else:
				return f

		def new_choice(choice):
			return KPrimChoice(
				choice.name, random_flip(choice.is_correct))

		new_choices = list(map(new_choice, self.scoring.choices))

		old_scoring = self.scoring

		self.scoring = KPrimScoring(
			halfpoints=random_flip(self.scoring.halfpoints),
			score=Decimal(random.randint(1, 8)) / Decimal(4),
			choices=new_choices)

		_readjust_ui(context, driver, self.scoring)

		_print_readjustments(old_scoring, self.scoring, report)

		return True, list()
