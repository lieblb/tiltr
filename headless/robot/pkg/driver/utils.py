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
from selenium.common.exceptions import WebDriverException, TimeoutException, SessionNotCreatedException,\
	NoSuchWindowException, NoSuchElementException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.command import Command

import time
import itertools

from ..exceptions import *


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
	retries = 0

	while True:
		try:
			WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, css)))
			break
		except (WebDriverException, SessionNotCreatedException):
			# sporadically we get: "selenium.common.exceptions.WebDriverException:
			# Message: Failed to decode response from marionette" for some reason
			retries += 1
			if retries >= 5:
				raise


def wait_for_css_visible(driver, css, timeout=30):
	retries = 0

	while True:
		try:
			WebDriverWait(driver, timeout).until(EC.visibility_of_element_located((By.CSS_SELECTOR, css)))
			break
		except (WebDriverException, SessionNotCreatedException):
			# sporadically we get: "selenium.common.exceptions.WebDriverException:
			# Message: Failed to decode response from marionette" for some reason
			retries += 1
			if retries >= 5:
				raise


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
	retries = 0

	while True:
		try:
			field = driver.find_element_by_css_selector(css)
			break
		except NoSuchWindowException:
			retries += 1
			if retries >= 5:
				raise

	set_element_value(driver, field, value)


def set_inputs(driver, **kwargs):
	retries = 0

	while True:
		try:
			fields = driver.find_elements_by_tag_name("input")
			break
		except NoSuchWindowException:
			retries += 1
			if retries >= 5:
				raise

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
		html = "[unknown html]"

	error_class = InteractionException
	if url is not None and '/error.php' in url:
		error_class = UnexpectedErrorException

	alert_text = None
	try:
		alert_text = driver.find_element_by_css_selector(".alert").text
	except:
		pass

	if alert_text is not None:
		return error_class("ILIAS aborted with: %s.\nFULL HTML: %s" % (alert_text, html))

	if url is None:
		url = "[unknown url]"

	try:
		return error_class("failed on loading " + url + " with html:\n" + html)
	except:
		return error_class("unknown error on url %s (driver no longer functional)" % url)


def try_submit(driver, css, f, allow_reload=True, n_tries=7, max_sleep_time=8):
	button = None

	for i in range(n_tries):
		try:
			button = driver.find_element_by_css_selector(css)
			break
		except TimeoutException as e:
			time.sleep(min(max_sleep_time, 2 ** i))
		except NoSuchElementException:
			if allow_reload:
				with wait_for_page_load(driver):
					driver.refresh()
			else:
				time.sleep(min(max_sleep_time, 2 ** i))

	if not button:
		raise InteractionException("could not detect %s button. aborting." % css)

	for i in range(n_tries):
		try:
			url = driver.url
		except:
			url = "[unknown url]"

		if '/error.php' in url:
			raise get_driver_error_details(driver)

		try:
			with wait_for_page_load(driver):
				if i > 0:
					button = driver.find_element_by_css_selector(css)

				f(button)
			break
		except TimeoutException as e:
			if i >= n_tries - 1:
				raise get_driver_error_details(driver) from e
			time.sleep(min(max_sleep_time, 2 ** i))
		except NoSuchElementException as e:
			# we've seen css before, and now it's gone. usually this means that
			# we succeeded.
			break
