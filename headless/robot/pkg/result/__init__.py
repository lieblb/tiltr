#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import json
import time
from enum import Enum

import database


def normalize_answer(value):
	if isinstance(value, basestring):
		value = value.replace("\n", "\\n")
	return value


class AnswerProtocol:
	def __init__(self, title):
		self.title = title
		self.entries = []

	def choose(self, key, value):
		self.entries.append((time.time(), "answered '%s' with '%s'" % (key, normalize_answer(value))))

	def verify(self, key, expected, actual):
		if expected == actual:
			self.entries.append((time.time(), "OK verified that '%s' is still '%s'" % (key, normalize_answer(expected))))
		else:
			self.entries.append((time.time(), "FAIL answer on '%s' was stored incorrectly: answer was '%s', but ILIAS stored '%s'" % (
				key, normalize_answer(expected), normalize_answer(actual))))
			raise Exception("answer mismatch during verification")

	def encode(self):
		return self.entries


class Origin(Enum):
	recorded = 0
	exported = 1


class Result:
	def __init__(self, from_json=None, **kwargs):
		if from_json:
			data = json.loads(from_json)
			self.origin = Origin[data["origin"]]
			self.properties = data["properties"]
			self.protocol = data["protocol"]
			self.performance = data["performance"]
			self.errors = data["errors"]
		else:
			self.origin = kwargs["origin"]
			self.properties = dict()
			self.protocol = None
			self.performance = None
			self.errors = dict()

	def to_json(self):
		return json.dumps(dict(
			origin=self.origin.name,
			properties=self.properties,
			protocol=self.protocol,
			performance=self.performance,
			errors=self.errors))

	def get_origin(self):
		return self.origin

	def add(self, key, value):
		assert key not in self.properties
		self.properties[key] = value

	@staticmethod
	def from_error(origin, type, err):
		r = Result(origin=origin)
		r.errors[type] = err
		return r

	def get(self, key):
		return self.properties.get(key, None)

	def set_protocol(self, protocol):
		self.protocol = protocol

	def set_performance_measurements(self, performance):
		self.performance = performance

	def check_against(self, other, report, workarounds):
		report("assertions:")

		all_ok = True

		keys = sorted(list(set(
			self.properties.keys() + other.properties.keys())))

		for k in keys:
			value_self = "%s" % self.get(k)
			value_other = "%s" % other.get(k)

			value_self = workarounds.strip_whitespace(value_self)
			value_other = workarounds.strip_whitespace(value_other)

			if value_self == value_other:
				status = "OK"
			else:
				status = "FAIL"
				all_ok = False

			report("%s %s: %s [%s] %s %s [%s]" % (
				status, k,
				value_self.replace("\n", "\\n"), self.get_origin(),
				"==" if status == "OK" else "!=",
				value_other.replace("\n", "\\n"), other.get_origin()))

		report("")

		if self.errors:
			for type, err in self.errors.items():
				report("error %s:%s in %s" % (type, err, self.origin))
			all_ok = False
		if other.errors:
			for type, err in other.errors.items():
				report("error %s:%s in %s" % (type, err, other.origin))
			all_ok = False

		return all_ok


def open_results():
	return database.DB()