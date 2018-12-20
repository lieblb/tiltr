#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from decimal import *
import itertools
import json

from .question import Question


class KPrimQuestion(Question):
	def __init__(self, driver, title, settings):
		self.title = title

		self.halfpoints = driver.find_element_by_name("score_partsol_enabled").is_selected()
		self.score = Decimal(driver.find_element_by_name("points").get_attribute("value"))
		self.solution = []
		self.names = []

		for i in range(4):
			is_right = None

			for radio in driver.find_elements_by_name("kprim_answers[correctness][%d]" % i):
				if int(radio.get_attribute("value")) == 1:
					is_right = radio.is_selected()

			assert is_right is not None
			self.solution.append(is_right)

			self.names.append(driver.find_element_by_name(
				"kprim_answers[answer][%d]" % i).get_attribute("value"))

	def create_answer(self, driver, *args):
		from ..answers.kprim import KPrimAnswer
		return KPrimAnswer(driver, self, *args)

	def initialize_coverage(self, coverage, context):
		elements = [(False, True)] * len(self.names)
		for combination in itertools.product(*elements):
			if context.workarounds.disallow_empty_answers or any(combination):
				solution = dict()
				for checked, label in zip(combination, self.names):
					solution[label] = 1 if checked else 0
				coverage.add_case(self, "verify", json.dumps(solution))
				coverage.add_case(self, "export", json.dumps(solution))

	def add_export_coverage(self, coverage, answers, language):
		coverage.case_occurred(self, "export", json.dumps(answers))

	def compute_score(self, answers, context):
		indexed_answers = dict()
		for name, value in answers.items():
			indexed_answers[self.names.index(name)] = value
		return self.compute_score_by_indices(indexed_answers)

	def compute_score_by_indices(self, answers):
		if not self.halfpoints:
			s = self.score / Decimal(4)
			score = Decimal(0)
			for i in range(4):
				if answers[i] == self.solution[i]:
					score += s
			return score
		else:
			n_correct = 0
			for i in range(4):
				if answers[i] == self.solution[i]:
					n_correct += 1
			if n_correct == 4:
				return self.score
			elif n_correct == 3:
				return self.score / Decimal(2)
			else:
				return Decimal(0)

	def get_random_answer(self, context):
		answers = [context.random.random() < 0.5 for _ in range(4)]
		return answers, self.compute_score_by_indices(answers)

	def readjust_scores(self, driver, random, report):
		pass
