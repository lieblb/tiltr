#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import json
import time
from enum import Enum
from decimal import *
from collections import defaultdict

from ..question.coverage import Coverage
from .database import DB


class Origin(Enum):
	recorded = 0
	exported = 1


class ErrorDomain(Enum):
	webdriver = 0
	qa = 1


class Result:
	def __init__(self, from_json=None, **kwargs):
		if from_json:
			data = json.loads(from_json)
			self.origin = Origin[data["origin"]]
			self.properties = dict((tuple(key), value) for key, value in data["properties"])
			self.protocol = data["protocol"]
			self.performance = data["performance"]
			self.errors = data["errors"]
			self.coverage = Coverage(from_dict=data["coverage"])
		else:
			self.origin = kwargs.get("origin", "unknown")
			self.properties = dict()
			self.protocol = []
			self.performance = []
			self.errors = dict()
			self.coverage = Coverage()

	def to_json(self):
		return json.dumps(dict(
			origin=self.origin.name,
			properties=list(self.properties.items()),
			protocol=self.protocol,
			performance=self.performance,
			errors=self.errors,
			coverage=self.coverage.as_dict()))

	def get_origin(self):
		return self.origin

	def add(self, key, value):
		assert key not in self.properties
		if isinstance(value, Decimal):
			value = str(value)  # make it safe for JSON
		self.properties[key] = value

	def update(self, key, value):
		assert key in self.properties
		if isinstance(value, Decimal):
			value = str(value)  # make it safe for JSON
		self.properties[key] = value

	@staticmethod
	def from_error(origin, domain, err):
		r = Result(origin=origin)
		r.errors[domain.name] = err
		return r

	def has_error(self, domain):
		return domain.name in self.errors

	def get(self, key):
		return self.properties.get(key, None)

	def attach_protocol(self, protocol):
		self.protocol = protocol

	def attach_performance_measurements(self, performance):
		self.performance = performance

	def attach_coverage(self, coverage):
		self.coverage = coverage

	def get_normalized_properties(self):
		return dict((tuple(str(k) for k in key), value) for key, value in self.properties.items())

	def get_answers(self):
		answers = defaultdict(dict)
		for p, value in self.properties.items():
			if p[0] == "question" and p[2] == "answer":
				question_title = p[1]
				dimension = p[3]
				answers[question_title][dimension] = value
		return answers

	def check_against(self, other, report, workarounds):
		all_ok = True

		self_properties = self.get_normalized_properties()
		other_properties = other.get_normalized_properties()

		keys = sorted(list(set(
			list(self_properties.keys()) + list(other_properties.keys()))))

		for k in keys:
			value_self = "%s" % self_properties.get(k, None)
			value_other = "%s" % other_properties.get(k, None)

			value_self = workarounds.normalize(value_self)
			value_other = workarounds.normalize(value_other)

			if value_self == value_other:
				status = "OK"
			else:
				status = "FAIL"
				all_ok = False

			report("%s %s: %s [%s] %s %s [%s]" % (
				status, " / ".join(k),
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
	return DB()