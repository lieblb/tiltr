#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import selenium
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities


class Browser:
	@staticmethod
	def _configure_driver(driver, resolution):
		try:
			# we try to avoid the need to scroll. a large size can cause memory issues.
			w = 1024
			h = 1024

			if resolution is not None and isinstance(resolution, str):
				w, h = resolution.split('x')
				w = int(w)
				h = int(h)

			driver.set_window_size(w, h)

			driver.set_page_load_timeout(30)

		except:
			driver.quit()
			raise

	def __init__(self, browser='firefox', **kwargs):
		capabilities = dict(
			chrome=DesiredCapabilities.CHROME,
			firefox=DesiredCapabilities.FIREFOX)

		self._driver = selenium.webdriver.Remote(
			command_executor='http://selenium-%s:%d/wd/hub' % (browser, 4444),
			desired_capabilities=capabilities.get(browser))

		Browser._configure_driver(self._driver, kwargs.get('resolution'))

	def __enter__(self):
		return self

	def __exit__(self, *args):
		self._driver.quit()

	@property
	def driver(self):
		return self._driver
