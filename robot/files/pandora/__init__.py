#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import splinter
import selenium


class SingletonBrowserContext:
	# keep this driver around and never quit. used for chrome:
	# due to a bug in the chrome driver, opening and closing chrome
	# eventually leads to thousands of chrome zombie processes that
	# kill the whole machine (lack of resources/memory).

	def __init__(self, driver):
		self.driver = driver

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		pass


class DriverFactory:
	_singletons = dict()

	@staticmethod
	def create(browser_name, resolution, **kwargs):
		if browser_name in DriverFactory._singletons:
			return DriverFactory._singletons[browser_name]
		else:
			create_driver = dict(
				firefox=DriverFactory._create_firefox,
				chrome=DriverFactory._create_chrome
			)

			if browser_name not in create_driver:
				raise RuntimeError("unsupported browser %s" % browser_name)

			create = create_driver[browser_name]
			browser = create(resolution=resolution, **kwargs)

			DriverFactory._configure_driver(browser.driver, resolution)

			if browser is SingletonBrowserContext:
				DriverFactory._singletons[browser_name] = browser

			return browser

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

		return driver

	@staticmethod
	def _create_firefox(resolution=None, **kwargs):
		# use splinter to create the firefox driver - this yields
		# much more reliable drivers - the pure selenium driver
		# will crash after 5 to 10 iterations of start and quit.

		# for details, see
		# https://github.com/cobrateam/splinter/blob/master/splinter/driver/webdriver/firefox.py

		args = dict(headless=True)

		for k in ('log_path', 'wait_time'):
			if k in kwargs:
				args[k] = kwargs[k]

		# moz:webdriverClick needed for file uploads to work.
		args['capabilities'] = {"moz:webdriverClick": False}

		return splinter.Browser('firefox', **args)

	@staticmethod
	def _create_chrome(resolution=None, **kwargs):
		options = selenium.webdriver.chrome.options.Options()

		options.headless = True

		options.add_argument('start-maximized')
		options.add_argument('disable-infobars')
		options.add_argument('disable-extensions')
		options.add_argument('disable-dev-shm-usage')
		options.add_argument('no-sandbox')
		options.add_argument('disable-setuid-sandbox')
		options.add_argument('dns-prefetch-disable')

		return SingletonBrowserContext(selenium.webdriver.Chrome(options=options))


def create_browser(**kwargs):
	return DriverFactory.create(**kwargs)


class Browser:
	def __init__(self, browser='firefox', **kwargs):
		self._context = DriverFactory.create(browser_name=browser, **kwargs)

	def __enter__(self):
		return self._context.__enter__()

	def __exit__(self, *args):
		return self._context.__exit__(*args)

	@property
	def driver(self):
		return self._context.driver

