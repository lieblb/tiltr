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
from selenium.common.exceptions import WebDriverException, TimeoutException, SessionNotCreatedException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

import time


def is_loaded(driver):
	return driver.execute_script("return document.readyState") == "complete"

@contextmanager
def wait_for_page_load(driver, timeout=30):
	for i in range(3):
		try:
			old_page = driver.find_element_by_tag_name('html')
			break
		except SessionNotCreatedException:
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
	WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, css)))


def set_element_value(driver, field, value):
	driver.execute_script("arguments[0].setAttribute('value', arguments[1])", field, value)


def set_element_value_by_css(driver, css, value):
	field = driver.find_element_by_css_selector(css)
	set_element_value(driver, field, value)


def http_get_parameters(url):
	url = urlparse(url)
	parameters = dict()
	for key, values in parse_qs(url.query).items():
		parameters[key] = values[0]
	return parameters
