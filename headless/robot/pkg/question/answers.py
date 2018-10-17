#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from collections import namedtuple
import re
import cgi
import json
import time
import html
from enum import Enum
from selenium.common.exceptions import NoSuchElementException

from .questions import ClozeType
from ..driver.utils import set_element_value
from ..exceptions import *


def normalize_answer(value):
	if isinstance(value, str):
		value = value.replace("\n", "\\n")
	return value


class Validness(Enum):
	VALID = 1
	INVALID = -1


class AnswerProtocol:
	def __init__(self, title):
		self.title = title
		self.entries = []

	def choose(self, key, value):
		self.entries.append((time.time(), "answered '%s' with '%s'" % (key, normalize_answer(value))))

	def verify(self, key, expected, actual, after_crash=False):
		if expected == actual:
			self.entries.append(
				(time.time(), "OK verified that '%s' is still '%s'" % (key, normalize_answer(expected))))
		else:
			err = "FAIL answer on '%s' was stored incorrectly: answer was '%s', but ILIAS stored '%s'" % (
				key, normalize_answer(expected), normalize_answer(actual))
			self.entries.append((time.time(), err))

			if after_crash:
				raise AutoSaveException("answer mismatch after crash: " + err);
			else:
				raise IntegrityException("answer mismatch during in-test verification: " + err)

	def add(self, text):
		self.entries.append((time.time(), text))

	def encode(self):
		return self.entries


Choice = namedtuple('Choice', ['selector', 'label', 'checked'])


class SingleChoiceAnswer:
	def __init__(self, driver, question):
		assert question.__class__.__name__ == "SingleChoiceQuestion"
		self.driver = driver
		self.question = question
		self.current_answer = None
		self.current_score = None
		self.protocol = AnswerProtocol(self.question.title)

	def randomize(self, context):
		self._set_answer(*self.question.get_random_answer(context))
		return Validness.VALID

	def _set_answer(self, answer, score):
		for choice in self._parse_ui():
			self.protocol.choose(choice.label, choice.label == answer)
			if choice.label == answer:
				self.driver.find_element_by_css_selector(choice.selector).click()
		self.current_answer = answer
		self.current_score = score

	def _parse_ui(self):
		choices = []
		for answer in self.driver.find_elements_by_css_selector('.ilc_question_SingleChoice .ilc_qanswer_Answer'):
			radio = answer.find_element_by_css_selector('input[type="radio"]')
			label = answer.find_element_by_css_selector('label[for="%s"]' % radio.get_attribute("id"))
			c = Choice(
				selector="#" + radio.get_attribute("id"),
				label=label.text.strip(),
				checked=radio.is_selected())
			choices.append(c)
		return choices

	def verify(self, context, after_crash=False):
		for c in self._parse_ui():
			if c.label == self.current_answer:
				expected = True
			else:
				expected = False
			self.protocol.verify(c.label, expected, c.checked, after_crash=after_crash)
		context.coverage.case_occurred(self.question, "verify", self.current_answer)

	def to_dict(self, context, language):
		answers = dict()
		for choice in self.question.choices.keys():
			if choice == self.current_answer:
				answers[choice] = 1
			else:
				answers[choice] = 0
		return dict(
			title=self.question.title,
			answers=answers,
			protocol=self.protocol.encode())


class MultipleChoiceAnswer:
	def __init__(self, driver, question):
		assert question.__class__.__name__ == "MultipleChoiceQuestion"
		self.driver = driver
		self.question = question
		self.current_answers = None
		self.current_score = None
		self.protocol = AnswerProtocol(self.question.title)

	def randomize(self, context):
		self._set_answers(*self.question.get_random_answer(context))
		return Validness.VALID

	def _set_answers(self, answers, score):
		for choice in self._parse_ui():
			checkbox = self.driver.find_element_by_css_selector(choice.selector)
			self.protocol.choose(choice.label, answers[choice.label])
			if answers[choice.label] != checkbox.is_selected():
				checkbox.click()
			assert checkbox.is_selected() == answers[choice.label]
		self.current_answers = answers
		self.current_score = score

	def _parse_ui(self):
		choices = []
		for answer in self.driver.find_elements_by_css_selector('.ilc_question_MultipleChoice .ilc_qanswer_Answer'):
			checkbox = answer.find_element_by_css_selector('input[type="checkbox"]')
			label = answer.find_element_by_css_selector('label[for="%s"]' % checkbox.get_attribute("id"))
			choices.append(Choice(
				selector="#" + checkbox.get_attribute("id"),
				label=label.text.strip(),
				checked=checkbox.is_selected()))
		return choices

	def _get_binary_answers(self):
		answers = dict()
		for choice in self.question.choices.keys():
			if self.current_answers[choice]:
				answers[choice] = 1
			else:
				answers[choice] = 0
		return answers

	def verify(self, context, after_crash=False):
		for c in self._parse_ui():
			self.protocol.verify(c.label, self.current_answers[c.label], c.checked, after_crash=after_crash)

		context.coverage.case_occurred(
			self.question, "verify", json.dumps(self._get_binary_answers()))

	def to_dict(self, context, language):
		return dict(
			title=self.question.title,
			answers=self._get_binary_answers(),
			protocol=self.protocol.encode())


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
		for option in match.find_elements_by_tag_name('option'):
			if option.text.strip() == new_value:
				option.click()
				found = True
				break
		if not found:
			raise InteractionException('option "%s" not found.' % new_value)
		self._value = new_value


def looks_like_an_unsigned_number(x):
	return len(x) >= 1 and x.count('.') <= 1 and all(y.isdigit() or len(y) < 1 for y in x.split('.'))


def looks_like_a_number(x):
	if x and x[0] in ("-", "+"):
		return looks_like_an_unsigned_number(x[1:])
	else:
		return looks_like_an_unsigned_number(x)


def implicit_text_to_number(context, value):
	if not context.workarounds.implicit_text_number_conversions:
		return value

	if len(value) >= 2 and value[0] == '+' and looks_like_a_number(value[1:]):
		# e.g. +9 -> 9
		value = value[1:]

	if looks_like_a_number(value):
		while value.endswith("0") and value.count('.') == 1 and not value.endswith(".0"):
			# e.g. 0.637010 -> 0.63701
			value = value[:-1]

		if len(value) >= 2 and value.endswith("."):
			# e.g. 13. -> 13
			value = value[:-1]
		elif len(value) >= 2 and value.startswith("."):
			# e.g. .17 -> 0.17
			value = "0" + value
		elif value.endswith(".0"):
			# e.g. 5.0 -> 5
			value = value[:-2]

	return value


def implicit_text_to_number_xls(context, value):
	# there are also several implicit conversions taking place when taking the number
	# from ILIAS into the XLS, but they are different from the ones inside ILIAS itself,
	# i.e. from implicit_text_to_number.

	if not context.workarounds.implicit_text_number_conversions:
		return value

	if looks_like_a_number(value):
		while value.endswith("0") and value.count('.') == 1 and not value.endswith(".0"):
			# e.g. 0.637010 -> 0.63701
			value = value[:-1]

		if len(value) >= 2 and value[0] == '.' and value[-1] != '0':
			# e.g. .94853 -> .948530
			value += "0"

		if value == "0.0" or value == "-0.0" or value == "-0":
			# e.g. "0.0" -> "0".  note that other conversions, e.g. 597.0 -> 597, don't
			# take place!
			value = "0"

	return value


class ClozeAnswer(object):
	def __init__(self, driver, question):
		assert question.__class__.__name__ == "ClozeQuestion"
		self.driver = driver
		self.question = question
		self.current_answers = None
		self.current_score = None
		self.protocol = AnswerProtocol(self.question.title)

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
				implicit_text_to_number(context, recorded_value),
				context.strip_whitespace(ui[gap.index].value),
				after_crash=after_crash)
			gap.add_verify_coverage(context.coverage, recorded_value)

	def to_dict(self, context, language):
		answers = dict()
		for gap in self.question.gaps.values():
			value = self.current_answers[gap.index]
			if gap.get_type() == ClozeType.text:
				value = implicit_text_to_number(context, value)

				# apply implicit_text_to_number twice here, as ILIAS converts numbers to
				# into DB first, then into XLS, and will make ".0" into "0.0" during the
				# test, which will become "0" in excel export. not good.
				value = implicit_text_to_number_xls(context, value)

			answers[gap.get_export_name(language)] = value
		return dict(
			title=self.question.title,
			answers=answers,
			protocol=self.protocol.encode())


class KPrimAnswer(object):
	def __init__(self, driver, question):
		assert question.__class__.__name__ == "KPrimQuestion"
		self.driver = driver
		self.question = question
		self.current_answers = None
		self.current_score = None
		self.protocol = AnswerProtocol(self.question.title)
		self.n_rows = 4

	def randomize(self, context):
		self._set_answers(*self.question.get_random_answer(context))
		return Validness.VALID

	def _set_answers(self, answers, score):
		ui = self._parse_ui()

		assert len(answers) == self.n_rows
		for index, radios, answer in zip(range(self.n_rows), ui, answers):
			self.protocol.choose(index, answer)
			radios[answer].click()

		self.current_answers = answers
		self.current_score = score

	def _parse_ui(self):
		root = self.driver.find_element_by_css_selector(".ilc_question_KprimChoice")
		ui = []
		for i in range(self.n_rows):
			radios = dict()
			for radio in root.find_elements_by_name("kprim_choice_result_%d" % i):
				radios[bool(int(radio.get_attribute("value")))] = radio
			ui.append(radios)
		return ui

	def _get_binary_answers(self):
		return dict(zip(self.question.names, [int(x) for x in self.current_answers]))

	def verify(self, context, after_crash=False):
		ui = self._parse_ui()

		for i in range(self.n_rows):
			self.protocol.verify(
				str(i),
				self.current_answers[i],
				ui[i][True].is_selected(),
				after_crash=after_crash)

		context.coverage.case_occurred(
			self.question, "verify", json.dumps(self._get_binary_answers()))

	def to_dict(self, context, language):
		return dict(
			title=self.question.title,
			answers=self._get_binary_answers(),
			protocol=self.protocol.encode())


class AbstractLongTextAnswer:
	_export_names = dict(de="Ergebnis", en="Result")

	def __init__(self, driver, question):
		assert question.__class__.__name__ == "LongTextQuestion"
		self.driver = driver
		self.question = question
		self.current_answer = None
		self.current_score = None
		self.protocol = AnswerProtocol(self.question.title)

	def randomize(self, context):
		answer, score = self.question.get_random_answer(context)
		self._set_answer(answer, score, context)
		return Validness.VALID

	def _set_answer(self, answer, score, context):
		self.protocol.choose("Ergebnis", answer)
		self._set_ui(answer, context)
		self.current_answer = answer
		self.current_score = score

	def verify(self, context, after_crash):
		text = self._get_ui(context)

		# strip_whitespace, since sometimes ILIAS sometimes adds additional newlines, e.g.:
		# answer was ')GBUUD§/0A:1', but ILIAS stored '\n)GBUUD§/0A:1'

		self.protocol.verify(
			"Ergebnis",
			context.collapse_whitespace(context.strip_whitespace(
				"\n".join(context.strip_whitespace(s) for s in self.current_answer.split("\n")))),
			context.collapse_whitespace(context.strip_whitespace(text)),
			after_crash=after_crash)

		self.question.add_verify_coverage(context.coverage, dict(Ergebnis=text))

	def to_dict(self, context, language):
		export_name = AbstractLongTextAnswer._export_names[language]
		pair = (export_name, self._encoded_current_answer(context))
		return dict(
			title=self.question.title,
			answers=dict((pair,)),
			protocol=self.protocol.encode())


class LongTextAnswerPlainHTML(AbstractLongTextAnswer):
	def _get_ui(self, context):
		selector = '.ilc_question_TextQuestion textarea.ilc_qlinput_LongTextInput'
		element = self.driver.find_element_by_css_selector(selector)
		return element.get_attribute("value")

	def _set_ui(self, value, context):
		selector = '.ilc_question_TextQuestion textarea.ilc_qlinput_LongTextInput'
		element = self.driver.find_element_by_css_selector(selector)
		set_element_value(self.driver, element, value)

	def _encoded_current_answer(self, context):
		return self.current_answer


class LongTextAnswerTinyMCE(AbstractLongTextAnswer):
	def _tinymce(self, f):
		iframe_css = ".ilc_question_TextQuestion iframe"
		try:
			iframe = self.driver.find_element_by_css_selector(iframe_css)
		except NoSuchElementException:
			raise InteractionException("could not find ilc_question_TextQuestion iframe")
		self.driver.switch_to_frame(iframe)

		try:
			try:
				tinymce = self.driver.find_element_by_css_selector("#tinymce")
			except NoSuchElementException:
				raise InteractionException("could not find TinyMCE element.")

			return f(tinymce)
		finally:
			self.driver.switch_to_default_content()

	def _get_ui(self, context):
		def f(tinymce):
			paragraphs = []
			for p in tinymce.find_elements_by_tag_name("p"):
				paragraphs.append(context.strip_whitespace(p.get_attribute("textContent")))
			return "\n".join(paragraphs)

		return self._tinymce(f)

	def _set_ui(self, value, context):
		def f(tinymce):
			paragraphs = []
			for line in value.split("\n"):
				paragraphs.append("<p>%s</p>" % cgi.escape(context.strip_whitespace(line)))

			self.driver.execute_script('arguments[0].innerHTML = arguments[1]', tinymce, "".join(paragraphs))

		self._tinymce(f)

	def _encoded_current_answer(self, context):
		if len(self.current_answer) == 0:
			return ""
		else:
			s = ""
			answer = self.current_answer

			for line in answer.split("\n"):
				if len(s) > 0:
					s += "\n"
				line = context.strip_whitespace(line)
				if context.workarounds.no_plaintext_longtext:
					line = cgi.escape(line)
				if context.workarounds.sloppy_whitespace:
					line = line.replace("\t", " ")
				s += "<p>%s</p>" % context.collapse_whitespace(line)

			return s
