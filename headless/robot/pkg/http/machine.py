#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import threading
import traceback
import StringIO
import sys
import json

import tornado.ioloop
import tornado.web

from splinter import Browser

from ..driver import TakeExamCommand


class GlobalState:
	def __init__(self):
		self.browser = None
		self.runner = None

	def init_browser(self, machine_index):
		log_path = "tmp/geckodriver.machine_%d.log" % machine_index
		open(log_path, 'w').close()  # empty log file
		if self.browser is None:
			self.browser = Browser(headless=True, log_path=log_path)
		return self.browser


class Runner(threading.Thread):
	def __init__(self, browser, batch, command):
		threading.Thread.__init__(self)
		self.browser = browser
		self.batch = batch
		self.command = command
		self.screenshot = None
		self.messages = []

	def get_batch(self):
		return self.batch

	def run(self):
		def report(*args):
			self.screenshot = self.browser.driver.get_screenshot_as_base64()
			self.messages.append(["ECHO", " ".join("%s" % arg for arg in args)])

		try:
			expected_result = self.command.run(self.browser, report)
			self.messages.append(["DONE", expected_result.to_json()])
		except:
			traceback.print_exc()

			buffer = StringIO.StringIO()
			traceback.print_exc(file=buffer)
			message = buffer.getvalue()

			self.messages.append(["ERROR", message])

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
			self.state.runner = Runner(self.state.init_browser(command.machine_index), batch, command)
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

	app = make_app()
	app.listen(8888)

	print("HELLO.")
	sys.stdout.flush()

	tornado.ioloop.IOLoop.current().start()
