#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from collections import namedtuple
import random
from enum import Enum
from decimal import *
from collections import defaultdict


class ClozeType(Enum):
	text = 0
	select = 1
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
				return text, self.get_score(text)
		else:
			# make up something random and probably wrong.
			text = context.produce_text(self.size, context.cloze_random_chars)
			return text, self.get_score(text)

	def get_score(self, text):
		if self.comparator == ClozeComparator.case_sensitive:
			return self.options.get(text, Decimal(0))

		assert self.comparator == ClozeComparator.ignore_case
		for option, score in self.options.items():
			if option.casefold() == text.casefold():
				return score

		return Decimal(0)

	def get_type(self):
		return ClozeType.text


class ClozeQuestionSelectGap(ClozeQuestionGap):
	def __init__(self, index, options):
		ClozeQuestionGap.__init__(self, index)
		self.options = options

	def get_random_choice(self, context):
		return random.choice(list(self.options.items()))

	def get_score(self, text):
		return self.options.get(text, Decimal(0))

	def get_type(self):
		return ClozeType.select


class ClozeQuestionNumericGap(ClozeQuestionGap):
	def __init__(self, browser, index, size):
		ClozeQuestionGap.__init__(self, index)
		self.size = size

		self.numeric_value = Decimal(browser.find_by_name("gap_%d_numeric" % index).first.value)
		self.numeric_lower = Decimal(browser.find_by_name("gap_%d_numeric_lower" % index).first.value)
		self.numeric_upper = Decimal(browser.find_by_name("gap_%d_numeric_upper" % index).first.value)
		self.score = Decimal(browser.find_by_name("gap_%d_numeric_points" % index).first.value)

		self.exponent = min(x.as_tuple().exponent for x in (self.numeric_value, self.numeric_lower, self.numeric_upper))

	def get_random_choice(self, context):
		t = random.randint(1, 4)
		if t == 1:
			return str(self.numeric_lower), self.score
		elif t == 2:
			return str(self.numeric_upper), self.score
		elif t == 3:
			x = Decimal(random.uniform(float(self.numeric_lower), float(self.numeric_upper)))
			return str(round(x, -self.exponent)), self.score
		else:
			eps_exp = self.exponent - random.randint(0, 2)  # e.g. enter 5.32 for a numeric range defined as [3, 7]
			eps = 10.0 ** eps_exp
			d = float(self.numeric_upper - self.numeric_lower)
			off = Decimal(str(random.uniform(eps, 1000 * d)))
			if random.random() < 0.5:
				return str(round(self.numeric_lower - off, -self.exponent)), Decimal(0)
			else:
				return str(round(self.numeric_upper + off, -self.exponent)), Decimal(0)

	def get_score(self, text):
		value = Decimal(text)
		if value >= self.numeric_lower and value <= self.numeric_upper:
			return self.score
		else:
			return Decimal(0)

	def get_type(self):
		return ClozeType.numeric


def parse_gap_size(browser, gap_index, fallback_length):
	elements = browser.find_by_name("gap_%d_gapsize" % gap_index)
	assert len(elements) == 1
	text = elements.first.value.strip()
	assert isinstance(text, str)
	if text == '':
		return fallback_length
	else:
		return int(text)


def parse_gap_options(browser, gap_index):
	options = dict()

	while True:
		answer = browser.find_by_name("gap_%d[answer][%d]" % (gap_index, len(options)))
		if not answer:
			break
		points = browser.find_by_name("gap_%d[points][%d]" % (gap_index, len(options)))

		options[answer.first.value] = Decimal(points.first.value)

	return options


class ClozeQuestion():
	def __init__(self, browser, title):
		self.title = title
		self.gaps = dict()

		self.identical_scoring = browser.find_by_name("identical_scoring").first.checked

		fallback_length = browser.find_by_name("fixedTextLength").first.value.strip()
		if fallback_length == '':
			fallback_length = 7
		else:
			fallback_length = int(fallback_length)

		comparator = ClozeComparator(browser.find_by_css(
			"#textgap_rating option[selected]").first["value"])

		while True:
			gap_index = len(self.gaps)

			if not browser.find_by_name("clozetype_%d" % gap_index):
				break

			cloze_type = ClozeType(int(browser.find_by_name("clozetype_%d" % gap_index).first.value))

			if cloze_type == ClozeType.text or cloze_type == ClozeType.select:
				options = parse_gap_options(browser, gap_index)

				if not options:
					break

				if cloze_type == ClozeType.text:
					gap = ClozeQuestionTextGap(
						gap_index, options, comparator, parse_gap_size(browser, gap_index, fallback_length))
				elif cloze_type == ClozeType.select:
					gap = ClozeQuestionSelectGap(gap_index, options)

			elif cloze_type == ClozeType.numeric:
				gap = ClozeQuestionNumericGap(
					browser, gap_index, parse_gap_size(browser, gap_index, fallback_length))

			else:
				raise Exception("unsupported cloze type " + str(cloze_type))				

			self.gaps[gap_index] = gap

	def get_random_answer(self, context):
		answers = dict()
		score = Decimal(0)

		while True:
			previous_answers = defaultdict(list)
			previous_answers_prob = 0.1 if self.identical_scoring else 0.25
			all_empty = True

			for gap in self.gaps.values():
				previous = previous_answers[gap.get_type()]
				if len(previous) > 0 and random.random() < previous_answers_prob:
					# use some previous answer to test identical_scoring option
					choice = random.choice(previous)
					if self.identical_scoring:
						choice_score = gap.get_score(choice)
					else:
						choice_score = Decimal(0)
				else:
					choice, choice_score = gap.get_random_choice(context)
				previous.append(choice)
				score += choice_score
				answers[gap.index] = choice
				all_empty = all_empty and len(choice) == 0

			if all_empty and context.workarounds.disallow_empty_answers:
				pass  # retry
			else:
				break

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

			self.choices[choice.first.value] = Decimal(points.first.value)

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
				checked_score=Decimal(points.first.value),
				unchecked_score=Decimal(points_unchecked.first.value))

	def get_random_answer(self, context):
		answers = dict()

		if context.workarounds.disallow_empty_answers:
			# special case here : ILIAS 5 does not recognize an "all false" MC as valid answer and
			# will not save it (the score in XLS will be None); we need to pick at least 1 checkbox.

			# check 1 item.
			answers[random.choice(list(self.choices.keys()))] = True

		# check the remaining items randomly.
		for label, item in self.choices.items():
			if label not in answers:
				answers[label] = random.random() < 0.5

		# compute the score.
		score = Decimal(0)
		for label, value in answers.items():
			item = self.choices[label]
			if value:
				score += item.checked_score
			else:
				score += item.unchecked_score

		return answers, score


class KPrimQuestion:
	def __init__(self, browser, title):
		self.title = title

		self.halfpoints = browser.find_by_name("score_partsol_enabled").first.checked
		self.score = Decimal(browser.find_by_name("points").first.value)
		self.solution = []
		self.names = []

		for i in range(4):
			is_right = None

			for radio in browser.find_by_name("kprim_answers[correctness][%d]" % i):
				if int(radio["value"]) == 1:
					is_right = radio.checked

			assert is_right is not None
			self.solution.append(is_right)

			self.names.append(browser.find_by_name("kprim_answers[answer][%d]" % i).first["value"])

	def _get_score(self, answers):
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
		answers = [random.random() < 0.5 for _ in range(4)]
		return answers, self._get_score(answers)


class LongTextQuestion:
	def __init__(self, browser, title):
		self.title = title

	def get_random_answer(self, context):
		while True:
			text = context.produce_text(20, context.long_text_random_chars)

			if not context.workarounds.disallow_empty_answers:
				break

			# ASSUMPTION: ILIAS does not support empty answers, since they will end up with
			# a None score in the XLS
			if len(text.strip()) >= 1:
				break
		return text, Decimal(0)
