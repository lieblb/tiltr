#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from enum import Enum
from collections import namedtuple


class Validness(Enum):
	VALID = 1
	INVALID = -1


class Answer:
	def __init__(self):
		raise NotImplementedError()

	def randomize(self, context):
		raise NotImplementedError()

	def verify(self, context, after_crash=False):
		raise NotImplementedError()

	def to_dict(self, context, language):
		raise NotImplementedError()


Choice = namedtuple('Choice', ['selector', 'label', 'checked'])
