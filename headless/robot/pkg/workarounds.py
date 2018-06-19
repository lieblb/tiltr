#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import json
import re


class Workarounds:
	def __init__(self, from_json=None):
		self.options = [
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
			)
		]

		self.keys = [option[0] for option in self.options]

		if from_json:
			for key in self.keys:
				setattr(self, key, from_json[key])
		else:
			for key in self.keys:
				setattr(self, key, True)

	def to_json(self):
		return json.dumps([dict(key=o[0], description=o[1], value=getattr(self, o[0])) for o in self.options])

	def print_status(self, report):
		for key in self.keys:
			report("  %s = %s" % (key, getattr(self, key)))

	def strip_whitespace(self, value):
		if isinstance(value, str):
			if self.sloppy_whitespace:
				value = value.strip()
		return value
