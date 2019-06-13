#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from typing import List, Tuple

import re
import random as rnd

from tiltr.question.coverage import Coverage

from ..data.settings import Settings, Workarounds
from .implicit import implicit_text_to_number_xls, implicit_text_to_number


def random_number(random, n: int) -> str:
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
		s = random.choice(('', '-', '+'))
		s += str(random.randint(0, (10 ** (n - len(s))) - 1))
		return s


def get_random_chars(allow_newlines: bool, allow_dollar: bool, allow_clamps: bool) -> List[str]:
	random_chars = " "  # space
	random_chars += "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
	random_chars += "éáèêäöüÄÖÜß?!.-_:;#§%&=^|{}[]()@+-*/~'\"\t\\"
	if allow_newlines:
		random_chars += "\n"
	if allow_clamps:
		random_chars += "<>"
	if allow_dollar:
		random_chars += "$"

	random_chars = [c for c in random_chars]
	random_chars.extend(["&lt;", "&gt;", "&amp;", "\\1"])
	if allow_dollar:
		random_chars.extend(["$1"])

	return random_chars


class TestContext:
	settings: Settings
	workarounds: Workarounds
	cloze_random_chars: List[str]
	long_text_random_chars: List[str]
	coverage: Coverage
	language: str
	ilias_version: Tuple

	def __init__(
			self, questions: List['Question'], settings: Settings, workarounds: Workarounds,
			language: str, ilias_version: Tuple):

		allow_cloze_clamps = not (
			workarounds.dont_use_clamps_in_cloze_readjustments or
			workarounds.disallow_clamps_in_cloze)

		self.settings = settings
		self.workarounds = workarounds
		self.cloze_random_chars = get_random_chars(
			allow_newlines=False,
			allow_dollar=not workarounds.disallow_dollar_in_cloze,
			allow_clamps=allow_cloze_clamps)
		self.long_text_random_chars = get_random_chars(
			allow_newlines=True,
			allow_dollar=True,
			allow_clamps=True)
		self.coverage = Coverage(questions, self)
		self.language = language
		self.ilias_version = ilias_version

	def _random_text(self, n: int, random_chars: List[str], allow_numbers: bool=True) -> str:
		if allow_numbers and self.random.random() < self.settings.numbers_in_text_fields_p:
			return random_number(self.random, n)
		else:
			components = list()

			n_chars = 0
			while n_chars < n:
				p = self.random.choice(random_chars)

				if n_chars == 0 and not allow_numbers:
					if p.isdigit() or p == '.':
						continue

				if n_chars + len(p) <= n:
					components.append(p)
					n_chars += len(p)

			return "".join(components)

	def strip_whitespace(self, value: str) -> str:
		return self.workarounds.strip_whitespace(value)

	def collapse_whitespace(self, value: str) -> str:
		if self.workarounds.sloppy_whitespace:
			if isinstance(value, str):
				value = re.sub(r'\s+', r' ', value)
		return value

	def implicit_text_to_number(self, value: str) -> str:
		if not self.workarounds.implicit_text_number_conversions:
			return value
		else:
			return implicit_text_to_number(value)

	def implicit_text_to_number_xls(self, value: str) -> str:
		if not self.workarounds.implicit_text_number_conversions:
			return value
		else:
			return implicit_text_to_number_xls(value)

	def prefer_text(self) -> bool:
		raise NotImplementedError()

	def _produce_text(self, size: int, random_chars: list, allow_numbers: bool = False) -> str:
		raise NotImplementedError()

	def produce_text(self, size: int, random_chars: list, allow_numbers: bool = False) -> str:
		while True:
			text = self._produce_text(size, random_chars, allow_numbers)

			if not self.workarounds.disallow_empty_answers:
				break

			# in this case, ILIAS does not support empty answers, as they will end up with a None
			# score in the XLS
			if len(text.strip()) >= 1:
				break

		return text


class RegressionContext(TestContext):
	def __init__(self, seed, *args):
		super().__init__(*args)
		self.random = rnd.Random(seed)

	def prefer_text(self) -> bool:
		return True  # prefer entering random text to picking correct solution in cloze gaps

	def _produce_text(self, size: int, random_chars: list, allow_numbers=False) -> str:
		special = ""
		for c in "<>\n":
			if c in random_chars:
				special += c
		if len(special) == 0:
			return self._random_text(size, random_chars, allow_numbers)
		s = ""
		while len(s) < size:
			if len(s) % len(special) == 0:
				s += self._random_text(1, random_chars, allow_numbers)
			else:
				s += special[0]
				special = special[1:] + special[:1]
		return s


class RandomContext(TestContext):
	def __init__(self, *args):
		super().__init__(*args)
		self.random = rnd.SystemRandom()

	def prefer_text(self) -> bool:
		return False

	def _produce_text(self, size: int, random_chars: list, allow_numbers: bool = False) -> str:
		if self.workarounds.disallow_empty_answers:
			if size < 1:
				raise Exception("internal error: max allowed produce_text size too small")
			min_size = 1
		else:
			min_size = 0
		return self._random_text(self.random.randint(min_size, size), random_chars, allow_numbers)

