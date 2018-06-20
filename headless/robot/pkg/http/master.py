#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import os
import requests
import io
import re
import json
import threading
import time

import tornado.ioloop
import tornado.web
import tornado.websocket

from .discovery import connect_machines
from ..driver.batch import Batch
from ..driver.drivers import Test
from ..result import open_results
from ..workarounds import Workarounds


def get_ilias_version():
	from splinter import Browser
	log_path = "tmp/geckodriver.master.log"
	open(log_path, 'w').close()  # empty log file
	browser = Browser(headless=True, log_path=log_path, wait_time=5)
	browser.visit("http://web:80/ILIAS")

	# if this is the first startup of ILIAS, it can take quite some time, until it's available.
	bdo = browser.find_by_css("footer bdo")
	if bdo and len(bdo) == 1:
		print(bdo.text)
		s = re.split("\(|\)", bdo.text)
		if len(s) >= 2:
			return s[1]

	return None


class Looper(threading.Thread):
	def __init__(self, state, test_name, workarounds, wait_time):
		threading.Thread.__init__(self)
		self.state = state
		self.test_name = test_name
		self.workarounds = workarounds
		self.wait_time = wait_time
		self.done = False

	def run(self):
		while self.state.looping:
			if self.state.batch and self.state.batch.is_done():
				self.state.batch = None

			if self.state.batch is None:
				self.state.start_batch(self.test_name, self.workarounds, self.wait_time)

			time.sleep(1)

		print("looper has exited.")


class GlobalState:
	def __init__(self, machines):
		self.machines = machines
		self.batch = None
		self.ilias_version = None
		self.looper = None
		self.looping = False

	def get_ilias_version(self):
		if self.ilias_version is None:
			self.ilias_version = get_ilias_version()  # try again
		return self.ilias_version

	def set_looping(self, looping):
		self.looping = looping
		print("setting looping to %s." % looping)
		if self.batch and self.looping and self.looper is None:
			batch = self.batch
			self.looper = Looper(self, batch.test_name, batch.workarounds, batch.wait_time)
			self.looper.start()

	def start_batch(self, test_name, workarounds, wait_time):
		if self.batch and self.batch.is_done():
			self.batch = None

		ilias_version = self.get_ilias_version()  # available?
		if ilias_version is None:
			return None

		if self.batch is None:
			self.batch = Batch(self.machines, ilias_version, test_name, workarounds, wait_time)
			self.batch.start()

		if self.looping:
			if self.looper is None:
				self.looper = Looper(self, test_name, workarounds, wait_time)
				self.looper.start()
			else:
				self.looper.workarounds = workarounds
		elif self.looper:
			self.looper = None

		return self.batch.get_id()


class AppHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def get(self):
		self.render("master.html",
			num_machines=len(self.state.machines),
			ilias_url=self.request.host.replace("11150", "11145"),
			ilias_version=self.state.get_ilias_version() or "unavailable")


class StatusHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def get(self):
		batch = self.state.batch
		if batch and not batch.is_done():
			self.write(json.dumps(dict(batchId=batch.get_id())))
		else:
			self.write(json.dumps(dict()))
		self.flush()


class TestsHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def get(self):
		self.write(json.dumps(Test.list()))
		self.flush()


class StartBatchHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def post(self):
		data = json.loads(self.request.body)

		workarounds = Workarounds(from_json=data["workarounds"])
		test_id = data["test"]
		wait_time = 1
		batch_id = self.state.start_batch(test_id, workarounds, wait_time)

		if batch_id is None:
			self.write("error")
		else:
			self.write(batch_id)

		self.flush()


class WebSocketHandler(tornado.websocket.WebSocketHandler):
	def initialize(self, state):
		self.state = state

	def open(self, batch):
		if self.state.batch and self.state.batch.get_id() == batch:
			self.state.batch.add_socket(self)
		else:
			self.close()  # reject this connection

	def on_close(self):
		if self.state.batch:
			self.state.batch.remove_socket(self)

	def on_message(self, message):
		pass


class ScreenshotHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def get(self, machine):
		if self.state.batch:
			if machine == "master":
				try:
					screenshot = self.state.batch.get_screenshot_as_base64()
					if screenshot:
						self.write(screenshot)
				except:
					print("screenshot on master failed.")
			else:
				machine_ip = self.state.machines[machine]

				r = requests.get("http://%s:8888/screenshot/%s" %
					(machine_ip, self.state.batch.get_id()), data={})
				self.write(r.text)

		self.finish()


class WorkaroundsHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def get(self):
		if self.state.batch:
			workarounds = self.state.batch.workarounds
		else:
			workarounds = Workarounds()  # default settings

		self.write(workarounds.to_json())
		self.finish()


class ResultsJsonHandler(tornado.web.RequestHandler):
	def get(self):
		with open_results() as db:
			self.write(db.get_json())
		self.finish()


class ResultsHandler(tornado.web.RequestHandler):
	def get(self, batch):
		if batch.endswith(".zip"):
			batch = batch[:-4]

		f = io.BytesIO()

		with open_results() as db:
			db.get_zipfile(batch, f)

		self.set_header('Content-Type', 'application/zip')
		self.set_header("Content-Disposition", "attachment; filename=%s.zip" % batch)
		self.write(f.getvalue())
		f.close()
		self.finish()


class DeleteResultsHandler(tornado.web.RequestHandler):
	def get(self):
		with open_results() as db:
			db.clear()
		self.finish()


class PerformanceJsonHandler(tornado.web.RequestHandler):
	def get(self):
		with open_results() as db:
			self.write(db.get_performance_data_json())
		self.finish()


class SettingsHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def get(self):
		self.write(json.dumps(dict(
			looping=self.state.looping)))
		self.finish()

	def post(self):
		settings = json.loads(self.request.body)
		self.state.set_looping(settings["looping"])


def make_app(machines):
	state = GlobalState(machines)

	node_modules = "/usr/local/lib/node_modules/"

	return tornado.web.Application([
		(r"/", AppHandler, dict(state=state)),
		(r"/start", StartBatchHandler, dict(state=state)),
		(r"/websocket/(?P<batch>[^/]+)", WebSocketHandler, dict(state=state)),
		(r"/screenshot/(?P<machine>.+)", ScreenshotHandler, dict(state=state)),
		(r"/workarounds.json", WorkaroundsHandler, dict(state=state)),

		(r"/tests.json", TestsHandler, dict(state=state)),
		(r"/status.json", StatusHandler, dict(state=state)),
		(r"/results.json", ResultsJsonHandler),
		(r"/result/(?P<batch>[^/]+)", ResultsHandler),
		(r"/delete-results", DeleteResultsHandler),
		(r"/performance.json", PerformanceJsonHandler),
		(r"/settings.json", SettingsHandler, dict(state=state)),

		(r"/static/jquery/(.*)", tornado.web.StaticFileHandler, {
			"path": node_modules + "jquery"}),
		(r"/static/bulma/(.*)", tornado.web.StaticFileHandler, {
			"path": node_modules + "bulma"}),
		(r"/static/bulma-accordion/(.*)", tornado.web.StaticFileHandler, {
			"path": node_modules + "bulma-accordion"}),
		(r"/static/bulma-switch/(.*)", tornado.web.StaticFileHandler, {
			"path": node_modules + "bulma-switch"}),
		(r"/static/open-iconic/(.*)", tornado.web.StaticFileHandler, {
			"path": node_modules + "open-iconic"}),
		(r"/static/plotly.js/(.*)", tornado.web.StaticFileHandler, {
			"path": node_modules + "plotly.js"}),
		(r"/static/default/(.*)", tornado.web.StaticFileHandler, {
			"path": os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "static")}),
	])

def run_master():
	print("starting master.")
	with connect_machines() as machines:
		print("found %d machines." % len(machines))
		app = make_app(machines)
		app.listen(80)
		print("now available at localhost:80/app.")
		tornado.ioloop.IOLoop.current().start()
