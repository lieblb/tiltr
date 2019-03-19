#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import cgi
from selenium.common.exceptions import NoSuchElementException

from .answer import Answer, Validness
from tiltr.driver.utils import wait_for_css_visible
from tiltr.data.exceptions import InteractionException
from tiltr.driver.utils import set_element_value


class AbstractLongTextAnswer(Answer):
	_export_names = dict(de="Ergebnis", en="Result")

	def __init__(self, driver, question, protocol):
		super().__init__(driver, question, protocol)
		assert question.__class__.__name__ == "LongTextQuestion"
		self.current_answer = None

	def randomize(self, context):
		answer, score = self.question.get_random_answer(context)
		self._set_answer(answer, score, context)
		return Validness()

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

	def _get_answer_dimensions(self, context, language):
		export_name = AbstractLongTextAnswer._export_names[language]
		pair = (export_name, self._encoded_current_answer(context))
		return dict((pair,))


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
		wait_for_css_visible(self.driver, iframe_css)

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
