#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from collections import namedtuple
import random
import itertools
import json
from enum import Enum
from decimal import *
from collections import defaultdict, Counter
from selenium.common.exceptions import NoSuchElementException

from ..driver.utils import wait_for_page_load, set_element_value

def readjust_score(score):
	delta = Decimal(random.randint(-8, 8)) / Decimal(4)
	score += delta
	score = max(score, Decimal(0))
	return score


class ClozeType(Enum):
	text = 0
	select = 1
	numeric = 2


class ClozeComparator(Enum):
	ignore_case = "ci"
	case_sensitive = "cs"


class ClozeQuestionGap():
	def __init__(self, question, index):
		self.question = question
		self.index = index

	def get_export_name(self):
		return u"Lücke " + str(self.index + 1)


class ClozeQuestionTextGap(ClozeQuestionGap):
	def __init__(self, question, index, options, comparator, size):
		ClozeQuestionGap.__init__(self, question, index)
		self.options = options
		self.comparator = comparator
		self.size = size

	def initialize_coverage(self, coverage, context):
		for mode in ("verify", "export"):
			for args in coverage.text_cases(self.size, context):
				coverage.add_case(self.question, self.index, mode, *args)
			for solution in self.options.keys():
				coverage.add_case(self.question, self.index, mode, "solution", solution)

	def add_verify_coverage(self, coverage, value):
		for args in coverage.text_cases_occurred(value):
			coverage.case_occurred(self.question, self.index, "verify", *args)
		if value in self.options:
			coverage.case_occurred(self.question, self.index, "verify", "solution", value)

	def add_export_coverage(self, coverage, value):
		value = str(value)
		for args in coverage.text_cases_occurred(value):
			coverage.case_occurred(self.question, self.index, "export", *args)
		if value in self.options:
			coverage.case_occurred(self.question, self.index, "export", "solution", value)

	def _modify_solution(self, text, score, context):
		mode = random.choices(
			("unmodified", "randchar", "randcase"),
			weights=(0.5, 0.25, 0.25))[0]

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

	def get_random_choice(self, context):
		if random.random() < 0.75 and not context.prefer_text():
			# pick scored answer.
			text, score = random.choice(list(self.options.items()))
			return self._modify_solution(text, score, context)
		else:
			# make up something random and probably wrong.
			if random.random() < 0.9:
				# produce some random test.
				text = context.produce_text(
					self.size, context.cloze_random_chars)
			else:
				# insert a random number. this is useful to test
				# workarounds.implicit_text_number_conversions.
				num_digits = random.randint(0, 2)
				format = (".%d" % num_digits) + "%f"
				text = format % (random.random() * 1000)
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
	def __init__(self, question, index, options):
		ClozeQuestionGap.__init__(self, question, index)
		self.options = options

	def initialize_coverage(self, coverage, context):
		for value in self.options.keys():
			for mode in ("verify", "export"):
				coverage.add_case(self.question, self.index, mode, value)

	def add_verify_coverage(self, coverage, value):
		coverage.case_occurred(self.question, self.index, "verify", value)

	def add_export_coverage(self, coverage, value):
		value = str(value)
		coverage.case_occurred(self.question, self.index, "export", value)

	def get_random_choice(self, context):
		return random.choice(list(self.options.items()))

	def get_score(self, text):
		return self.options.get(text, Decimal(0))

	def get_type(self):
		return ClozeType.select


class ClozeQuestionNumericGap(ClozeQuestionGap):
	def __init__(self, question, index, size, driver):
		ClozeQuestionGap.__init__(self, question, index)
		self.size = size

		self.numeric_value = Decimal(driver.find_element_by_name("gap_%d_numeric" % index).get_attribute("value"))
		self.numeric_lower = Decimal(driver.find_element_by_name("gap_%d_numeric_lower" % index).get_attribute("value"))
		self.numeric_upper = Decimal(driver.find_element_by_name("gap_%d_numeric_upper" % index).get_attribute("value"))
		self.score = Decimal(driver.find_element_by_name("gap_%d_numeric_points" % index).get_attribute("value"))

		self.exponent = min(x.as_tuple().exponent for x in (self.numeric_value, self.numeric_lower, self.numeric_upper))

	def initialize_coverage(self, coverage, context):
		for mode in ("verify", "export"):
			coverage.add_case(self.question, self.index, mode, str(self.numeric_value))
			coverage.add_case(self.question, self.index, mode, str(self.numeric_lower))
			coverage.add_case(self.question, self.index, mode, str(self.numeric_upper))

	def add_verify_coverage(self, coverage, value):
		x = str(value)
		if x in [str(self.numeric_value), str(self.numeric_lower), str(self.numeric_upper)]:
			coverage.case_occurred(self.question, self.index, "verify", x)

	def add_export_coverage(self, coverage, value):
		x = str(value)
		if x in [str(self.numeric_value), str(self.numeric_lower), str(self.numeric_upper)]:
			coverage.case_occurred(self.question, self.index, "export", x)

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
		if self.numeric_lower <= value <= self.numeric_upper:
			return self.score
		else:
			return Decimal(0)

	def get_type(self):
		return ClozeType.numeric


def parse_gap_size(driver, gap_index, fallback_length):
	element = driver.find_element_by_name("gap_%d_gapsize" % gap_index)
	text = element.get_attribute("value").strip()
	assert isinstance(text, str)
	if text == '':
		return fallback_length
	else:
		return int(text)


def parse_gap_options(driver, gap_index):
	options = dict()

	while True:
		try:
			answer = driver.find_element_by_id("gap_%d[answer][%d]" % (gap_index, len(options)))
		except NoSuchElementException:
			break
		points = driver.find_element_by_id("gap_%d[points][%d]" % (gap_index, len(options)))
		options[answer.get_attribute("value")] = Decimal(points.get_attribute("value"))

	return options


class ClozeQuestion():
	def __init__(self, driver, title):
		self.title = title
		self.gaps = dict()

		self.identical_scoring = driver.find_element_by_name("identical_scoring").is_selected()

		fallback_length = driver.find_element_by_name("fixedTextLength").get_attribute("value").strip()
		if fallback_length == '':
			fallback_length = 7
		else:
			fallback_length = int(fallback_length)

		self.comparator = ClozeComparator(driver.find_element_by_css_selector(
			"#textgap_rating option[selected]").get_attribute("value"))

		while True:
			gap_index = len(self.gaps)

			try:
				cloze = driver.find_element_by_name("clozetype_%d" % gap_index)
			except NoSuchElementException:
				break

			cloze_type = ClozeType(int(cloze.get_attribute("value")))

			if cloze_type == ClozeType.text or cloze_type == ClozeType.select:
				options = parse_gap_options(driver, gap_index)

				if not options:
					break

				if cloze_type == ClozeType.text:
					gap = ClozeQuestionTextGap(
						self, gap_index, options, self.comparator,
						parse_gap_size(driver, gap_index, fallback_length))
				elif cloze_type == ClozeType.select:
					gap = ClozeQuestionSelectGap(self, gap_index, options)

			elif cloze_type == ClozeType.numeric:
				gap = ClozeQuestionNumericGap(
					self, gap_index,
					parse_gap_size(driver, gap_index, fallback_length),
					driver)

			else:
				raise Exception("unsupported cloze type " + str(cloze_type))				

			self.gaps[gap_index] = gap

	def initialize_coverage(self, coverage, context):
		for gap in self.gaps.values():
			gap.initialize_coverage(coverage, context)

	def add_export_coverage(self, coverage, answers):
		gaps = dict()
		for gap in self.gaps.values():
			gaps[gap.get_export_name()] = self.gaps[gap.index]
		for gap_name, value in answers.items():
			print("cloze value %s" % value)
			gaps[gap_name].add_export_coverage(coverage, str(value))

	def get_gap_definition(self, index):
		return self.gap[index]

	def _get_normalized(self, s):
		if self.comparator == ClozeComparator.case_sensitive:
			return s
		else:
			assert self.comparator == ClozeComparator.ignore_case
			return s.casefold()

	def _is_empty_answer(self, answer, context):
		answer = context.strip_whitespace(answer)
		return len(answer) == 0

	def get_random_answer(self, context):
		while True:
			answers = dict()

			previous_answers = defaultdict(set)
			previous_answers_prob = 0.1 if self.identical_scoring else 0.25
			all_empty = True

			for gap in self.gaps.values():
				previous = previous_answers[gap.get_type()]

				if len(previous) > 0 and random.random() < previous_answers_prob:
					# use some previous answer to explicitly test identical_scoring
					# option, though it's also tested through the case below.
					choice = random.choice(list(previous))
				else:
					choice, choice_score = gap.get_random_choice(context)

				previous.add(choice)
				answers[gap.index] = choice
				all_empty = all_empty and self._is_empty_answer(choice, context)

			if all_empty and context.workarounds.disallow_empty_answers:
				pass  # retry
			else:
				return answers, self.compute_score_by_indices(answers, context)

	def readjust_scores(self, driver, report):
		pass

	def compute_score(self, answers, context):
		gaps = dict()
		for gap in self.gaps.values():
			gaps[gap.get_export_name()] = gap.index

		indexed_answers = dict()
		for name, value in answers.items():
			indexed_answers[gaps[name]] = value
		return self.compute_score_by_indices(indexed_answers, context)

	def compute_score_by_indices(self, answers, context):
		score = Decimal(0)
		given_answers = set()

		for index, text in answers.items():
			if not self.identical_scoring:
				normalized = text

				if not context.workarounds.identical_scoring_ignores_comparator:
					if self.comparator == ClozeComparator.ignore_case:
						normalized = text.casefold()
				if normalized in given_answers:
					continue
				given_answers.add(normalized)

			score += self.gaps[index].get_score(text)

		return score


class SingleChoiceQuestion:
	@staticmethod
	def _get_ui(driver):
		choices = dict()

		while True:
			try:
				choice = driver.find_element_by_name("choice[answer][%d]" % len(choices))
			except NoSuchElementException:
				break
			points = driver.find_element_by_name("choice[points][%d]" % len(choices))
			choices[choice.get_attribute("value")] = Decimal(points.get_attribute("value"))

		return choices

	@staticmethod
	def _set_ui(driver, choices):
		i = 0
		while True:
			try:
				choice = driver.find_element_by_name("choice[answer][%d]" % i)
			except NoSuchElementException:
				break
			points = driver.find_element_by_name("choice[points][%d]" % i)
			set_element_value(driver, points, str(choices[choice.get_attribute("value")]))
			i += 1

	def __init__(self, driver, title):
		self.title = title
		self.choices = self._get_ui(driver)

	def initialize_coverage(self, coverage, context):
		for choice in self.choices.keys():
			coverage.add_case(self, "verify", choice)
			coverage.add_case(self, "export", choice)

	def add_export_coverage(self, coverage, answers):
		for choice, checked in answers.items():
			if checked != 0:
				coverage.case_occurred(self, "export", str(choice))
				break

	def get_random_answer(self, context):
		choice = random.choice(list(self.choices.keys()))
		return choice, self.choices[choice]

	def readjust_scores(self, driver, report):
		report("checking readjustment for %s." % self.title)
		choices = self._get_ui(driver)

		if len(choices) != len(self.choices):
			raise Exception("wrong number of choices in readjustment.")
		for key, score in self.choices.items():
			if choices[key] != score:
				raise Exception("wrong choice score in readjustment.")

		for key, score in list(choices.items()):
			new_score = readjust_score(score)
			choices[key] = new_score
			report('readjusted score for "%s / %s" from %s to %s.' % (self.title, key, score, new_score))

		self._set_ui(driver, choices)
		self.choices = choices

	def compute_score(self, answers, context):
		score = Decimal(0)
		for label, checked in answers.items():
			if checked:
				score += self.choices[label]
		return score



MultipleChoiceItem = namedtuple('MultipleChoiceItem', ['checked_score', 'unchecked_score'])


class MultipleChoiceQuestion:
	def __init__(self, driver, title):
		self.title = title
		self.choices = dict()

		while True:
			try:
				choice = driver.find_element_by_name("choice[answer][%d]" % len(self.choices))
			except NoSuchElementException:
				break

			points = driver.find_element_by_name("choice[points][%d]" % len(self.choices))
			points_unchecked = driver.find_element_by_name("choice[points_unchecked][%d]" % len(self.choices))

			self.choices[choice.get_attribute("value")] = MultipleChoiceItem(
				checked_score=Decimal(points.get_attribute("value")),
				unchecked_score=Decimal(points_unchecked.get_attribute("value")))

	def initialize_coverage(self, coverage, context):
		if True:  # all cases
			elements = [(False, True)] * len(self.choices)
			for combination in itertools.product(*elements):
				if context.workarounds.disallow_empty_answers or any(combination):
					solution = dict()
					for checked, label in zip(combination, self.choices.keys()):
						solution[label] = 1 if checked else 0
					coverage.add_case(self, "verify", json.dumps(solution))
					coverage.add_case(self, "export", json.dumps(solution))

		else:  # only some border cases
			best_solution = dict()
			worst_solution = dict()
			for label, choice in self.choices.items():
				best_solution[label] = choice.checked_score > choice.unchecked_score
				worst_solution[label] = not best_solution[label]

			if context.workarounds.disallow_empty_answers or any(best_solution.values()):
				coverage.add_case(self, "verify", best_solution)
				coverage.add_case(self, "export", best_solution)

			if context.workarounds.disallow_empty_answers or any(worst_solution.values()):
				coverage.add_case(self, "verify", worst_solution)
				coverage.add_case(self, "export", worst_solution)

			for i in len(self.choices):
				minimal_good_solution = dict()
				for j, (label, choice) in enumerate(self.choices.items()):
					pick = choice.checked_score > choice.unchecked_score
					pick = pick if i == j else not pick
					minimal_good_solution[label] = pick
				coverage.add_case(self, "verify", minimal_good_solution)
				coverage.add_case(self, "export", minimal_good_solution)

	def add_export_coverage(self, coverage, answers):
		coverage.case_occurred(self, "export", json.dumps(answers))

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

		return answers, self.compute_score(answers, context)

	def readjust_scores(self, driver, report):
		pass

	def compute_score(self, answers, context):
		score = Decimal(0)
		for label, checked in answers.items():
			item = self.choices[label]
			if checked:
				score += item.checked_score
			else:
				score += item.unchecked_score
		return score


class KPrimQuestion:
	def __init__(self, driver, title):
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

	def initialize_coverage(self, coverage, context):
		elements = [(False, True)] * len(self.names)
		for combination in itertools.product(*elements):
			if context.workarounds.disallow_empty_answers or any(combination):
				solution = dict()
				for checked, label in zip(combination, self.names):
					solution[label] = 1 if checked else 0
				coverage.add_case(self, "verify", json.dumps(solution))
				coverage.add_case(self, "export", json.dumps(solution))

	def add_export_coverage(self, coverage, answers):
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
		answers = [random.random() < 0.5 for _ in range(4)]
		return answers, self.compute_score_by_indices(answers)

	def readjust_scores(self, driver, report):
		pass


class LongTextQuestion:
	def __init__(self, driver, title):
		self.title = title
		self.length = 20

		if not driver.find_element_by_id("scoring_mode_non").is_selected():
			raise Exception("only manual scoring is supported for tests with LongTextQuestion")

	def initialize_coverage(self, coverage, context):
		for args in coverage.text_cases(self.length, context):
			coverage.add_case(self, "verify", *args)
			coverage.add_case(self, "export", *args)

	def add_verify_coverage(self, coverage, answers):
		for text in answers.values():
			for args in coverage.text_cases_occurred(text):
				coverage.case_occurred(self, "verify", *args)

	def add_export_coverage(self, coverage, answers):
		for text in answers.values():
			for args in coverage.text_cases_occurred(text):
				coverage.case_occurred(self, "export", *args)

	def get_random_answer(self, context):
		while True:
			n = random.randint(0, self.length)
			text = context.produce_text(n, context.long_text_random_chars)

			if not context.workarounds.disallow_empty_answers:
				break

			# ASSUMPTION: ILIAS does not support empty answers, since they will end up with
			# a None score in the XLS
			if len(text.strip()) >= 1:
				break
		return text, self.compute_score(text, context)

	def readjust_scores(self, driver, report):
		pass

	def compute_score(self, text, context):
		return Decimal(0)