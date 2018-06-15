#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import json


class Workarounds:
	def __init__(self, from_json=None):
		self.options = [
			(
				"sloppy_whitespace",
				"ILIAS currently strips various whitespaces when saving answers."
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
				"ILIAS currently does not deal correctly with empty questions (scores in Excel are just blank instead "
				"of stating a number like 0 or the computed score, which might be != 0)."
			),
			(
				# see https://github.com/ILIAS-eLearning/ILIAS/pull/1052/
				"random_xls_participant_sheet_orders",
				"order of ILIAS participant sheet answers in XLS export normalized, i.e. same for each participant."
			),
			(
				# see https://www.ilias.de/mantis/view.php?id=18720
				"force_tinymce",
				"does ILIAS support running tests correctly in non-TinyMCE mode?"
			),
			(
				"fix_longtext_escaping",
				"does ILIAS handle escaping in essay questions correctly?"
			)
		]

		self.keys = [option[0] for option in self.options]

		if from_json:
			for key in self.keys:
				setattr(self, key, from_json[key])
		else:
			for key in self.keys:
				setattr(self, key, False)

	def to_json(self):
		return json.dumps(self.options)

	def print_status(self, report):
		for key in self.keys:
			report("  %s = %s" % (key, getattr(self, key)))

	def strip_whitespace(self, value):
		if (self.sloppy_whitespace) and isinstance(value, str):
			value = value.strip()
		return value
