#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from decimal import *
from enum import Enum
import itertools
from collections import defaultdict

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.select import Select
from texttable import Texttable

from tiltr.driver.utils import set_element_value
from .question import Question


def _readjust_score(random, score, enforce_positive):
	if enforce_positive:
		return Decimal(random.randint(1, 8)) / Decimal(4)
	else:
		delta = Decimal(random.randint(-8, 8)) / Decimal(4)
		return score + delta


def _get_maximum_score(scores):
	if scores:
		return sum(max(s, 0) for s in scores.values())
	else:
		return Decimal(0)


class MatchingMultiplicity(Enum):
	ONE_TO_ONE = 1
	MANY_TO_MANY = 2


class MatchingQuestion(Question):
	@staticmethod
	def _ui_get_multiplicity(driver):
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
	def _ui_get_pairs(driver):
		css = (
			('.matchingpairwizard tbody td select[name^="pairs[definition]"]', 'option[selected]'),
			('.matchingpairwizard tbody td select[name^="pairs[term]"]', 'option[selected]'),
			('.matchingpairwizard tbody td input[name^="pairs[points]', '')
		 )

		definitions, terms, points = driver.execute_script("""
			return arguments[0].map(function(css) {
				return $(css[0]).map(function(i, e) {
					if (!e.getAttribute('name').endsWith('[' + i.toString() + ']')) {
						throw 'item is out of order';
					}
					return $(this, css[1])[0].value;
				});
			});
		""", css)

		return list(zip(zip(definitions, terms), points))

	@staticmethod
	def _ui_get_pair_keys(driver):
		return list(map(lambda x: x[0], MatchingQuestion._ui_get_pairs(driver)))

	@staticmethod
	def _ui_get_pair_indices(driver):
		pairs = dict()
		for i, (definition, term) in enumerate(MatchingQuestion._ui_get_pair_keys(driver)):
			pairs[(definition, term)] = i
		return pairs

	@staticmethod
	def _ui_get_scores(driver):
		scores = dict()
		for (definition, term), score in MatchingQuestion._ui_get_pairs(driver):
			scores[(definition, term)] = Decimal(score)
		return scores

	@staticmethod
	def _ui_add_pairs(driver, keys):
		index = len(MatchingQuestion._ui_get_pair_indices(driver)) - 1

		for definition, term in keys:
			driver.find_element_by_id("add_pairs[%d]" % index).click()
			index += 1

			Select(driver.find_element_by_css_selector(
				'select[name="pairs[definition][%d]"]' % index)).select_by_value(definition)

			Select(driver.find_element_by_css_selector(
				'select[name="pairs[term][%d]"]' % index)).select_by_value(term)

	@staticmethod
	def _ui_remove_pairs(driver, keys):
		# the number ids of pairs change with each remove, so we need to refresh
		# on each iteration.
		for key in keys:
			pairs = MatchingQuestion._ui_get_pair_indices(driver)
			index_to_remove = pairs[key]
			driver.find_element_by_id("remove_pairs[%d]" % index_to_remove).click()

	@staticmethod
	def _ui_update_scores(driver, scores):
		current_keys = set(MatchingQuestion._ui_get_pair_keys(driver))

		added = set(scores.keys()) - current_keys
		MatchingQuestion._ui_add_pairs(driver, added)

		removed = current_keys - set(scores.keys())
		MatchingQuestion._ui_remove_pairs(driver, removed)

		current_pairs = MatchingQuestion._ui_get_pair_indices(driver)
		assert set(current_pairs.keys()) == set(scores.keys())

		for key, score in scores.items():
			points_element = driver.find_element_by_css_selector(
				'input[name="pairs[points][%d]"]' % current_pairs[key])
			set_element_value(driver, points_element, str(score))

	@staticmethod
	def _ui_get_items(driver, what):
		def gather():
			i = 0

			while True:
				values = list()

				try:
					for s in ('identifier', 'answer'):
						values.append(driver.find_element_by_name(
							'%s[%s][%d]' % (what, s, i)).get_attribute('value'))
				except NoSuchElementException:
					break

				yield tuple(values)

				i += 1

		return dict(gather())

	def __init__(self, driver, title, settings):
		super().__init__(title)

		self.multiplicity = self._ui_get_multiplicity(driver)
		self.definitions = self._ui_get_items(driver, 'definitions')
		self.terms = self._ui_get_items(driver, 'terms')
		self.scores = self._ui_get_scores(driver)

	def get_maximum_score(self):
		return _get_maximum_score(self.scores)

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
		if context.workarounds.dont_readjust_matching:
			return False, list()

		new_scores = dict()

		all_pairs = set((d, t) for d, t in itertools.product(
			self.definitions.keys(), self.terms.keys()))

		unused_pairs = all_pairs - set(self.scores.keys())

		old_scores = list(self.scores.items())
		context.random.shuffle(old_scores)

		changes = dict()
		removed = set()

		actions = ['keep', 'adjust']
		if not context.workarounds.no_remove_on_readjust_matching:
			actions.append('remove')

		for (definition, term), score in old_scores:
			action = context.random.choice(actions)

			if action == 'keep':
				# keep pair and score as is
				new_scores[(definition, term)] = score
				changes[(definition, term)] = (score, score)
			elif action == 'adjust':
				# adjust score of existing pair
				enforce_positive = _get_maximum_score(new_scores) <= Decimal(0)
				new_scores[(definition, term)] = _readjust_score(
					context.random, score, enforce_positive)
				changes[(definition, term)] = (
					score,
					new_scores[(definition, term)])
			elif action == 'remove':
				# remove pair
				changes[(definition, term)] = (score, 'n/a')
				removed.add((definition, term))
			else:
				raise RuntimeError("illegal readjust action %s" % action)

		n_to_add = context.random.randint(
			0, min(len(unused_pairs), max(2, len(self.scores))))
		if len(new_scores) < 1:
			n_to_add = max(n_to_add, 1)
		if n_to_add > len(unused_pairs):
			unused_pairs = all_pairs - set(new_scores.keys())

		for _ in range(n_to_add):
			new_definition, new_term = context.random.choice(list(unused_pairs))
			unused_pairs.remove((new_definition, new_term))
			enforce_positive = _get_maximum_score(new_scores) <= Decimal(0)
			new_scores[(new_definition, new_term)] = _readjust_score(
				context.random, Decimal(0), enforce_positive)

			if (new_definition, new_term) in changes:
				removed.remove((definition, term))
				changes[(new_definition, new_term)] = (
					changes[(new_definition, new_term)][0],
					new_scores[(new_definition, new_term)])
			else:
				changes[(new_definition, new_term)] = (
					"n/a",
					new_scores[(new_definition, new_term)])

		table = Texttable()
		table.set_deco(Texttable.HEADER)
		table.set_cols_dtype(['t', 'a', 'a'])
		table.add_row(['', 'old', 'readjusted'])
		for (definition, term), (old_score, new_score) in changes.items():
			key_as_str = '("%s", "%s")' % (
				self.definitions[definition], self.terms[term])
			table.add_row([key_as_str, old_score, new_score])
		report(table)

		MatchingQuestion._ui_update_scores(driver, new_scores)
		self.scores = new_scores

		removed_keys = [(self.definitions[d], self.terms[t]) for d, t in removed]
		return True, removed_keys

	def compute_score(self, answers, context):
		score = Decimal(0)
		for definition_id, term_ids in answers.items():
			for term_id in term_ids:
				k = (definition_id, term_id)
				if k in self.scores:
					score += self.scores.get(k)
		return score

	def compute_score_from_result(self, result, context):
		definition_ids = dict((label, i) for i, label in self.definitions.items())
		term_ids = dict((label, i) for i, label in self.terms.items())

		answers = defaultdict(set)
		for key, value in result.properties.items():
			if key[0] == "question" and key[1] == self.title and key[2] == "answer":
				definition_label = key[3]
				term_label = key[4]
				answers[definition_ids[definition_label]].add(term_ids[term_label])

		return self.compute_score(answers, context)

	def parse_xls_row(self, sheet, row):
		key = sheet.cell(row=row, column=1).value
		if key is None:
			return None

		# matching questions are stored as (key, "matches", value).
		value = sheet.cell(row=row, column=3).value

		return (key, value), True
