#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from urllib.parse import urlparse, parse_qs

from contextlib import contextmanager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.expected_conditions import staleness_of

@contextmanager
def wait_for_page_load(browser, timeout=30):
	# http://splinter.readthedocs.io/en/latest/api/driver-and-element-api.html
	old_page = browser.driver.find_element_by_tag_name('html')
	yield
	WebDriverWait(browser.driver, timeout).until(staleness_of(old_page))


def http_get_parameters(url):
	url = urlparse(url)
	parameters = dict()
	for key, values in parse_qs(url.query).items():
		parameters[key] = values[0]
	return parameters
