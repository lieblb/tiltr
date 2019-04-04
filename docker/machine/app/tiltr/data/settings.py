#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from .implicit import implicit_text_to_number_xls
from texttable import Texttable


class ValueBag:
	def __init__(self, options, from_dict=None):
		self.options = options

		self.keys = [option[0] for option in self.options]

		if from_dict:
			for key in self.keys:
				setattr(self, key, from_dict[key])
		else:
			for option in self.options:
				setattr(self, option[0], option[2] if len(option) > 2 else True)

	def get_catalog(self, exclude=None):
		if exclude is None:
			exclude = set()
		return [dict(
			key=o[0],
			description=o[1],
			value=getattr(self, o[0])) for o in self.options if o[0] not in exclude]

	def to_dict(self):
		return dict((o[0], getattr(self, o[0])) for o in self.options)

	def print_status(self, report):
		table = Texttable()
		table.set_deco(Texttable.HEADER)
		table.set_cols_dtype(['t', 'a'])

		for key in self.keys:
			table.add_row([key, getattr(self, key)])

		for line in table.draw().split('\n'):
			report(line)


class Settings(ValueBag):
	def __init__(self, **kwargs):
		super().__init__([
			(
				'browser',
				"""Browser to use for testing. Must be "firefox" or "chrome".""",
				'firefox'
			),
			(
				'resolution',
				"""Pixel resolution of virtual browser windows.""",
				"1024x1600"
			),
			(
				'num_deterministic_machines',
				"""Number of deterministic/regression test machines - these always do the same things.""",
				1
			),
			(
				"crash_frequency",
				"""Make the automation simulate a complete crash of the client browser with the given
				percentage of question navigation operations.""",
				1
			),
			(
				"autosave_duration",
				"""Make autosave happen every n seconds.""",
				5
			),
			(
				"autosave_tolerance",
				"""Additional time to wait after editing a question until crashing is considered safe.""",
				10
			),
			(
				"num_readjustments",
				"""Number of readjustment rounds after each exam (only some question types).""",
				1
			),
			(
				"modify_answer_frequency",
				"""Change already given answers this often on revisiting them (in percent).""",
				50
			),
			(
				"self_test_fake_error_level",
				"""Generate fake errors of the specified error level for a simple self tests.
				Use this to check that the current implementation correctly reports thrown exceptions.""",
				0
			),
			(
				'cloze_previous_answer_p',
				"""Probability with which to use previous answers in cloze questions.""",
				0.2
			),
			(
				'cloze_text_enter_scored_p',
				"""Probability with which to enter a scored answer in open text cloze gaps.""",
				0.75
			),
			(
				'cloze_text_enter_random_number_p',
				"""Probability with which to enter a random number instead of random text into a text cloze gap.""",
				0.1
			),
			(
				'invalid_answer_p',
				"""Probability of giving an invalid answer (e.g. text in numeric gap).""",
				0.25
			),
			(
				'test_passes',
				"""Passes to use during test. A = answer, V = verify, R = random verify/answer.""",
				'AVR'
			),
			(
				'max_long_text_length',
				"""Maximum number of characters to enter into long text questions.""",
				20
			),
			(
				'max_cloze_text_length',
				"""Maximum number of characters to enter into cloze text gaps.""",
				7
			),
			(
				'screenshot_refresh_time',
				"""Number of seconds after which to refresh browser screenshots.""",
				10
			),
			(
				'numbers_in_text_fields_p',
				"""Probability of entering numeric values in text fields.""",
				0.05
			)
		], **kwargs)


class Workarounds(ValueBag):
	_solved = dict(
		disallow_clamps_in_cloze=(5, 3, 12),  # see https://github.com/ILIAS-eLearning/ILIAS/pull/1082
		disallow_invalid_answers=(5, 3, 12),  # https://www.ilias.de/mantis/view.php?id=23432
		dont_readjust_matching=(5, 3, 0),
	)

	@staticmethod
	def get_solved(ilias_version_tuple):
		if ilias_version_tuple is None:
			return set()
		else:
			return set(k for k, version in Workarounds._solved.items() if ilias_version_tuple >= version)

	@staticmethod
	def disable_solved(d, ilias_version_tuple):
		for key in Workarounds.get_solved(ilias_version_tuple):
			d[key] = False

	def __init__(self, **kwargs):
		super().__init__([
			(
				# e.g. " abc" might become "abc"
				"sloppy_whitespace",
				"W01 Ignore whitespace inaccuracies in answers."
			),
			(
				# e.g. allow ".17" to become "0.17"
				"implicit_text_number_conversions",
				"W02 Allow cloze texts to be reformatted as numbers in the XLS export."
			),
			(
				# e.g. "3<Q>2<i" becomes "32"
				# see https://github.com/ILIAS-eLearning/ILIAS/pull/1082.
				"disallow_clamps_in_cloze",
				"""W03 Do not use <, > in cloze questions."""
			),
			(
				# e.g. "cv$1a" becomes "cva"
				# see https://www.ilias.de/mantis/view.php?id=23143.
				"disallow_dollar_in_cloze",
				"""W04 Do not use $ in cloze questions. MANTIS 25136"""
			),
			(
				#  work around a missing numeric value like 0 or the computed score (which might be > 0)
				"disallow_empty_answers",
				"W05 Never give empty answers, as empty questions' scores in XLS exports are blank."
			),
			(
				# see https://github.com/ILIAS-eLearning/ILIAS/pull/1052/
				"random_xls_participant_sheet_orders",
				"W06 Do not check for a defined participant order in the XLS export, as it is currently random."
			),
			(
				# see https://www.ilias.de/mantis/view.php?id=18720
				"force_tinymce",
				"W07 Force TinyMCE to work around encoding and decoding problems in non-TinyMCE mode. MANTIS 18720"
			),
			(
				# see https://github.com/ILIAS-eLearning/ILIAS/pull/1094
				# work around plaintext in the XLS export undergoing HTML escapes due to TinyMCE escaping
				"no_plaintext_longtext",
				"""W08 Allow the plaintext answer "a < b" to show up as "a &lt; b" in the XLS export."""
			),
			(
				"identical_scoring_ignores_comparator",
				"W09 Allow the identical scoring option in cloze texts to ignore comparation settings."
			),
			(
				# see https://www.ilias.de/mantis/view.php?id=23432
				# works around problems with the error reporting of the current form submit mechanism.
				"disallow_invalid_answers",
				"W10 Do not enter text in number cloze gaps. MANTIS 23432"
			),
			(
				# simulated crash will provoke data loss without this.
				"enable_autosave",
				"W11 Inhibit tests without enabled autosave."
			),
			(
				# workaround illegal_empty_score
				"allow_empty_scores",
				"W12 Read empty fields in XLS export as a numeric 0."
			),
			(
				# https://mantis.ilias.de/view.php?id=25105 and other problems
				# kprim readjustment errors
				"dont_readjust_kprim",
				"W13 Do not perform readjustments on KPrim questions. MANTIS 25105"
			),
			(
				# https://mantis.ilias.de/view.php?id=25136
				# maximum score of matching questions is wrong after readjustment
				"dont_readjust_matching",
				"W14 Do not perform readjustments on matching questions. MANTIS 25136"
			),
			(
				# https://mantis.ilias.de/view.php?id=25204
				# do not remove scoring pairs from matching question in readjustment
				"no_remove_on_readjust_matching",
				"W15 Do not remove scoring rules on matching question readjustments. MANTIS 25204"
			),
			(
				# https://mantis.ilias.de/view.php?id=25212
				"allow_unreachable_max_scores",
				"W16 Allow maximum scores that are too high and cannot be achieved. MANTIS 25212"
			)
		], **kwargs)


	def strip_whitespace(self, value):
		if isinstance(value, str) and self.sloppy_whitespace:
			value = value.strip()
		return value

	def normalize(self, value):
		return implicit_text_to_number_xls(self.strip_whitespace(value))
