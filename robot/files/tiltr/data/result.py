#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import json
import base64
import re

from enum import Enum
from decimal import *
from collections import defaultdict

from .database import DB
from .exceptions import ErrorDomain, most_severe


def _dump_properties(properties, report):
	# this supports tuple-keys (for matching questions); which is why we don't simply use
	# json.dumps(properties) to print this out.
	for k, v in properties.items():
		report('  %s: %s' % (json.dumps(k), json.dumps(v)))


def _flat(x):
	if isinstance(x, tuple):
		for y in x:
			for yy in _flat(y):
				yield yy
	else:
		yield x


def _normalize_json(s):
	try:
		return json.dumps(json.loads(s))
	except ValueError:
		return '-illegal-json-' + s


class Origin(Enum):
	recorded = 0
	exported = 1


class Result:
	@staticmethod
	def key(*args):
		return tuple(_flat(args))

	@staticmethod
	def normalize_question_title(title):
		return re.sub(r'\s+', '', title)

	def __init__(self, from_json=None, **kwargs):
		from ..question.coverage import Coverage

		if from_json:
			data = json.loads(from_json)
			self.origin = Origin[data["origin"]]
			self.properties = dict((tuple(key), value) for key, value in data["properties"])
			self.types = dict((tuple(key), value) for key, value in data["types"])
			self.protocol = data["protocol"]
			self.files = dict((k, base64.b64decode(v)) for k, v in data["files"].items())
			self.performance = data["performance"]
			self.errors = data["errors"]
			self.coverage = Coverage(from_dict=data["coverage"])
		else:
			self.origin = kwargs.get('origin', 'unknown')
			self.properties = dict()
			self.types = dict()
			self.protocol = []
			self.files = kwargs.get('files', dict())
			self.performance = []
			self.errors = dict()
			self.coverage = Coverage()

	def to_json(self):
		return json.dumps(dict(
			origin=self.origin.name,
			properties=list(self.properties.items()),
			types=list(self.types.items()),
			protocol=self.protocol,
			files=dict((k, base64.b64encode(v).decode('utf8')) for k, v in self.files.items()),
			performance=self.performance,
			errors=self.errors,
			coverage=self.coverage.as_dict()))

	def get_origin(self):
		return self.origin

	def add(self, key, value, value_type=None):
		assert key not in self.properties
		if isinstance(value, Decimal):
			value = str(value)  # make it safe for JSON
		self.properties[key] = value
		if value_type:
			self.types[key] = value_type

	def update(self, key, value):
		assert key in self.properties
		if isinstance(value, Decimal):
			value = str(value)  # make it safe for JSON
		self.properties[key] = value

	def add_as_formatted_score(self, key, score):
		s = str(score)
		if '.' in s:
			s = s.rstrip('0')
			if s.endswith('.'):
				s = s.rstrip('.')
		self.add(key, s)

	@staticmethod
	def from_error(origin, domain, err, files=None):
		r = Result(origin=origin, files=files or dict())
		r.errors[domain.name] = err
		return r

	def get_most_severe_error(self):
		return most_severe(ErrorDomain[d] for d in self.errors.keys())

	def get(self, key):
		return self.properties.get(key, None)

	def attach_protocol(self, protocol):
		self.protocol = protocol

	def attach_file(self, filename, bytes):
		self.files[filename] = bytes

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

			type_self = self.types.get(k, None)
			type_other = self.types.get(k, None)
			types = tuple(set(t for t in (type_self, type_other) if t is not None))

			value_self = workarounds.normalize(value_self)
			value_other = workarounds.normalize(value_other)

			if types == ('json',):
				value_self = _normalize_json(value_self)
				value_other = _normalize_json(value_other)
			elif len(types) > 0:
				raise RuntimeError("incompatible property data types")

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

		if not all_ok:
			report("DUMP of properties A:")
			_dump_properties(self.properties, report)
			report("DUMP of properties B:")
			_dump_properties(other.properties, report)

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
