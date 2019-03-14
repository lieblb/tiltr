#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import sys

try:
	# if pdb-clone is installed, register this process. in
	# case of problems, we can attach and debug.
	from pdb_clone import pdbhandler
	pdbhandler.register()
except ImportError:
	pass

if sys.argv[1] == "--master":
	from .http.master import run_master
	run_master()
elif sys.argv[1] == "--machine":
	from .http.machine import run_machine
	run_machine()
