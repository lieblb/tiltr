#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from collections import namedtuple
import re
import cgi
import html
from .questions import ClozeType

from ..result import AnswerProtocol

Choice = namedtuple('Choice', ['selector', 'label', 'checked'])


class SingleChoiceAnswer:
	def __init__(self, browser, question):
		assert question.__class__.__name__ == "SingleChoiceQuestion"
		self.browser = browser
		self.question = question
		self.current_answer = None
		self.current_score = None
		self.protocol = AnswerProtocol(self.question.title)

	def randomize(self, context):
		self._set_answer(*self.question.get_random_answer(context))

	def _set_answer(self, answer, score):
		for choice in self._parse_ui():
			self.protocol.choose(choice.label, choice.label == answer)
			if choice.label == answer:
				self.browser.find_by_css(choice.selector).first.click()
		self.current_answer = answer
		self.current_score = score

	def _parse_ui(self):
		choices = []
		for answer in self.browser.find_by_css('.ilc_question_SingleChoice .ilc_qanswer_Answer'):
			radio = answer.find_by_css('input[type="radio"]')
			label = answer.find_by_css('label[for="' + radio["id"] + '"]')
			c = Choice(selector="#" + radio["id"], label=label.text.strip(), checked=radio.checked)
			choices.append(c)
		return choices

	def verify(self, context):
		for c in self._parse_ui():
			if c.label == self.current_answer:
				expected = True
			else:
				expected = False
			self.protocol.verify(c.label, expected, c.checked)

	def encode(self, context):
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
	def __init__(self, browser, question):
		assert question.__class__.__name__ == "MultipleChoiceQuestion"
		self.browser = browser
		self.question = question
		self.current_answers = None
		self.current_score = None
		self.protocol = AnswerProtocol(self.question.title)

	def randomize(self, context):
		self._set_answers(*self.question.get_random_answer(context))

	def _set_answers(self, answers, score):
		for choice in self._parse_ui():
			elements = self.browser.find_by_css(choice.selector)
			assert len(elements) == 1
			checkbox = elements.first
			self.protocol.choose(choice.label, answers[choice.label])
			if answers[choice.label] != checkbox.checked:
				checkbox.click()
			assert checkbox.checked == answers[choice.label]
		self.current_answers = answers
		self.current_score = score

	def _parse_ui(self):
		choices = []
		for answer in self.browser.find_by_css('.ilc_question_MultipleChoice .ilc_qanswer_Answer'):
			checkbox = answer.find_by_css('input[type="checkbox"]')
			label = answer.find_by_css('label[for="' + checkbox["id"] + '"]')
			choices.append(Choice(selector="#" + checkbox["id"], label=label.text.strip(), checked=checkbox.checked))
		return choices

	def verify(self, context):
		for c in self._parse_ui():
			self.protocol.verify(c.label, self.current_answers[c.label], c.checked)

	def encode(self, context):
		answers = dict()
		for choice in self.question.choices.keys():
			if self.current_answers[choice]:
				answers[choice] = 1
			else:
				answers[choice] = 0
		return dict(
			title=self.question.title,
			answers=answers,
			protocol=self.protocol.encode())


Gap = namedtuple('Gap', ['selector', 'name', 'index', 'text'])
gap_name_pattern = re.compile("^gap_([0-9]+)$")


class ClozeAnswerGap(object):
	def __init__(self, browser, element):
		self.browser = browser

		self.name = element["name"]
		self._value = element.value

		match = gap_name_pattern.match(self.name)
		if not match:
			raise Exception("illegal gap name " + self.name)
		self.index = int(match.group(1))


class TextAnswerGap(ClozeAnswerGap):
	@property
	def value(self):
		return self._value

	@value.setter
	def value(self, new_value):
		matches = self.browser.find_by_name(self.name)
		assert len(matches) == 1
		matches.first.value = new_value
		self._value = new_value


class SelectAnswerGap(ClozeAnswerGap):
	@property
	def value(self):
		matches = self.browser.find_by_name(self.name)
		assert len(matches) == 1

		for option in matches.first.find_by_tag('option'):
			if int(option["value"]) == int(self._value):
				return option.text.strip()

		return None

	@value.setter
	def value(self, new_value):
		matches = self.browser.find_by_name(self.name)
		assert len(matches) == 1

		found = False
		for option in matches.first.find_by_tag('option'):
			if option.text.strip() == new_value:
				option.click()
				found = True
				break
		if not found:
			raise Exception('option "%s" not found.' % new_value)

		self._value = new_value


def implicit_text_to_number(context, value):
	if not context.workarounds.implicit_text_number_conversions:
		return value
	if len(value) >= 2 and value.endswith(".") and value[:-1].isdigit():
		# e.g. 13. -> 13
		value = value[:-1]
	elif len(value) >= 2 and value.startswith(".") and value[1:].isdigit():
		# e.g. .17 -> 0.17
		value = "0" + value
	elif value.endswith(".0"):
		# e.g. 5.0 -> 5
		value = value[:-2]
	return value


class ClozeAnswer(object):
	def __init__(self, browser, question):
		assert question.__class__.__name__ == "ClozeQuestion"
		self.browser = browser
		self.question = question
		self.current_answers = None
		self.current_score = None
		self.protocol = AnswerProtocol(self.question.title)

	def _ilias_gap_name(self, gap):
		return u"Lücke " + str(gap.index)

	def randomize(self, context):
		self._set_answers(*self.question.get_random_answer(context))

	def _set_answers(self, answers, score):
		ui = self._parse_ui()
		assert len(answers) == len(ui) and len(ui) == len(self.question.gaps)

		for gap in self.question.gaps.values():
			self.protocol.choose(gap.get_export_name(), answers[gap.index])
			ui[gap.index].value = answers[gap.index]

		self.current_answers = answers
		self.current_score = score

	def _parse_ui(self):
		root = self.browser.find_by_css(".ilc_question_ClozeTest")
		gaps = []

		for element in root.find_by_css('input[type="text"].ilc_qinput_TextInput'):
			gaps.append(TextAnswerGap(self.browser, element))

		for element in root.find_by_css("select.ilc_qinput_ClozeGapSelect"):
			gaps.append(SelectAnswerGap(self.browser, element))

		indexed = dict((gap.index, gap) for gap in gaps)
		assert len(gaps) == len(indexed)  # all unique?

		return indexed

	def verify(self, context):
		ui = self._parse_ui()
		assert len(self.current_answers) == len(ui) and len(ui) == len(self.question.gaps)

		for gap in self.question.gaps.values():
			self.protocol.verify(
				gap.get_export_name(),
				context.strip_whitespace(self.current_answers[gap.index]),
				ui[gap.index].value)

	def encode(self, context):
		answers = dict()
		for gap in self.question.gaps.values():
			value = self.current_answers[gap.index]
			if gap.get_type() == ClozeType.text:
				value = implicit_text_to_number(context, value)
			answers[gap.get_export_name()] = value
		return dict(
			title=self.question.title,
			answers=answers,
			protocol=self.protocol.encode())


class KPrimAnswer(object):
	def __init__(self, browser, question):
		assert question.__class__.__name__ == "KPrimQuestion"
		self.browser = browser
		self.question = question
		self.current_answers = None
		self.current_score = None
		self.protocol = AnswerProtocol(self.question.title)

	def randomize(self, context):
		self._set_answers(*self.question.get_random_answer(context))

	def _set_answers(self, answers, score):
		ui = self._parse_ui()

		assert len(answers) == 4
		for radios, answer in zip(ui, answers):
			radios[answer].check()

		self.current_answers = answers
		self.current_score = score

	def _parse_ui(self):
		root = self.browser.find_by_css(".ilc_question_KprimChoice")
		ui = []
		for i in range(4):
			radios = dict()
			for radio in root.find_by_name("kprim_choice_result_%d" % i):
				radios[bool(int(radio["value"]))] = radio
			ui.append(radios)
		return ui

	def verify(self, context):
		ui = self._parse_ui()

		for i in range(4):
			self.protocol.verify(
				str(i),
				self.current_answers[i],
				ui[i][True].checked)

	def encode(self, context):
		return dict(
			title=self.question.title,
			answers=dict(zip(self.question.names, [int(x) for x in self.current_answers])),
			protocol=self.protocol.encode())


class AbstractLongTextAnswer:
	def __init__(self, browser, question):
		assert question.__class__.__name__ == "LongTextQuestion"
		self.browser = browser
		self.question = question
		self.current_answer = None
		self.current_score = None
		self.protocol = AnswerProtocol(self.question.title)

	def randomize(self, context):
		answer, score = self.question.get_random_answer(context)
		self._set_answer(answer, score, context)

	def _set_answer(self, answer, score, context):
		self.protocol.choose("Ergebnis", answer)
		self._set_ui(answer, context)
		self.current_answer = answer
		self.current_score = score

	def verify(self, context):
		text = self._get_ui(context)

		# strip_whitespace, since sometimes ILIAS sometimes adds additional newlines, e.g.:
		# answer was ')GBUUD§/0A:1', but ILIAS stored '\n)GBUUD§/0A:1'

		self.protocol.verify(
			"Ergebnis",
			context.collapse_whitespace(context.strip_whitespace(
				"\n".join(context.strip_whitespace(s) for s in self.current_answer.split("\n")))),
			context.collapse_whitespace(context.strip_whitespace(text)))

	def encode(self, context):
		return dict(
			title=self.question.title,
			answers=dict(Ergebnis=self._encoded_current_answer(context)),
			protocol=self.protocol.encode())


class LongTextAnswerPlainHTML(AbstractLongTextAnswer):
	def _get_ui(self, context):
		selector = '.ilc_question_TextQuestion textarea.ilc_qlinput_LongTextInput'
		elements = self.browser.find_by_css(selector)
		assert len(elements) == 1
		return elements.first.value

	def _set_ui(self, value, context):
		selector = '.ilc_question_TextQuestion textarea.ilc_qlinput_LongTextInput'
		elements = self.browser.find_by_css(selector)
		assert len(elements) == 1
		elements.first.value = value

	def _encoded_current_answer(self, context):
		return self.current_answer


class LongTextAnswerTinyMCE(AbstractLongTextAnswer):
	def _get_ui(self, context):
		iframe_css = ".ilc_question_TextQuestion iframe"
		if not self.browser.find_by_css(iframe_css):
			raise Exception("could not find ilc_question_TextQuestion iframe")
		iframe_id = self.browser.find_by_css(iframe_css).first["id"]

		with self.browser.get_iframe(iframe_id) as iframe:
			selector = "#tinymce"
			if not iframe.find_by_css(selector):
				raise Exception("could not find TinyMCE element.")
			elements = iframe.find_by_css(selector)
			assert len(elements) == 1

			paragraphs = []
			for p in elements.first.find_by_tag("p"):
				paragraphs.append(context.strip_whitespace(p["textContent"]))
			return "\n".join(paragraphs)

	def _set_ui(self, value, context):
		iframe_css = ".ilc_question_TextQuestion iframe"
		if not self.browser.find_by_css(iframe_css):
			raise Exception("could not find ilc_question_TextQuestion iframe")
		iframe_id = self.browser.find_by_css(iframe_css).first["id"]

		with self.browser.get_iframe(iframe_id) as iframe:
			selector = "#tinymce"
			if not iframe.find_by_css(selector):
				raise Exception("could not find TinyMCE element.")
			elements = iframe.find_by_css(selector)
			assert len(elements) == 1

			paragraphs = []
			for line in value.split("\n"):
				paragraphs.append("<p>%s</p>" % cgi.escape(context.strip_whitespace(line)))

			tinymce = self.browser.driver.find_element_by_css_selector(selector)
			self.browser.driver.execute_script('arguments[0].innerHTML = arguments[1]', tinymce, "".join(paragraphs))

	def _encoded_current_answer(self, context):
		if len(self.current_answer) == 0:
			return ""
		else:
			s = ""
			for line in self.current_answer.split("\n"):
				if len(s) > 0:
					s += "\n"
				line = context.strip_whitespace(line)
				if context.workarounds.no_plaintext_longtext:
					line = cgi.escape(line)
				if context.workarounds.sloppy_whitespace:
					line = line.replace("\t", " ")
				s += "<p>%s</p>" % context.collapse_whitespace(line)
			return s
