#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from selenium.webdriver.common.action_chains import ActionChains

from .answer import Answer, Validness
from testilias.data.exceptions import *


def _check_label(kind, element, stored):
	displayed = element.find_element_by_css_selector('.ilc_qanswer_Answer').text
	if displayed.strip() != stored:
		raise IntegrityException('displayed %s label "%s" != "%s"' % (kind, displayed, stored))


def _scrolling_drag_and_drop(chain, source, target):
	pass


class MatchingAnswer(Answer):
	def __init__(self, driver, question, protocol):
		super().__init__(driver, question, protocol)
		assert question.__class__.__name__ == "MatchingQuestion"
		self.current_answer = None
		self.debug = False

	def randomize(self, context):
		self._set_answer(*self.question.get_random_answer(context))
		return Validness.VALID

	def _set_answer(self, answer, score):
		self._reset_answer_ui()

		root = self.driver.find_element_by_css_selector('.ilc_question_MatchingQuestion')
		source_area = root.find_element_by_css_selector('#sourceArea')
		target_area = root.find_element_by_css_selector('#targetArea')

		for definition_id, term_ids in answer.items():
			target_element = target_area.find_element_by_css_selector(
				'.droparea[data-type="definition"][data-id="%s"]' % definition_id)

			_check_label(
				'definition',
				target_element.find_element_by_css_selector('.ilMatchingQuestionDefinition'),
				self.question.get_definition_label(definition_id))

			term_ids = set(list(term_ids))  # copy

			n_retries = 0
			while term_ids:
				# sometimes drag and drop does not work on the first try. retry until all terms
				# have been dragged and dropped onto their target.

				n_retries += 1
				if n_retries > 10:
					raise InteractionException("drag and drop for matching question failed")

				for term_id in term_ids:
					if self.debug:
						print("set_answer: %s [%s] -> %s [%s]" % (
							self.question.get_term_label(term_id), term_id,
							self.question.get_definition_label(definition_id), definition_id))

					source_element = source_area.find_element_by_css_selector(
						'.draggable[data-type="term"][data-id="%s"]' % term_id)

					_check_label(
						'term',
						source_element,
						self.question.get_term_label(term_id))

					chain = ActionChains(self.driver)
					chain.move_to_element(source_element)
					chain.drag_and_drop(source_element, target_element)
					chain.perform()

					if self.debug:
						print(
							"drag_and_drop:",
							source_element.get_attribute('id'),
							target_element.get_attribute('id'))

				for term in target_element.find_elements_by_css_selector('.draggable[data-type="term"]'):
					term_ids.remove(term.get_attribute('data-id'))


		if self.debug:
			print("verify...")
			for definition_id, term_ids in self._parse_ui().items():
				print(definition_id, term_ids)
			print("verify done...")

		for definition_id, term_ids in answer.items():
			self.protocol.choose(
				self.question.get_definition_label(definition_id),
				self.question.get_term_labels(term_ids))

		self.current_answer = answer
		self.current_score = score

	def _reset_answer_ui(self):
		root = self.driver.find_element_by_css_selector('.ilc_question_MatchingQuestion')
		source_area = root.find_element_by_css_selector('#sourceArea')
		target_area = root.find_element_by_css_selector('#targetArea')

		for definition in target_area.find_elements_by_css_selector('.droparea[data-type="definition"]'):
			for term in definition.find_elements_by_css_selector('.draggable[data-type="term"]'):
				term_target = source_area.find_element_by_css_selector(
					'.draggable[data-type="term"][data-id="%s"]' % term.get_attribute('data-id'))

				chain = ActionChains(self.driver)
				chain.move_to_element(term)
				chain.drag_and_drop(term, term_target)
				chain.pause(1)
				chain.perform()


	def _parse_ui(self):
		answers = dict()

		root = self.driver.find_element_by_css_selector('.ilc_question_MatchingQuestion')
		target_area = root.find_element_by_css_selector('#targetArea')

		for definition in target_area.find_elements_by_css_selector('.droparea[data-type="definition"]'):
			term_ids = set()

			for term in definition.find_elements_by_css_selector('.draggable[data-type="term"]'):
				term_ids.add(term.get_attribute('data-id'))

			if term_ids:
				definition_id = definition.get_attribute('data-id')
				answers[definition_id] = term_ids

		return answers

	def verify(self, context, after_crash=False):
		parsed = self._parse_ui()
		for definition_id in self.question.definitions.keys():
			self.protocol.verify(
				self.question.get_definition_label(definition_id),
				sorted(self.question.get_term_labels(self.current_answer.get(definition_id, set()))),
				sorted(self.question.get_term_labels(parsed.get(definition_id, set()))),
				after_crash=after_crash)

	def _get_answer_dimensions(self, context, language):
		answers = dict()

		for definition_id, term_ids in self.current_answer.items():
			definition = self.question.get_definition_label(definition_id)
			for term in self.question.get_term_labels(term_ids):
				answers[(definition, term)] = True

		return answers
