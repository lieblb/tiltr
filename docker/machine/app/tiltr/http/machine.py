#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import threading
import traceback
import sys
import json
import time
import os

import tornado.ioloop
import tornado.web

import pandora

from selenium.common.exceptions import WebDriverException
from tiltr.data.exceptions import InteractionException
from tiltr.data.result import Result, Origin

from ..driver.commands import TakeExamCommand
from .utils import clear_tmp
from .args import parse_args


class GlobalState:
	def __init__(self):
		self.runner = None


class Runner(threading.Thread):
	def __init__(self, state, batch, command):
		threading.Thread.__init__(self)
		clear_tmp()

		self.state = state
		self.wait_time = command.wait_time
		self.batch = batch
		self.command = command

		self.messages = []
		self.screenshot = None
		self.screenshot_valid_time = time.time()
		self.screenshot_refresh_time = float(command.settings.screenshot_refresh_time)

	def get_batch(self):
		return self.batch

	def run(self):
		# isolate the selenium driver from our main process through a fork. this fixes severe problems with
		# chrome zomie processes piling up inside the selenium chrome docker container.

		pipein, pipeout = os.pipe()
		if os.fork() == 0:

			os.close(pipein)

			def write(*args):
				os.write(pipeout, (json.dumps(args) + "\n").encode('utf8'))

			try:
				try:
					with self._create_browser() as browser:
						def report(*args):
							if time.time() > self.screenshot_valid_time:
								try:
									screenshot = browser.driver.get_screenshot_as_base64()
									self.screenshot_valid_time = time.time() + self.screenshot_refresh_time
									write("SCREENSHOT", screenshot)
								except:
									pass  # screenshot failed

							write("ECHO", " ".join("%s" % arg for arg in args))

						report("machine browser has wait time %d." % self.wait_time)
						report('running on user agent', browser.driver.execute_script('return navigator.userAgent'))

						expected_result = self.command.run(browser, report)
				except WebDriverException as webdriver_error:
					# we end up here in case our browser / selenium does not start and fails to close down.
					e = InteractionException(str(webdriver_error))
					traceback.print_exc()
					expected_result = Result.from_error(Origin.recorded, e.get_error_domain(), traceback.format_exc())

				if expected_result is None:
					write("ERROR", "no result obtained")
				else:
					write("DONE", expected_result.to_json())
			except:
				traceback.print_exc()
				write("ERROR", traceback.format_exc())

			sys.exit(0)

		else:
			os.close(pipeout)

			try:
				with os.fdopen(pipein) as fdpipein:
					while True:
						line = fdpipein.readline()[:-1]
						if not line:
							break
						data = json.loads(line)
						if data[0] == 'SCREENSHOT':
							self.screenshot = data[1]
						else:
							self.messages.append(data)
			finally:
				os.close(pipein)

	def _create_browser(self):
		return pandora.Browser(
			browser=self.command.settings.browser,
			wait_time=self.command.wait_time,
			resolution=self.command.settings.resolution)

	def get_messages(self, index):
		return self.messages[index:]

	def get_screenshot(self):
		return self.screenshot


class HelloHandler(tornado.web.RequestHandler):
	def post(self):
		self.write('HelloToo')
		self.finish()


class StartHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state	

	def post(self, batch):
		if self.state.runner and not self.state.runner.is_alive():
			self.state.runner = None

		if self.state.runner is None:
			command_json = self.get_argument("command_json")
			command = TakeExamCommand(from_json=command_json)
			self.state.runner = Runner(self.state, batch, command)
			self.state.runner.start()

		self.finish()


class AbortHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state	

	def get(self, index):
		pass


class MonitorHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state	

	def get(self, batch, index):
		runner = self.state.runner

		if runner and runner.get_batch() == batch:
			self.write(json.dumps(runner.get_messages(int(index))))
		else:
			self.write(json.dumps([]))

		self.finish()


class ScreenshotHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state	

	def get(self, batch):
		runner = self.state.runner

		if runner and runner.get_batch() == batch and runner.get_screenshot():
			self.write(runner.get_screenshot())

		self.finish()


def make_app():
	state = GlobalState()

	return tornado.web.Application([
		(r"/hello/", HelloHandler),
		(r"/start/(?P<batch>[^/]+)", StartHandler, dict(state=state)),
		(r"/abort/", AbortHandler, dict(state=state)),
		(r"/monitor/(?P<batch>[^/]+)/(?P<index>[0-9]+)", MonitorHandler, dict(state=state)),
		(r"/screenshot/(?P<batch>[^/]+)", ScreenshotHandler, dict(state=state))
	])


def run_machine():
	print("starting machine.")
	parse_args()  # ignored right now

	app = make_app()
	app.listen(8888)

	print("HELLO.")
	sys.stdout.flush()

	tornado.ioloop.IOLoop.current().start()
