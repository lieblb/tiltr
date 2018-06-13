#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from collections import namedtuple
import random
from enum import Enum


class ClozeType(Enum):
	text = 0
	dropdown = 1
	numeric = 2


class ClozeComparator(Enum):
	ignore_case = "ci"
	case_sensitive = "cs"


class ClozeQuestionGap():
	def __init__(self, index):
		self.index = index

	def get_export_name(self):
		return u"Lücke " + str(self.index + 1)


class ClozeQuestionTextGap(ClozeQuestionGap):
	def __init__(self, index, options, comparator, size):
		ClozeQuestionGap.__init__(self, index)
		self.options = options
		self.comparator = comparator
		self.size = size

	def get_random_choice(self, context):
		if random.random() < 0.75 and not context.prefer_text():
			# pick scored answer.
			text, score = random.choice(list(self.options.items()))

			mode = random.choices(
				("unmodified", "randchar", "randcase"), weights=(0.5, 0.25, 0.25))[0]

			if mode == "unmodified":
				# keep exactly as specified.
				return text, score
			else:
				# modify case or content.
				chars = []
				for i in range(len(text)):
					r = random.random()
					if mode == "randchar" and r < 0.2:
						chars.append(random.choice(context.cloze_random_chars))
					elif mode == "randcase" and r < 0.2:
						chars.append(text[i].swapcase())
					else:
						chars.append(text[i])
				text = "".join(chars)
				return text, self._get_score(text)
		else:
			# make up something random and probably wrong.
			text = context.produce_text(self.size, context.cloze_random_chars)
			return text, self._get_score(text)

	def _get_score(self, text):
		if self.comparator == ClozeComparator.case_sensitive:
			return self.options.get(text, 0.0)

		assert self.comparator == ClozeComparator.ignore_case
		for option, score in self.options.items():
			if option.casefold() == text.casefold():
				return score

		return 0.0

class ClozeQuestionDropDownGap(ClozeQuestionGap):
	def __init__(self, index, options):
		ClozeQuestionGap.__init__(self, index)
		self.options = options

	def get_random_choice(self, context):
		return random.choice(list(self.options.items()))


class ClozeQuestionNumericGap(ClozeQuestionGap):
	def __init__(self, index):
		ClozeQuestionGap.__init__(self, index)


def parse_gap_size(browser, gap_index, fallback_length):
	elements = browser.find_by_name("gap_%d_gapsize" % gap_index)
	assert len(elements) == 1
	text = elements.first.value.strip()
	assert isinstance(text, str)
	if text == '':
		return fallback_length
	else:
		return int(text)


class ClozeQuestion():
	def __init__(self, browser, title):
		self.title = title
		self.gaps = dict()

		fallback_length = browser.find_by_name("fixedTextLength").first.value.strip()
		if fallback_length == '':
			fallback_length = 7
		else:
			fallback_length = int(fallback_length)

		comparator = ClozeComparator(browser.find_by_css(
			"#textgap_rating option[selected]").first["value"])

		while True:
			options = dict()
			gap_index = len(self.gaps)

			while True:
				answer = browser.find_by_name("gap_%d[answer][%d]" % (gap_index, len(options)))
				if not answer:
					break
				points = browser.find_by_name("gap_%d[points][%d]" % (gap_index, len(options)))

				options[answer.first.value] = float(points.first.value)

			if not options:
				break

			cloze_type = ClozeType(int(browser.find_by_name("clozetype_%d" % gap_index).first.value))

			if cloze_type == ClozeType.text:
				gap = ClozeQuestionTextGap(
					gap_index, options, comparator, parse_gap_size(browser, gap_index, fallback_length))
			elif cloze_type == ClozeType.dropdown:
				gap = ClozeQuestionDropDownGap(gap_index, options)
			#elif cloze_type == ClozeType.numeric:
			#	gap = ClozeQuestionNumericGap(gap_index, parse_gap_size(browser, gap_index, fallback_length))
			# gap_0_numeric
			# gap_0_numeric_lower
			# gap_0_numeric_upper
			# gap_0_numeric_points
			else:
				raise Exception("unsupported cloze type " + str(cloze_type))				

			self.gaps[gap_index] = gap

	def get_random_answer(self, context):
		answers = dict()
		score = 0.0

		for gap in self.gaps.values():
			choice, choice_score = gap.get_random_choice(context)
			score += choice_score
			answers[gap.index] = choice

		return answers, score


class SingleChoiceQuestion:
	def __init__(self, browser, title):
		self.title = title
		self.choices = dict()

		while True:
			choice = browser.find_by_name("choice[answer][%d]" % len(self.choices))
			if not choice:
				break
			points = browser.find_by_name("choice[points][%d]" % len(self.choices))

			self.choices[choice.first.value] = float(points.first.value)

	def get_random_answer(self, context):
		choice = random.choice(list(self.choices.keys()))
		return choice, self.choices[choice]


MultipleChoiceItem = namedtuple('MultipleChoiceItem', ['checked_score', 'unchecked_score'])


class MultipleChoiceQuestion:
	def __init__(self, browser, title):
		self.title = title
		self.choices = dict()

		while True:
			choice = browser.find_by_name("choice[answer][%d]" % len(self.choices))
			if not choice:
				break
			points = browser.find_by_name("choice[points][%d]" % len(self.choices))
			points_unchecked = browser.find_by_name("choice[points_unchecked][%d]" % len(self.choices))

			self.choices[choice.first.value] = MultipleChoiceItem(
				checked_score=float(points.first.value),
				unchecked_score=float(points_unchecked.first.value))

	def get_random_answer(self, context):
		answers = dict()

		if not context.workarounds.supports_empty_answers:
			# special case here : ILIAS 5 does not recognize an "all false" MC as valid answer and
			# will not save it (the score in XLS will be None); we need to pick at least 1 checkbox.

			# check 1 item.
			answers[random.choice(list(self.choices.keys()))] = True

		# check the remaining items randomly.
		for label, item in self.choices.items():
			if label not in answers:
				answers[label] = random.random() < 0.5

		# compute the score.
		score = 0.0
		for label, value in answers.items():
			item = self.choices[label]
			if value:
				score += item.checked_score
			else:
				score += item.unchecked_score

		return answers, score


class LongTextQuestion:
	def __init__(self, browser, title):
		self.title = title

	def get_random_answer(self, context):
		while True:
			text = context.produce_text(20, context.long_text_random_chars)

			if context.workarounds.supports_empty_answers:
				break

			# ASSUMPTION: ILIAS does not support empty answers, since they will end up with
			# a None score in the XLS
			if len(text.strip()) >= 1:
				break
		return text, 0.0
