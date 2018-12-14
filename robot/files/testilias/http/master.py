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
import humanize
import shutil
import traceback

import tornado.ioloop
import tornado.web
import tornado.websocket

from .discovery import connect_machines
from .utils import clear_tmp
from .args import parse_args
from testilias.driver.batch import Batch
from testilias.driver.drivers import Test
from testilias.data.result import open_results
from testilias.data.settings import Settings, Workarounds


class Looper(threading.Thread):
	def __init__(self, state, test_name, settings, workarounds, wait_time):
		threading.Thread.__init__(self)
		self.state = state
		self.test_name = test_name
		self.settings = settings
		self.workarounds = workarounds
		self.wait_time = wait_time
		self.done = False

	def run(self):
		while self.state.looping:
			try:
				if self.state.batch and self.state.batch.is_done():
					self.state.batch = None

				if self.state.batch is None:
					self.state.start_batch(self.test_name, self.settings, self.workarounds, self.wait_time)
			except:
				traceback.print_exc()

			time.sleep(1)

		self.state.looper = None
		print("looper has exited.")


class GlobalState:
	def __init__(self, machines, args):
		self.machines = machines
		self.batch = None
		self.ilias_version = None
		self.looper = None
		self.looping = False
		self.args = args
		self.ilias_url = args.ilias_url

	def get_ilias_url(self):
		return self.ilias_url

	def _fetch_ilias_version(self):
		from splinter import Browser
		from selenium.common.exceptions import WebDriverException

		try:
			log_path = "tmp/geckodriver.master.log"
			open(log_path, 'w').close()  # empty log file
			browser = Browser(headless=True, log_path=log_path, wait_time=15)
			browser.visit(self.ilias_url)

			# if this is the first startup of ILIAS, it can take quite some time, until it's available.
			bdo = browser.find_by_css("footer bdo")
			if bdo and len(bdo) == 1:
				print("found ILIAS version text '%s'" % bdo.text)
				s = re.split("\(|\)", bdo.text)
				if len(s) >= 2:
					return s[1]
		except WebDriverException as e:
			print("could not fetch ILIAS version", e)
			return None

		return None

	def get_ilias_version(self):
		if self.ilias_version is None:
			self.ilias_version = self._fetch_ilias_version()  # try again
		return self.ilias_version

	def get_ilias_version_tuple(self):
		version = self.get_ilias_version()
		if version:
			m = re.search("^v(\d+\.\d+\.\d+)", version)
			if m:
				return tuple(int(x) for x in m[1].split("."))
		raise Exception("could not retrieve ILIAS version")

	def set_looping(self, looping):
		self.looping = looping
		print("setting looping to %s." % looping)
		if self.batch and self.looping and self.looper is None:
			batch = self.batch
			self.looper = Looper(self, batch.test_name, batch.settings, batch.workarounds, batch.wait_time)
			self.looper.start()
		if not self.looping:
			self.looper = None

	def start_batch(self, test_name, settings, workarounds, wait_time):
		if self.batch and self.batch.is_done():
			self.batch = None

		ilias_version = self.get_ilias_version()  # available?
		if ilias_version is None:
			return None

		if self.batch is None:
			clear_tmp()
			self.batch = Batch(self.machines, ilias_version, test_name, settings, workarounds, wait_time)
			self.batch.configure(self.args)
			self.batch.start()

		if self.looping:
			if self.looper is None:
				print("creating new looper.")
				self.looper = Looper(self, test_name, settings, workarounds, wait_time)
				self.looper.start()
			else:
				print("reusing existing looper.")
				self.looper.workarounds = workarounds
		elif self.looper:
			print("removing looper.")
			self.looper = None

		return self.batch.get_id()


class AppHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def _get_ilias_url(self):
		ilias_url = self.state.ilias_url

		args = self.state.args
		if args.ext_ilias_port is not None:
			# differentiate between internal ILIAS docker container which we usually expose via :11145
			# and an external ILIAS installation. yes, this is a bit hacky.
			ilias_url = ilias_url.replace(
				'web:80', self.request.host.replace(':' + args.testilias_port, ':' + args.ext_ilias_port))

		return ilias_url

	def get(self):

		self.render("master.html",
			num_machines=len(self.state.machines),
			ilias_url=self._get_ilias_url(),
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

		workarounds_dict = data["workarounds"]
		Workarounds.disable_solved(workarounds_dict, self.state.get_ilias_version_tuple())

		settings = Settings(from_dict=data["settings"])
		workarounds = Workarounds(from_dict=workarounds_dict)
		test_id = data["test"]
		wait_time = 0
		batch_id = self.state.start_batch(test_id, settings, workarounds, wait_time)

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


class PreferencesHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def get(self):
		if self.state.batch:
			settings = self.state.batch.settings
			workarounds = self.state.batch.workarounds
		else:
			# use defaults
			settings = Settings()
			workarounds = Workarounds()

		fixed_workarounds = Workarounds.get_solved(
			self.state.get_ilias_version_tuple())

		self.write(json.dumps(dict(
			settings=settings.get_catalog(),
			workarounds=workarounds.get_catalog(exclude=fixed_workarounds))))
		self.finish()


class ResultsJsonHandler(tornado.web.RequestHandler):
	def get(self, what):
		with open_results() as db:
			if what == "counts":
				data = db.get_counts()
			elif what == "details":
				data = db.get_details()
			elif what == "coverage":
				data = db.get_coverage()
			elif what == "performance":
				data = db.get_performance_data()
			elif what == "longterm":
				data = db.get_longterm_data()

			self.write(json.dumps(data))

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


class SettingsHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def get(self):
		total, used, free = shutil.disk_usage(__file__)

		self.write(json.dumps(dict(
			looping=self.state.looping,
			host_disk_free=humanize.naturalsize(free))))

		self.finish()

	def post(self):
		settings = json.loads(self.request.body)
		self.state.set_looping(settings["looping"])


class ReportHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def get(self):
		with open_results() as db:
			protocols = db.get_protocols()

			nprotocols = dict()
			sep = "-" * 40
			for name, text in protocols.items():
				lines = text.split("\n")
				sections = []
				i = 0
				while i < len(lines):
					if lines[i].startswith(sep) and lines[i + 2].startswith(sep):
						sections.append(dict(name=lines[i + 1], lines=[]))
						i += 3
					else:
						sections[-1]["lines"].append(lines[i])
						i += 1
				nprotocols[name] = sections

			self.render("report.html",
				ilias_version=self.state.get_ilias_version() or "unavailable",
				results=db.get_results(),
				protocols=nprotocols)


def make_app(machines, args):
	state = GlobalState(machines, args)

	node_modules = "/usr/local/lib/node_modules/"

	return tornado.web.Application([
		(r"/", AppHandler, dict(state=state)),
		(r"/report", ReportHandler, dict(state=state)),

		(r"/start", StartBatchHandler, dict(state=state)),
		(r"/websocket/(?P<batch>[^/]+)", WebSocketHandler, dict(state=state)),
		(r"/screenshot/(?P<machine>.+)", ScreenshotHandler, dict(state=state)),
		(r"/preferences.json", PreferencesHandler, dict(state=state)),

		(r"/tests.json", TestsHandler, dict(state=state)),
		(r"/status.json", StatusHandler, dict(state=state)),
		(r"/results-(.*?).json", ResultsJsonHandler),
		(r"/result/(?P<batch>[^/]+)", ResultsHandler),
		(r"/delete-results", DeleteResultsHandler),
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
	args = parse_args()
	print("starting master with arguments:")
	for k, v in vars(args).items():
		if 'password' not in k:
			print('%s: %s' % (k, v))
		else:
			print('%s: ***' % k)
	with connect_machines() as machines:
		print("found %d machines." % len(machines))
		app = make_app(machines, args)
		app.listen(80)
		print("now available at localhost:80/app.")
		tornado.ioloop.IOLoop.current().start()
