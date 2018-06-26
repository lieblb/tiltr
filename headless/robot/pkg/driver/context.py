#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import random
import re
from ..question.coverage import Coverage


def random_number(n):
	if n == 0:
		return ""
	elif n == 1:
		return str(random.randint(0, 9))
	elif random.random() < 0.5:
		if random.random() < 0.5:
			return "." + str(random.randint(0, (10 ** (n - 1)) - 1))
		else:
			return str(random.random() * 1000)[:n]
	else:
		s = ""
		if random.random() < 0.5:
			s += "+"
		s += str(random.randint(0, (10 ** (n - len(s))) - 1))
		return s


def random_text(n, random_chars):
	if random.random() * 100 < 5:
		return random_number(n)
	else:
		components = list()
		n_chars = 0
		while n_chars < n:
			p = random.choice(random_chars)
			if n_chars + len(p) <= n:
				components.append(p)
				n_chars += len(p)
		return "".join(components)


def get_random_chars(allow_newlines, allow_dollar, allow_clamps):
	random_chars =\
		u" ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789éáèêäöüÄÖÜß?!.-_:;#§%&=^|\{\}[]()@+-*/~'\"\t"
	if allow_newlines:
		random_chars += "\n"
	if allow_clamps:
		random_chars += "<>"
	if allow_dollar:
		random_chars += "$"

	random_chars = [c for c in random_chars]
	random_chars.extend(["&lt;", "&gt;", "&amp;"])

	return random_chars


class TestContext:
	def __init__(self, questions, workarounds):
		self.workarounds = workarounds
		self.cloze_random_chars = get_random_chars(
			allow_newlines=False,
			allow_dollar=not workarounds.disallow_dollar_in_cloze,
			allow_clamps=not workarounds.disallow_clamps_in_cloze)
		self.long_text_random_chars = get_random_chars(
			allow_newlines=True,
			allow_dollar=True,
			allow_clamps=True)
		self.coverage = Coverage(questions, self)

	def strip_whitespace(self, value):
		return self.workarounds.strip_whitespace(value)

	def collapse_whitespace(self, value):
		if self.workarounds.sloppy_whitespace:
			if isinstance(value, str):
				value = re.sub(r'\s+', r' ', value)
		return value


class RegressionContext(TestContext):
	def prefer_text(self):
		return True  # prefer entering random text to picking correct solution in cloze gaps

	def produce_text(self, size, random_chars):
		special = ""
		for c in "<>\n":
			if c in random_chars:
				special += c
		if len(special) == 0:
			return random_text(size, random_chars)
		s = ""
		while len(s) < size:
			if len(s) % len(special) == 0:
				s += random_text(1, random_chars)
			else:
				s += special[0]
				special = special[1:] + special[:1]
		return s


class RandomContext(TestContext):
	def prefer_text(self):
		return False

	def produce_text(self, size, random_chars):
		return random_text(random.randint(0, size), random_chars)
