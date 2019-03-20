#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from decimal import *
from enum import Enum
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.select import Select

from .question import Question


class MatchingMultiplicity(Enum):
	ONE_TO_ONE = 1
	MANY_TO_MANY = 2


class MatchingQuestion(Question):
	@staticmethod
	def _get_ui_multiplicity(driver):
		for radio in driver.find_elements_by_name('matching_mode'):
			if radio.is_selected():
				value = radio.get_attribute('value')
				if value == '1:1':
					return MatchingMultiplicity.ONE_TO_ONE
				elif value == 'n:n':
					return MatchingMultiplicity.MANY_TO_MANY
				else:
					raise RuntimeError('unknown matching mode %s' % value)

		raise RuntimeError('no matching mode set in gui')

	@staticmethod
	def _get_ui_pairs(driver):
		pairs = dict()

		while True:
			i = len(pairs)

			try:
				k = []

				for s in ('definition', 'term'):
					k.append(Select(driver.find_element_by_name(
						'pairs[%s][%d]' % (s, i))).first_selected_option.get_attribute('value'))

				pairs[tuple(k)] = Decimal(driver.find_element_by_name('pairs[points][%d]' % i).get_attribute('value'))
			except NoSuchElementException:
				break

		return pairs

	@staticmethod
	def _get_ui_items(driver, what):
		items = dict()

		while True:
			i = len(items)
			q = dict()

			try:
				for s in ('identifier', 'answer'):
					q[s] = driver.find_element_by_name(
						'%s[%s][%d]' % (what, s, i)).get_attribute('value')
			except NoSuchElementException:
				break

			items[q['identifier']] = q['answer']

		return items

	def __init__(self, driver, title, settings):
		super().__init__(title)

		self.multiplicity = self._get_ui_multiplicity(driver)
		self.definitions = self._get_ui_items(driver, 'definitions')
		self.terms = self._get_ui_items(driver, 'terms')
		self.pairs = self._get_ui_pairs(driver)

	def get_maximum_score(self):
		return sum(self.pairs.values())

	def create_answer(self, driver, *args):
		from ..answers.matching import MatchingAnswer
		return MatchingAnswer(driver, self, *args)

	def get_definition_label(self, definition_id):
		return self.definitions[definition_id]

	def get_term_label(self, term_id):
		return self.terms[term_id]

	def get_term_labels(self, term_ids):
		return [self.terms[t] for t in term_ids]

	def initialize_coverage(self, coverage, context):
		pass

	def add_export_coverage(self, coverage, answers, language):
		pass

	def get_random_answer(self, context):
		min_n = 1 if context.workarounds.disallow_empty_answers else 0
		n = context.random.randint(min_n, len(self.definitions))

		definitions = context.random.sample(self.definitions.keys(), n)
		if self.multiplicity == MatchingMultiplicity.ONE_TO_ONE:
			terms = context.random.sample(self.terms.keys(), n)
			answers = dict((d, set([t])) for d, t in zip(definitions, terms))
		elif self.multiplicity == MatchingMultiplicity.MANY_TO_MANY:
			answers = dict()
			force_1 = None
			if context.workarounds.disallow_empty_answers:
				force_1 = context.random.randint(0, len(definitions))
			for i, definition_id in enumerate(definitions):
				min_m = 1 if force_1 == i else 0
				m = context.random.randint(min_m, len(self.terms))
				if m > 0:
					answers[definition_id] = set(
						context.random.sample(self.terms.keys(), m))
		else:
			raise NotImplementedError("illegal matching multiplicity")

		return answers, self.compute_score(answers, context)

	def readjust_scores(self, driver, context, report):
		return False

	def compute_score(self, answers, context):
		score = Decimal(0)
		for definition_id, term_ids in answers.items():
			for term_id in term_ids:
				k = (definition_id, term_id)
				if k in self.pairs:
					score += self.pairs.get(k)
		return score
