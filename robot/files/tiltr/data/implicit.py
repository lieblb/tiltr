#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import re


def looks_like_a_number(x):
	m = re.match(r'^((\+|\-)?(([0-9]+)|([0-9]+\.)|(\.[0-9]+)|([0-9]+\.[0-9]+)))$', x)
	return m is not None


def implicit_text_to_number(value):
	if len(value) >= 2 and value[0] == '+' and looks_like_a_number(value[1:]):
		# e.g. +9 -> 9
		value = value[1:]

	if looks_like_a_number(value):
		while value.endswith("0") and value.count('.') == 1 and not value.endswith(".0"):
			# e.g. 0.637010 -> 0.63701
			value = value[:-1]

		integer_match = re.match(r'^((\+|\-)?[0-9]+)\.$', value)
		if integer_match:
			# e.g. 13. -> 13, but do not convert -. -> -
			value = integer_match.group(1)
		elif len(value) >= 2 and value.startswith("."):
			# e.g. .17 -> 0.17
			value = "0" + value
		elif value.endswith(".0"):
			# e.g. 5.0 -> 5
			value = value[:-2]

	return value


def implicit_text_to_number_xls(value):
	# there are also several implicit conversions taking place when taking the number
	# from ILIAS into the XLS, but they are different from the ones inside ILIAS itself,
	# i.e. from implicit_text_to_number.

	# also catch more esoteric conversions like 3E6 -> 3000000
	try:
		value = str(float(value))
	except ValueError:
		pass

	if isinstance(value, str) and looks_like_a_number(value):
		while value.endswith("0") and value.count('.') == 1 and not value.endswith(".0"):
			# e.g. 0.637010 -> 0.63701
			value = value[:-1]

		if len(value) >= 2 and value[0] == '.' and value[-1] != '0':
			# e.g. .94853 -> .948530
			value += "0"

		if value == "0.0" or value == "-0.0" or value == "-0":
			# e.g. "0.0" -> "0".  note that other conversions, e.g. 597.0 -> 597, don't
			# take place!
			value = "0"

	return value
