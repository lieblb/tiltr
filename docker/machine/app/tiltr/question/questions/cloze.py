#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import time
import traceback
import html
from enum import Enum
from decimal import *
from collections import defaultdict, namedtuple

from selenium.common.exceptions import NoSuchElementException, ElementNotVisibleException
from selenium.webdriver.support.select import Select
from texttable import Texttable

from .question import Question
from ...data.exceptions import *
from tiltr.driver.utils import set_element_value, wait_for_page_load

ClozeScoring = namedtuple('ClozeScoring', ['identical_scoring', 'comparator', 'gaps'])

TextualGapScoring = namedtuple(
	'TextualGapScoring', ['cloze_type', 'size', 'options'])
NumericGapScoring = namedtuple(
	'NumericGapScoring', ['cloze_type', 'value', 'lower', 'upper', 'score'])


def _create_gaps(scoring):
	constructors = dict((
		(ClozeType.text, ClozeQuestionTextGap),
		(ClozeType.select, ClozeQuestionSelectGap),
		(ClozeType.numeric, ClozeQuestionNumericGap)))

	gaps = dict()
	for gap_index, gap_scoring in enumerate(scoring.gaps):
		construct_gap = constructors[gap_scoring.cloze_type]
		gap = construct_gap(scoring, gap_index)
		gaps[gap_index] = gap

	return gaps


def _max_entry_size(size, context):
	# get the maximum number of characters we write into this gap. note that
	# this might be != the real maximum size, which might be unlimited, so we
	# choose some configured maximum number for entry purposes.
	if size is not None:
		return size
	else:
		return int(context.settings.max_cloze_text_length)


def _modify_answer(text, context, max_len=None):
	max_len = _max_entry_size(max_len, context)

	mode = context.random.choices(
		("unmodified", "randchar", "randcase", "randperm", "randfull"),
		weights=(0.5, 0.2, 0.1, 0.1, 0.1))[0]

	if mode == "unmodified":
		# keep exactly as specified.
		return text
	elif mode == "randperm":
		text = ''.join(context.random.sample(text, len(text)))
		return text
	elif mode == "randfull":
		return context.produce_text(max_len, context.cloze_random_chars)
	else:
		# modify case or content.
		chars = []
		for i in range(len(text)):
			r = context.random.random()
			if mode == "randchar" and r < 0.2:
				chars.append(context.random.choice(context.cloze_random_chars))
			elif mode == "randcase" and r < 0.2:
				chars.append(text[i].swapcase())
			else:
				chars.append(text[i])
		text = "".join(chars)
		return text


def _readjust_score(random, score, boost):
	if random.randint(1, 10) == 5:
		return Decimal(0)
	else:
		return Decimal(random.randint(1, 3 * 4)) / Decimal(4)

def _count_answers(scoring, actual_answers, answer_counts):
	if scoring.cloze_type != ClozeType.numeric:
		for x in [s.strip() for s in actual_answers if s.strip()]:
			answer_counts[x] += 1

def _readjust(context, scoring, gap, actual_answers, answer_counts):
	random = context.random

	if scoring.cloze_type == ClozeType.numeric:
		new_score = Decimal(0)
		i = 0

		while new_score <= Decimal(0):
			new_score = _readjust_score(random, scoring.score, i)
			i += 1

		return scoring._replace(
			score=new_score)

	else:  # text and select gaps

		# if two variants with different border spaces exist, only choose the stripped
		# variant, since we won't be able to differentiate the two in the readjustment
		# UI later on. that means "a" and "a " are both "a" for us.
		actual_answers = set([s.strip() for s in actual_answers if s.strip()])

		if context.workarounds.workaround_identical_cloze_answers_in_readjustment:
			actual_answers = set(x for x in actual_answers if answer_counts[x] <= 1)

		unscored_answers = set(actual_answers) - set(gap.get_scored_options().keys())

		new_options = dict()
		for k, v in scoring.options.items():
			new_options[k] = v
		just_added = set()

		# add new answers
		n_answers_to_add = random.randint(0, min(max(2, len(unscored_answers)), 10))

		if context.ilias_version >= (5, 4):
			if scoring.cloze_type == ClozeType.text:
				for _ in range(min(n_answers_to_add, len(unscored_answers))):
					new_answer = context.random.choice(list(unscored_answers))
					unscored_answers.remove(new_answer)
					assert new_answer not in new_options
					new_options[new_answer] = Decimal(random.randint(1, 8)) / Decimal(4)
					just_added.add(new_answer)
			else:
				pass  # cannot add new answers for "select" or "numeric" gaps
		else:  # ILIAS < 5.4
			for _ in range(n_answers_to_add):
				while True:
					if scoring.cloze_type == ClozeType.text and len(unscored_answers) > 0 and random.randint(1, 10) > 1:
						new_answer = context.random.choice(list(unscored_answers))
						unscored_answers.remove(new_answer)
					else:
						new_answer, ignored_score = gap.get_random_choice(context)

						if scoring.cloze_type == ClozeType.select:
							new_answer = _modify_answer(new_answer, context)

						new_answer = new_answer.strip()
						new_answer = new_answer.replace('\t', '')

					if len(new_answer) > 0 and new_answer not in new_options:
						new_options[new_answer] = Decimal(random.randint(1, 8)) / Decimal(4)
						just_added.add(new_answer)
						break

		i = 0
		while True:
			readjusted_options = dict()

			for k, score in new_options.items():
				if k in just_added:
					readjusted_options[k] = score
				else:
					readjusted_options[k] = _readjust_score(random, score, i)

			if context.ilias_version >= (5, 4):
				# no remove support at the moment FIXME
				if all(score > Decimal(0) for score in readjusted_options.values()):
					break
			else:
				if any(score > Decimal(0) for score in readjusted_options.values()):
					break

			i += 1

		return scoring._replace(options=readjusted_options)


class ClozeType(Enum):
	text = 0
	select = 1
	numeric = 2


class ClozeComparator(Enum):
	ignore_case = "ci"
	case_sensitive = "cs"


class ClozeQuestionGap:
	_export_names = dict(de="Lücke", en="Gap")

	def __init__(self, index):
		self.index = index

	def get_maximum_score(self):
		raise NotImplementedError()

	def get_export_name(self, language):
		return ClozeQuestionGap._export_names[language] + " " + str(self.index + 1)

	def is_valid_answer(self, value):
		raise NotImplementedError()


class ClozeQuestionTextGap(ClozeQuestionGap):
	def __init__(self, scoring, index):
		ClozeQuestionGap.__init__(self, index)
		self.comparator = scoring.comparator
		gap_scoring = scoring.gaps[index]
		self.options = gap_scoring.options
		self.size = gap_scoring.size  # maximum size

	def get_maximum_score(self):
		return max(self.options.values())

	def _get_maximum_entry_size(self, context):
		return _max_entry_size(self.size, context)

	def initialize_coverage(self, question, coverage, context):
		size = self._get_maximum_entry_size(context)
		for mode in ("verify", "export"):
			for args in coverage.text_cases(size, context):
				coverage.add_case(question, self.index, mode, *args)
			for solution in self.options.keys():
				coverage.add_case(question, self.index, mode, "solution", solution)

	def add_coverage(self, question, channel, coverage, value):
		value = str(value)
		for args in coverage.text_cases_occurred(value):
			coverage.case_occurred(question, self.index, channel, *args)
		if value in self.options:
			coverage.case_occurred(question, self.index, channel, "solution", value)

	def _modify_answer(self, text, context):
		text = _modify_answer(text, context, self.size)
		return text, self.get_score(text)

	def get_random_choice(self, context):
		if context.random.random() < float(context.settings.cloze_text_enter_scored_p) and not context.prefer_text():
			# pick scored answer.
			text, _ = context.random.choice(list(self.options.items()))
			return self._modify_answer(text, context)
		else:
			# make up something random and probably wrong.
			if context.random.random() < float(context.settings.cloze_text_enter_random_number_p):
				# insert a random number. this is useful to test
				# workarounds.implicit_text_number_conversions.
				num_digits = context.random.randint(0, 2)
				format = (".%d" % num_digits) + "%f"
				text = format % (context.random.random() * 1000)
			else:
				# produce some random test.
				entry_size = self._get_maximum_entry_size(context)
				text = context.produce_text(
					entry_size, context.cloze_random_chars)
			return text, self.get_score(text)

	def get_score(self, text):
		if self.comparator == ClozeComparator.case_sensitive:
			return self.options.get(text, Decimal(0))

		assert self.comparator == ClozeComparator.ignore_case
		best_score = Decimal(0)
		for option, score in self.options.items():
			if option.casefold() == text.casefold():
				best_score = max(best_score, score)

		return best_score

	def get_scored_options(self):
		return self.options

	def is_valid_answer(self, value):
		if self.size is None:  # no restriction?
			return True
		else:
			return len(value) <= self.size

	def get_type(self):
		return ClozeType.text


class ClozeQuestionSelectGap(ClozeQuestionGap):
	def __init__(self, scoring, index):
		ClozeQuestionGap.__init__(self, index)
		self.options = scoring.gaps[index].options

	def get_maximum_score(self):
		return max(self.options.values())

	def initialize_coverage(self, question, coverage, context):
		for value in self.options.keys():
			for mode in ("verify", "export"):
				coverage.add_case(question, self.index, mode, value)

	def add_coverage(self, question, channel, coverage, value):
		value = str(value)
		coverage.case_occurred(question, self.index, channel, value)

	def get_random_choice(self, context):
		return context.random.choice(list(self.options.items()))

	def get_score(self, text):
		return self.options.get(text, Decimal(0))

	def get_scored_options(self):
		return self.options

	def is_valid_answer(self, value):
		return value in self.options

	def get_type(self):
		return ClozeType.select


class ClozeQuestionNumericGap(ClozeQuestionGap):
	def __init__(self, scoring, index):
		ClozeQuestionGap.__init__(self, index)

		gap_scoring = scoring.gaps[index]

		self.numeric_value = gap_scoring.value
		self.numeric_lower = gap_scoring.lower
		self.numeric_upper = gap_scoring.upper
		self.score = gap_scoring.score

		# ILIAS will limit exports to XLS to 16 significant decimals, which makes sense.
		# e.g. 25.433019319138662 -> 25.43301931913866, 0.17493771424585164 -> 0.1749377142458516
		self.format = '%.16g'

	def get_maximum_score(self):
		return self.score

	def initialize_coverage(self, question, coverage, context):
		for mode in ("verify", "export"):
			coverage.add_case(question, self.index, mode, str(self.numeric_value))
			coverage.add_case(question, self.index, mode, str(self.numeric_lower))
			coverage.add_case(question, self.index, mode, str(self.numeric_upper))

	def add_coverage(self, question, channel, coverage, value):
		x = str(value)
		if x in [str(self.numeric_value), str(self.numeric_lower), str(self.numeric_upper)]:
			coverage.case_occurred(question, self.index, channel, x)

	def _get_random_inside(self, context):
		return context.random.uniform(float(self.numeric_lower), float(self.numeric_upper))

	def _get_random_outside(self, context):
		r = 14  # generate fake numbers up to this scale
		d = float(self.numeric_upper - self.numeric_lower)
		off = context.random.uniform(10 ** -r, (10 ** r) * d)

		return context.random.choice((
			float(self.numeric_lower) - off,
			float(self.numeric_upper) + off
		))

	def get_random_choice(self, context):
		s = None

		if not context.workarounds.disallow_invalid_answers:
			if context.random.random() < float(context.settings.invalid_answer_p):
				s = context.produce_text(20, context.cloze_random_chars, allow_numbers=False)

		if s is None:
			g = context.random.choice((
				lambda _: float(self.numeric_lower),
				lambda _: float(self.numeric_upper),
				self._get_random_inside,
				self._get_random_outside
			))

			n = g(context)
			s = self.format % n

		return s, self.get_score(s)

	def get_score(self, text):
		try:
			n = float(text)
			n = float(self.format % n)  # limit to number of representable digits

			if float(self.numeric_lower) <= n <= float(self.numeric_upper):
				return self.score
			else:
				return Decimal(0)
		except ValueError:
			return Decimal(0)

	def get_scored_options(self):
		return dict((self.numeric_value, self.score))

	def is_valid_answer(self, value):
		value = value.strip()
		if len(value) == 0:
			return True
		try:
			float(value)
			return True
		except ValueError:
			return False

	def get_type(self):
		return ClozeType.numeric


def parse_gap_size(driver, gap_index):
	element = driver.find_element_by_name("gap_%d_gapsize" % gap_index)
	text = element.get_attribute("value").strip()
	assert isinstance(text, str)
	if text == '':
		return None
	else:
		return int(text)


def parse_numeric_gap_scoring(driver, gap_index):
	value = Decimal(driver.find_element_by_name("gap_%d_numeric" % gap_index).get_attribute("value"))
	lower = Decimal(driver.find_element_by_name("gap_%d_numeric_lower" % gap_index).get_attribute("value"))
	upper = Decimal(driver.find_element_by_name("gap_%d_numeric_upper" % gap_index).get_attribute("value"))
	score = Decimal(driver.find_element_by_name("gap_%d_numeric_points" % gap_index).get_attribute("value"))
	return dict(value=value, lower=lower, upper=upper, score=score)


def parse_gap_options(driver, gap_index):
	options = dict()
	seen = set()

	while True:
		try:
			answer = driver.find_element_by_id("gap_%d[answer][%d]" % (gap_index, len(options)))
		except NoSuchElementException:
			break
		points = driver.find_element_by_id("gap_%d[points][%d]" % (gap_index, len(options)))

		answer_key = answer.get_attribute("value")

		if answer_key.strip() in seen:
			raise InteractionException("the gap has multiple identical options named '%s'. unsupported." % answer_key)
		seen.add(answer_key.strip())

		options[answer_key] = Decimal(points.get_attribute("value"))

	return options


class GapReadjuster:
	def __init__(self, driver, gap_index, gap, context):
		self.driver = driver
		self.gap_index = gap_index
		self.gap = gap
		self.context = context

	def initialize(self):  # happens on main tab
		pass

class NumericGapReadjuster(GapReadjuster):
	def extend_scores(self):
		pass

	def update_scores(self):
		set_element_value(
			self.driver,
			self.driver.find_element_by_name("gap_%d_numeric_points" % self.gap_index),
			str(self.gap.score))

	def update_gap(self, gap):
		return gap


class TextGapReadjuster(GapReadjuster):
	def initialize(self):  # happens on main tab
		self._old_keys = set(self._option_answers())

	def update_scores(self):
		# for some obscure reason, setting answers and scores via set_element_value() won't
		# work here. send_keys() works though.

		# set all scores (not yet set, i.e. not in keep_score).
		for option_index, option_answer in enumerate(self._option_answers()):
			#if option_answer not in keep_score:
			points = self.driver.find_element_by_id("gap_%d[points][%d]" % (self.gap_index, option_index))
			points.clear()
			try:
				points.send_keys(str(self.gap.options[option_answer]))
			except KeyError as e:
				raise InteractionException("failed to find %s in %s" % (option_answer, self.gap.options))

	def update_gap(self, gap):
		return gap


class TextGapReadjuster53(TextGapReadjuster):
	def _get_option_answer_element(self, option_index):
		return self.driver.find_element_by_id("gap_%d[answer][%d]" % (self.gap_index, option_index))

	def _option_answers(self):
		option_index = 0
		while True:
			try:
				element = self._get_option_answer_element(option_index)
				yield element.get_attribute("value").strip()
			except NoSuchElementException:
				break
			option_index += 1

	def _add_answer(self, option_index, option_key):
		self.driver.find_element_by_name("add_gap_%d_%d" % (self.gap_index, option_index - 1)).click()

		element = self._get_option_answer_element(option_index)
		element.send_keys(option_key)

		if element.get_attribute("value") != option_key:
			raise InteractionException(
				"gap option name mismatch: '%s' != '%s'" % (element.get_attribute("value"), option_key))

	def _add(self):
		new_keys = set(self.gap.options.keys())
		added_keys = new_keys - self._old_keys

		option_index = len(self._old_keys)
		for option_key in added_keys:
			self._add_answer(option_index, option_key)
			option_index += 1

	def _remove(self):
		keys = list(self._option_answers())
		new_keys = set(self.gap.options.keys())

		option_index = 0
		for option_key in keys:
			if len(option_key.strip()) == 0:
				raise InteractionException("illegal empty option name")

			if option_key not in new_keys:
				self.driver.find_element_by_name(
					"remove_gap_%d_%d" % (self.gap_index, option_index)).click()
			else:
				option_index += 1

	def extend_scores(self):
		self._add()
		self._remove()


class TextGapReadjuster54(TextGapReadjuster):
	def _option_answers(self):
		for tr in self.driver.find_elements_by_css_selector(
			"#il_prop_cont_gap_%d .answerwizard tbody tr" % self.gap_index):

			for td in tr.find_elements_by_css_selector("td"):
				yield td.text
				break

	def update_gap(self, gap):
		options = dict()

		for tr in self.driver.find_elements_by_css_selector(
			"#il_prop_cont_gap_%d .answerwizard tbody tr" % self.gap_index):

			tds = list(tr.find_elements_by_css_selector("td"))

			if self.context.workarounds.mantis_25329:
				answer_text = tds[0].get_attribute("innerHTML").strip()
			else:
				answer_text = tds[0].text.strip()

			score = tds[1].find_element_by_css_selector("input").get_attribute("value").strip()

			options[answer_text] = Decimal(score)

		return gap._replace(options=options)

	def extend_scores(self):
		driver = self.driver
		gap_index = self.gap_index
		options = self.gap.options
		# context = self.context

		new_keys = set(options.keys())
		added_keys = new_keys - self._old_keys
		keep_score = set()

		# add options.
		if added_keys:
			# gather answer statstics tables - they are not numbered
			# and all have the same id. hm.

			still_to_add = set(list(added_keys))

			def find_table():
				tables = list()
				for table in driver.find_elements_by_css_selector("#ilContentContainer table#tstAnswerStatistic"):
					tables.append(table)
					if len(tables) > gap_index:  # exit early
						break

				# pick the one table for our gap.
				return tables[gap_index]

			while still_to_add:
				# pick the one table for our gap (and guard against adding the correct answer text
				# to the wrong gap).

				corrections_table = find_table()

				# click next appropriate "add" button.
				answer_text = None
				found_add_button = False

				for tr in corrections_table.find_elements_by_css_selector("tbody tr"):
					tds = list(tr.find_elements_by_css_selector("td"))

					if self.context.workarounds.mantis_25329:
						answer_text = tds[0].get_attribute("innerHTML").strip()
					else:
						answer_text = tds[0].text.strip()

					if answer_text in still_to_add:
						tds[2].find_element_by_css_selector("a").click()  # clicks to add
						found_add_button = True
						break

				if not found_add_button:
					raise InteractionException("did not find add button for answers %s" % still_to_add)

				def wait(cond, desc, num_tries=7):
					for i in range(num_tries):
						if cond():
							return
						time.sleep(1)
					raise InteractionException("failed to wait for: %s" % desc)

				def is_modal_visible():
					return driver.execute_script('return $(".modal.fade.in .modal-content").length > 0;')

				def has_modal_error():
					return driver.execute_script('return $(".modal.fade.in .modal-content .alert-danger").length > 0;')

				wait(lambda: is_modal_visible(), "scoring popup show")

				assert options[answer_text] > Decimal(0)  # must be positive

				# scoring popup will show now. we need to enter a value and save.
				driver.execute_script('''
						(function(args) {
							var points = args[0];

							var modal_content = $(".modal.fade.in .modal-content");
							modal_content.find("input#points").val(points);

							modal_content.find('input[name="cmd[addAnswerAsynch]"]').click();
						}(arguments))
					''', str(options[answer_text]))


				wait(lambda: has_modal_error() or not is_modal_visible(), "scoring popup hide")

				if has_modal_error():
					raise InteractionException("scoring modal gave an unexpected error")

				still_to_add.remove(answer_text)
				keep_score.add(answer_text)


class ClozeQuestion(Question):
	@staticmethod
	def _get_ui(driver):
		fixed_text_length = driver.find_element_by_name("fixedTextLength").get_attribute("value").strip()
		if fixed_text_length == '':
			fixed_text_length = None
		else:
			fixed_text_length = int(fixed_text_length)

		gaps = list()

		while True:
			gap_index = len(gaps)

			try:
				cloze_type_element = driver.find_element_by_name("clozetype_%d" % gap_index)
			except NoSuchElementException:
				break

			cloze_type = ClozeType(int(cloze_type_element.get_attribute("value")))

			if cloze_type != ClozeType.select:
				gap_size = parse_gap_size(driver, gap_index)
				if gap_size is None:
					gap_size = fixed_text_length
			else:
				gap_size = None

			if cloze_type in (ClozeType.text, ClozeType.select):
				options = parse_gap_options(driver, gap_index)

				if not options:
					raise InteractionException("did not find gap options (%d)" % gap_index)

				scoring = TextualGapScoring(
					cloze_type=cloze_type, size=gap_size, options=options)

			elif cloze_type == ClozeType.numeric:
				scoring = NumericGapScoring(
					cloze_type=ClozeType.numeric,
					**parse_numeric_gap_scoring(driver, gap_index))

			else:
				raise NotImplementedException("unsupported cloze type " + str(cloze_type))

			gaps.append(scoring)

		identical_scoring = driver.find_element_by_name("identical_scoring").is_selected()

		comparator = ClozeComparator(driver.find_element_by_css_selector(
			"#textgap_rating option[selected]").get_attribute("value"))

		return ClozeScoring(
			identical_scoring=identical_scoring,
			comparator=comparator,
			gaps=gaps)

	@staticmethod
	def _create_readjusters(driver, scoring, context):
		readjusters = dict()
		for gap_index, gap in enumerate(scoring.gaps):
			if gap.cloze_type in (ClozeType.text, ClozeType.select):
				if context.ilias_version >= (5, 4):
					construct_readjuster = TextGapReadjuster54
				else:
					construct_readjuster = TextGapReadjuster53
			else:
				construct_readjuster = NumericGapReadjuster

			readjusters[gap_index] = construct_readjuster(
				driver, gap_index, gap, context)

			readjusters[gap_index].initialize()
		return readjusters

	@staticmethod
	def _update_from_readjustment_ui(driver, scoring, context):
		if context.ilias_version < (5, 4):
			return ClozeQuestion._get_ui(driver)
		else:
			with wait_for_page_load(driver):
				# go to readjustment scoring tab
				driver.find_element_by_id("tab_question").click()

			readjusters = ClozeQuestion._create_readjusters(
				driver, scoring, context)

			# update option texts we might have missed so far.
			gaps = []
			for gap_index, gap in enumerate(scoring.gaps):
				gaps.append(readjusters[gap_index].update_gap(gap))

			return scoring._replace(gaps=gaps)

	@staticmethod
	def _set_ui(driver, scoring, context):
		readjusters = ClozeQuestion._create_readjusters(driver, scoring, context)

		if context.ilias_version >= (5, 4):
			with wait_for_page_load(driver):
				# go to readjustment statistics ("given answers") tab
				driver.find_element_by_id("tab_answers").click()

		# add new scored answers.
		for gap_index, gap in enumerate(scoring.gaps):
			readjusters[gap_index].extend_scores()

		if context.ilias_version >= (5, 4):
			with wait_for_page_load(driver):
				# go to readjustment scoring tab
				driver.find_element_by_id("tab_question").click()

		# we're now on the main tab (scoring tab) and stay there. this is important as
		# the save only happens in our caller and we would lose all data if we switched
		# to another tab without saving.

		if context.ilias_version < (5, 4):
			identical_scoring_checkbox = driver.find_element_by_name("identical_scoring")
			if identical_scoring_checkbox.is_selected() != scoring.identical_scoring:
				identical_scoring_checkbox.click()

			Select(driver.find_element_by_id("textgap_rating")).select_by_value(
				scoring.comparator.value)

		# update scores.
		for gap_index, gap in enumerate(scoring.gaps):
			readjusters[gap_index].update_scores()

	def _create_gaps(self):
		self.gaps = _create_gaps(self.scoring)

	def __init__(self, driver, title, settings):
		super().__init__(title)

		self.scoring = self._get_ui(driver)
		self._create_gaps()

	def get_maximum_score(self, context):
		return sum([gap.get_maximum_score() for gap in self.gaps.values()])

	def create_answer(self, driver, *args):
		from ..answers.cloze import ClozeAnswer
		return ClozeAnswer(driver, self, *args)

	def initialize_coverage(self, coverage, context):
		for gap in self.gaps.values():
			gap.initialize_coverage(self, coverage, context)

	def add_export_coverage(self, coverage, answers, language):
		gaps = dict()
		for gap in self.gaps.values():
			gaps[gap.get_export_name(language)] = self.gaps[gap.index]
		for gap_name, value in answers.items():
			gaps[gap_name].add_coverage(self, "export", coverage, str(value))

	def get_gap_definition(self, index):
		return self.gap[index]

	def _get_normalized(self, s):
		if self.scoring.comparator == ClozeComparator.case_sensitive:
			return s
		else:
			assert self.scoring.comparator == ClozeComparator.ignore_case
			return s.casefold()

	def _is_empty_answer(self, answer, context):
		answer = context.strip_whitespace(answer)
		return len(answer) == 0

	def get_random_answer(self, context):
		while True:
			answers = dict()
			valid = dict()

			previous_answers = defaultdict(set)
			previous_answers_p = float(context.settings.cloze_previous_answer_p)
			all_empty = True

			shuffled_gaps = list(self.gaps.values())
			context.random.shuffle(shuffled_gaps)  # randomize our "previous" value logic

			for gap in shuffled_gaps:
				previous = previous_answers[gap.get_type()]
				choice = None

				if len(previous) > 0 and context.random.random() < previous_answers_p:
					# use some previous answer to explicitly test identical_scoring
					# option, though it's also tested through the case below.
					choice = context.random.choice(list(previous))

					# trying to set a select gap to some illegal value causes problems.
					if not gap.is_valid_answer(choice):
						choice = None

				if choice is None:
					choice, _ = gap.get_random_choice(context)

				previous.add(choice)

				answers[gap.index] = choice
				valid[gap.index] = gap.is_valid_answer(choice)
				all_empty = all_empty and self._is_empty_answer(choice, context)

			if all_empty and context.workarounds.disallow_empty_answers:
				pass  # retry
			else:
				return answers, valid, self.compute_score_by_indices(answers, context)

	def readjust_scores(self, driver, actual_answers, context, report):
		def random_flip_scoring(f):
			if context.ilias_version >= (5, 4):
				return f  # never flip
			if context.random.randint(0, 3) == 0:  # flip?
				return not f
			else:
				return f

		def random_flip_comparator(c):
			if context.ilias_version >= (5, 4):
				return c  # never flip
			if context.random.randint(0, 3) == 0:  # flip?
				return context.random.choice([x for x in ClozeComparator if x != c])
			else:
				return c

		old_scoring = self._update_from_readjustment_ui(driver, self.scoring, context)

		actual_answers_by_index = dict()
		for i in range(len(self.scoring.gaps)):
			answer_key = (self.gaps[i].get_export_name(context.language),)
			assert answer_key in actual_answers
			actual_answers_by_index[i] = actual_answers[answer_key]

		answer_counts = defaultdict(int)
		for i, s in enumerate(self.scoring.gaps):
			_count_answers(s, actual_answers_by_index[i], answer_counts)

		self.scoring = ClozeScoring(
			identical_scoring=random_flip_scoring(self.scoring.identical_scoring),
			comparator=random_flip_comparator(self.scoring.comparator),
			gaps=[_readjust(context, s, self.gaps[i], actual_answers_by_index[i], answer_counts)
				  for i, s in enumerate(self.scoring.gaps)])
		self._create_gaps()
		self._set_ui(driver, self.scoring, context)

		table = Texttable()
		table.set_deco(Texttable.HEADER)
		table.set_cols_dtype(['t', 'a', 'a'])
		table.add_row(['', 'old', 'readjusted'])

		table.add_row([
			'identical_scoring',
			old_scoring.identical_scoring,
			self.scoring.identical_scoring])

		table.add_row([
			'comparator',
			old_scoring.comparator.name,
			self.scoring.comparator.name])

		for i, (old_gap, new_gap) in enumerate(zip(old_scoring.gaps, self.scoring.gaps)):
			table.add_row(["", "", ""])
			table.add_row(["gap %d" % (1 + i), "", ""])

			assert old_gap.cloze_type == new_gap.cloze_type
			if old_gap.cloze_type == ClozeType.numeric:
				for key in ('value', 'lower', 'upper', 'score'):
					table.add_row([
						key,
						getattr(old_gap, key),
						getattr(new_gap, key)])
			else:
				table.add_row([
					'size',
					old_gap.size or "no limit",
					new_gap.size or "no limit"])

				for key in set(old_gap.options.keys()) | set(new_gap.options.keys()):
					table.add_row([
						key,
						old_gap.options.get(key, "n/a"),
						new_gap.options.get(key, "n/a")])

		report(table)

		return True, list()

	def compute_score(self, answers, context):
		# normalize answers: "a " will score the same as "a".
		answers = dict((k, v.strip()) for k, v in answers.items())

		name_to_index = dict()
		for gap in self.gaps.values():
			name_to_index[gap.get_export_name(context.language)] = gap.index

		indexed_answers = dict()
		for name, value in answers.items():
			indexed_answers[name_to_index[name]] = value

		return self.compute_score_by_indices(indexed_answers, context)

	def compute_score_by_indices(self, answers, context):
		score = Decimal(0)

		if self.scoring.identical_scoring:
			for index, text in answers.items():
				score += self.gaps[index].get_score(text)
		else:
			# make sure answers are sorted as self.identical_scoring won't be
			# computed correctly otherwise.
			sorted_answers = sorted(list(answers.items()), key=lambda x: int(x[0]))

			given_answers = set()
			for index, text in sorted_answers:
				comparable_text = text

				if not context.workarounds.identical_scoring_ignores_comparator:
					if self.scoring.comparator == ClozeComparator.ignore_case:
						comparable_text = text.casefold()
				if comparable_text in given_answers:
					continue
				given_answers.add(comparable_text)

				score += self.gaps[index].get_score(text)

		return score
