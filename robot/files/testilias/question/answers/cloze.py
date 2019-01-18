#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from collections import namedtuple
import re

from .answer import Answer, Validness
from ..questions.cloze import ClozeType
from testilias.driver.utils import set_element_value
from testilias.data.exceptions import InteractionException


Gap = namedtuple('Gap', ['selector', 'name', 'index', 'text'])
gap_name_pattern = re.compile("^gap_([0-9]+)$")


class ClozeAnswerGap(object):
	def __init__(self, driver, element):
		self.driver = driver

		self.name = element.get_attribute("name")
		self._value = element.get_attribute("value")

		match = gap_name_pattern.match(self.name)
		if not match:
			raise InteractionException("illegal gap name " + self.name)
		self.index = int(match.group(1))


class TextOrNumericAnswerGap(ClozeAnswerGap):
	@property
	def value(self):
		return self._value

	@value.setter
	def value(self, new_value):
		match = self.driver.find_element_by_name(self.name)
		set_element_value(self.driver, match, new_value)
		self._value = new_value


class SelectAnswerGap(ClozeAnswerGap):
	@property
	def value(self):
		match = self.driver.find_element_by_name(self.name)
		for option in match.find_elements_by_tag_name('option'):
			if int(option.get_attribute("value")) == int(self._value):
				return option.text.strip()

		return None

	@value.setter
	def value(self, new_value):
		match = self.driver.find_element_by_name(self.name)
		found = False
		option_values = []
		for option in match.find_elements_by_tag_name('option'):
			option_value = option.text.strip()
			if option_value == new_value:
				option.click()
				found = True
				break
			option_values.append(option_value)
		if not found:
			raise InteractionException(
				'option "%s" not found in %s.' % (new_value, option_values))
		self._value = new_value


class ClozeAnswer(Answer):
	def __init__(self, driver, question, protocol):
		super().__init__(driver, question, protocol)
		assert question.__class__.__name__ == "ClozeQuestion"
		self.current_answer = None

	def randomize(self, context):
		answers, valid, score = self.question.get_random_answer(context)
		self._set_answers(answers, score)
		return Validness.VALID if all(valid.values()) else Validness.INVALID

	def _set_answers(self, answers, score):
		ui = self._parse_ui()
		assert len(answers) == len(ui) and len(ui) == len(self.question.gaps)

		for gap in self.question.gaps.values():
			self.protocol.choose(gap.get_export_name("de"), answers[gap.index])
			ui[gap.index].value = answers[gap.index]

		self.current_answers = answers
		self.current_score = score

	def _parse_ui(self):
		root = self.driver.find_element_by_css_selector(".ilc_question_ClozeTest")
		gaps = []

		for element in root.find_elements_by_css_selector('input[type="text"].ilc_qinput_TextInput'):
			gaps.append(TextOrNumericAnswerGap(self.driver, element))

		for element in root.find_elements_by_css_selector("select.ilc_qinput_ClozeGapSelect"):
			gaps.append(SelectAnswerGap(self.driver, element))

		indexed = dict((gap.index, gap) for gap in gaps)
		assert len(gaps) == len(indexed)  # all unique?

		return indexed

	def verify(self, context, after_crash=False):
		ui = self._parse_ui()
		assert len(self.current_answers) == len(ui) and len(ui) == len(self.question.gaps)

		for gap in self.question.gaps.values():
			recorded_value = context.strip_whitespace(self.current_answers[gap.index])
			self.protocol.verify(
				gap.get_export_name("de"),
				context.implicit_text_to_number(recorded_value),
				context.implicit_text_to_number(context.strip_whitespace(ui[gap.index].value)),
				after_crash=after_crash)
			gap.add_verify_coverage(context.coverage, recorded_value)

	def _get_answer_dimensions(self, context, language):
		answers = dict()
		for gap in self.question.gaps.values():
			value = self.current_answers[gap.index]
			if gap.get_type() == ClozeType.text:
				value = context.implicit_text_to_number(value)

				# apply implicit_text_to_number twice here, as ILIAS converts numbers to
				# into DB first, then into XLS, and will make ".0" into "0.0" during the
				# test, which will become "0" in excel export. not good.
				value = context.implicit_text_to_number_xls(value)

			answers[gap.get_export_name(language)] = value
		return answers
