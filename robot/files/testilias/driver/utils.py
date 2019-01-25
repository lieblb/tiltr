#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from urllib.parse import urlparse, parse_qs
import time
import itertools
import os
from contextlib import contextmanager

import selenium
import splinter

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.expected_conditions import staleness_of
from selenium.common.exceptions import *
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.command import Command

from testilias.data.exceptions import *


def interact(driver, action, refresh=False):
	n_retries = 5
	while True:
		try:
			return action()
		except (WebDriverException, SessionNotCreatedException):
			if n_retries < 1:
				raise
			n_retries -= 1
			if refresh:
				with wait_for_page_load(driver):
					driver.refresh()


def is_loaded(driver):
	return driver.execute_script("return document.readyState") == "complete"


@contextmanager
def wait_for_page_load(driver, timeout=30):
	for i in range(5):
		try:
			old_page = driver.find_element_by_tag_name('html')
			break
		except SessionNotCreatedException:
			time.sleep(1)
		except NoSuchElementException:
			time.sleep(1)

	yield

	try:
		WebDriverWait(driver, timeout).until(staleness_of(old_page))

		WebDriverWait(driver, timeout).until(is_loaded)
	except TimeoutException:
		raise
	except WebDriverException:
		# sporadically, Selenium will fail with a strange error here:
		#
		# File "/robot/pkg/driver/utils.py", line 19, in wait_for_page_load
		#     WebDriverWait(browser.driver, timeout).until(staleness_of(old_page))
		#   File "/usr/local/lib/python3.6/dist-packages/selenium/webdriver/support/wait.py", line 71, in until
		#     value = method(self._driver)
		#   File "/usr/local/lib/python3.6/dist-packages/selenium/webdriver/support/expected_conditions.py", line 301, in __call__
		#     self.element.is_enabled()
		#   File "/usr/local/lib/python3.6/dist-packages/selenium/webdriver/remote/webelement.py", line 159, in is_enabled
		#     return self._execute(Command.IS_ELEMENT_ENABLED)['value']
		#   File "/usr/local/lib/python3.6/dist-packages/selenium/webdriver/remote/webelement.py", line 628, in _execute
		#     return self._parent.execute(command, params)
		#   File "/usr/local/lib/python3.6/dist-packages/selenium/webdriver/remote/webdriver.py", line 314, in execute
		#     self.error_handler.check_response(response)
		#   File "/usr/local/lib/python3.6/dist-packages/selenium/webdriver/remote/errorhandler.py", line 242, in check_response
		#     raise exception_class(message, screen, stacktrace)
		# selenium.common.exceptions.WebDriverException: Message: TypeError: el is undefined
		#
		# if this happens, just wait some more and hope for the best (i.e. that the page did reload).
		time.sleep(3)


def wait_for_css(driver, css, timeout=30):
	interact(driver, lambda: WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, css))))


def wait_for_css_visible(driver, css, timeout=30):
	interact(driver, lambda: WebDriverWait(driver, timeout).until(EC.visibility_of_element_located((By.CSS_SELECTOR, css))))


def set_element_value(driver, field, value):
	driver.execute_script("arguments[0].setAttribute('value', arguments[1])", field, value)


def set_elements_values(driver, values):
	driver.execute_script("""
		for (var i = 0; i < arguments[0]; i++) {
			var j = 1 + 2 * i;
			arguments[j].setAttribute('value', arguments[j + 1])
		}
	""", len(values), *list(itertools.chain(*values.items())))


def set_element_value_by_css(driver, css, value):
	field = interact(driver, lambda: driver.find_element_by_css_selector(css))
	set_element_value(driver, field, value)


def set_inputs(driver, **kwargs):
	fields = interact(driver, lambda: driver.find_elements_by_tag_name("input"))

	field_to_value = dict()

	for field in fields:
		name = field.get_attribute("name")
		if name in kwargs:
			field_to_value[field] = kwargs[name]

	set_elements_values(driver, field_to_value)


def is_driver_alive(driver):
	try:
		driver.execute(Command.STATUS)
		return True
	except:
		return False


def http_get_parameters(url):
	url = urlparse(url)
	parameters = dict()
	for key, values in parse_qs(url.query).items():
		parameters[key] = values[0]
	return parameters


def get_driver_error_details(driver):
	try:
		url = driver.url
	except:
		url = None

	try:
		html = driver.find_element_by_css_selector("body").get_attribute('innerHTML')
	except:
		html = None

	try:
		alert_text = driver.find_element_by_css_selector(".alert").text
	except:
		alert_text = None

	return url, html, alert_text


def create_detailed_exception(driver):
	url, html, alert_text = get_driver_error_details(driver)

	error_class = InteractionException
	if url is not None and '/error.php' in url:
		error_class = UnexpectedErrorException

	if html is None:
		html = "[unknown html]"

	if url is None:
		url = "[unknown url]"

	if alert_text is not None:
		return error_class("ILIAS aborted with: %s.\nURL: %s\nFULL HTML: %s" % (alert_text, url, html))
	else:
		return error_class("failed on loading %s with html: %s\n" % (url, html))


def try_submit(driver, css, f, allow_reload=True, allow_empty=True, n_tries=7, max_sleep_time=8):
	button = None

	for i in range(n_tries):
		try:
			button = driver.find_element_by_css_selector(css)
			break
		except (TimeoutException, ElementClickInterceptedException, ElementNotInteractableException):
			time.sleep(min(max_sleep_time, 2 ** i))
		except NoSuchElementException:
			if allow_reload:
				with wait_for_page_load(driver):
					driver.refresh()
			else:
				time.sleep(min(max_sleep_time, 2 ** i))

	if not button:
		if allow_empty:
			return False
		raise InteractionException("could not detect %s button. aborting." % css)

	old_url = None
	unknown_url = "[unknown url]"

	for i in range(n_tries):
		try:
			url = driver.current_url
		except:
			url = unknown_url

		if old_url is None:
			old_url = url
		elif url != old_url and url != unknown_url and old_url != unknown_url:
			break  # the page already changed.

		if '/error.php' in url:
			raise create_detailed_exception(driver)

		try:
			with wait_for_page_load(driver):
				f(button)
			break
		except (TimeoutException, ElementClickInterceptedException, ElementNotInteractableException) as e:
			if i >= n_tries - 1:
				raise create_detailed_exception(driver) from e
			time.sleep(min(max_sleep_time, 2 ** i))
		except NoSuchElementException:
			# we've seen css before, and now it's gone. usually this means that
			# we succeeded.
			break
		except StaleElementReferenceException:
			# this usually indicates our click and page change has finally succeeded.
			break

	return True


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
	def _create_firefox(resolution, **kwargs):
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
	def _create_chrome(resolution, **kwargs):
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


def create_browser(browser='firefox', resolution=None, **kwargs):
	return DriverFactory.create(browser, resolution, **kwargs)
