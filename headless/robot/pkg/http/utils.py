#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import os
import time
import shutil

# we're running stuff inside Docker containers. if we're running for a long time, our
# /tmp folders gets larger and larger (e.g. > 1GB per machine). this function allows
# us to delete old stuff periodically, so this does not pose a problem.


def clear_tmp(keep_minutes=15):
	files = os.listdir("/tmp")
	too_old = time.time() - keep_minutes * 60

	for filename in files:
		path = os.path.join("/tmp", filename)
		stat = os.stat(path)
		if max(stat.st_ctime, stat.st_atime) < too_old:
			if os.path.isfile(path):
				os.remove(path)
			else:
				shutil.rmtree(path, ignore_errors=True)
