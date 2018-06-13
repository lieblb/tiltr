#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import sys

if sys.argv[1] == "master":
	from .http.master import run_master
	run_master()
elif sys.argv[1] == "machine":
	from .http.machine import run_machine
	run_machine()
