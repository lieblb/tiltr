#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import json


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

	def get_catalog(self):
		return [dict(key=o[0], description=o[1], value=getattr(self, o[0])) for o in self.options]

	def to_dict(self):
		return dict((o[0], getattr(self, o[0])) for o in self.options)

	def print_status(self, report):
		for key in self.keys:
			report("  %s = %s" % (key, getattr(self, key)))


class Settings(ValueBag):
	def __init__(self, **kwargs):
		super().__init__([
			(
				"crash_frequency",
			 	"frequency of simulated crashes of question navigations (in percent).",
			 	1
			),
			(
				"autosave_duration",
			 	"configured autosave time.",
			 	5
			),
			(
				"autosave_tolerance",
			 	"additional time to give autosave until crashing is considered safe.",
			 	10
			),
			(
				"num_readjustments",
				"number of readjustment tests after each exam (very patchy).",
				0
			),
			(
				"modify_answer_frequency",
				"frequency of changing already given answers (in percent).",
				50
			)
		], **kwargs)


class Workarounds(ValueBag):
	def __init__(self, **kwargs):
		super().__init__([
			(
				"sloppy_whitespace",
				"whitespace is not always correctly preserved when saving answers."
			),
			(
				"implicit_text_number_conversions",
				"cloze texts in xls are converted into numbers, e.g. \".17\" becomes \"0,17\"."
			),
			(
				# see https://github.com/ILIAS-eLearning/ILIAS/pull/1082.
				"disallow_clamps_in_cloze",
				"<, > cause problems in cloze questions, e.g. \"3<Q>2<i\" becomes \"32\"."
			),
			(
				# see https://www.ilias.de/mantis/view.php?id=23143.
				"disallow_dollar_in_cloze",
				"$ cause problems in cloze questions, e.g. \"cv$1a\" becomes \"cva\"."
			),
			(
				"disallow_empty_answers",
				"empty questions' scores in Excel are blank instead "
				"of stating a number like 0 or the computed score (which might be > 0)."
			),
			(
				# see https://github.com/ILIAS-eLearning/ILIAS/pull/1052/
				"random_xls_participant_sheet_orders",
				"answer order for each xls participant sheet is random (and not normalized)."
			),
			(
				# see https://www.ilias.de/mantis/view.php?id=18720
				"force_tinymce",
				"various encoding and decoding problems in non-TinyMCE mode"
			),
			(
				# see https://github.com/ILIAS-eLearning/ILIAS/pull/1094
				"no_plaintext_longtext",
				"text in XLS export won't be plaintext due to TinyMCE escaping."
			),
			(
				"identical_scoring_ignores_comparator",
				"identical scoring option in cloze texts ignores comparation settings."
			),
			(
				"enable_autosave",
				"only test with enabled autosave, as simulated crashes will irretrievably lose data otherwise."
			)
		], **kwargs)


	def strip_whitespace(self, value):
		if isinstance(value, str):
			if self.sloppy_whitespace:
				value = value.strip()
		return value
