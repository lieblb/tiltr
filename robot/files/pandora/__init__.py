#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import selenium
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities


class Browser:
	def __init__(self, browser='firefox', **kwargs):
		capabilities = dict(
			chrome=DesiredCapabilities.CHROME,
			firefox=DesiredCapabilities.FIREFOX)

		self._driver = selenium.webdriver.Remote(
			command_executor='http://selenium-%s:%d/wd/hub' % (browser, 4444),
			desired_capabilities=capabilities.get(browser))

	def __enter__(self):
		return self

	def __exit__(self, *args):
		self._driver.quit()

	@property
	def driver(self):
		return self._driver
