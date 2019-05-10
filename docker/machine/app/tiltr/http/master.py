#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
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
import sys
import pandora

import tornado.ioloop
import tornado.web
import tornado.websocket

from .discovery import connect_machines
from .utils import clear_tmp
from .args import parse_args
from tiltr.driver.batch import Batch
from tiltr.driver.drivers import PackagedTest, ILIASVersion
from tiltr.data.result import open_results
from tiltr.data.settings import Settings, Workarounds
from tiltr.data.database import DB

def _uses_embedded_ilias(args):
	return args.embedded_ilias_port is not None and int(args.embedded_ilias_port) > 0

def _query_database_table_count():
	try:
		import pymysql

		connection = pymysql.connect(
			host='db',
			user='dev',
			password='dev',
			db='ilias',
			charset='utf8mb4',
			cursorclass=pymysql.cursors.DictCursor)

		try:
			with connection.cursor() as cursor:
				sql = "SELECT COUNT(*) AS n_tables FROM information_schema.tables WHERE table_schema=%s"
				cursor.execute(sql, ('ilias',))
				n_tables = int(cursor.fetchone()["n_tables"])

		finally:
			connection.close()

		return n_tables
	except:
		return 0


class FetchILIASVersion(threading.Thread):
	def __init__(self, state):
		super().__init__()
		self.state = state

	def run(self):
		if _uses_embedded_ilias(self.state.args):
			with open('/tiltr/ILIAS/include/inc.ilias_version.php', 'r') as f:
				php_code = f.read()

			m = re.search(r'"ILIAS_VERSION"\s*,\s*"([^"]+)"', php_code)
			if m:
				version_text = m.group(1)

				m = re.search(r"^(\d+\.\d+\.\d+)", version_text)
				assert(m)
				version_tuple = tuple(int(x) for x in m[1].split("."))

				self.state.ilias_version = ILIASVersion(version_text, version_tuple)
		else:
			n_tries = 0
			while True:
				try:
					with pandora.Browser('chrome') as browser:
						driver = browser.driver

						driver.set_page_load_timeout(60)  # give up after this time
						driver.get(self.state.ilias_url)

						bdo = driver.find_element_by_css_selector("footer bdo")
						if bdo:
							print("found ILIAS version text '%s'" % bdo.text)
							s = re.split(r"\(|\)", bdo.text)
							if len(s) >= 2:
								version_text = s[1]

								m = re.search(r"^v(\d+\.\d+\.\d+)", version_text)
								assert(m)
								version_tuple = tuple(int(x) for x in m[1].split("."))

								self.state.ilias_version = ILIASVersion(version_text, version_tuple)

								return
				except:
					traceback.print_exc()
					time.sleep(2 ** min(n_tries, 5))
					n_tries += 1


class Looper(threading.Thread):
	def __init__(self, state, test, settings, workarounds, wait_time):
		super().__init__()
		self.state = state
		self.test = test
		self.settings = settings
		self.workarounds = workarounds
		self.wait_time = wait_time
		self.done = False
		self.consecutive_interaction_fails = 0

	def _check_success(self):
		success = self.state.batch.get_success()
		if success == ('FAIL', 'interaction'):
			self.consecutive_interaction_fails += 1
		else:
			self.consecutive_interaction_fails = 0

		if self.consecutive_interaction_fails >= 10:
			# stop looping after too many consecutive interaction fails.
			print("too many consecutive interaction fails")
			self.state.is_looping = False

			# usually, this happens when chrome/selenium drivers continue to
			# crash which indicates that something is wrong with our Docker
			# container. shut down in this case.
			sys.exit(1)

	def run(self):
		while self.state.is_looping:
			try:
				if self.state.batch and self.state.batch.is_done():
					self._check_success()
					self.state.batch = None

				if not self.state.is_looping:
					break

				if self.state.batch is None:
					self.state.start_batch(self.test, self.settings, self.workarounds, self.wait_time)
			except:
				traceback.print_exc()

			time.sleep(1)

		self.state.looper = None

		print("looper has exited.")


class GlobalState:
	def __init__(self, machines, args):
		self.machines = machines
		self.batch = None
		self.looper = None
		self._is_looping = False
		self.args = args
		self.ilias_url = args.ilias_url

		self.ilias_version = None

		FetchILIASVersion(self).start()

	def get_ilias_url(self):
		return self.ilias_url

	def get_ilias_version(self):
		return self.ilias_version

	@property
	def is_looping(self):
		return self._is_looping

	@is_looping.setter
	def is_looping(self, is_looping):
		print("setting is_looping to %s." % is_looping)

		self._is_looping = is_looping

		if self.batch:
			self.batch.set_recycle_users(is_looping)

		if self.batch and self.is_looping and self.looper is None:
			batch = self.batch
			self.looper = Looper(
				self, batch.test, batch.settings, batch.workarounds, batch.wait_time)
			self.looper.start()
		if not self.is_looping:
			self.looper = None

	def start_batch(self, test, settings, workarounds, wait_time):
		if self.batch and self.batch.is_done():
			self.batch = None

		ilias_version = self.get_ilias_version()  # available?
		if ilias_version is None:
			return None

		if self.batch is None:
			clear_tmp()

			self.batch = Batch(self.machines, ilias_version, test, settings, workarounds, wait_time)
			self.batch.configure(self.args)
			self.batch.set_recycle_users(self.is_looping)

			self.batch.start()

		if self.is_looping:
			if self.looper is None:
				print("creating new looper.")
				self.looper = Looper(self, test, settings, workarounds, wait_time)
				self.looper.start()
			else:
				#print("reusing existing looper.")
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
		if args.tiltr_port is not None and _uses_embedded_ilias(args):
			# differentiate between internal ILIAS docker container which we usually expose via :11145
			# and an external ILIAS installation. yes, this is a bit hacky.
			actual_host = self.request.host.replace(':' + str(args.tiltr_port), ':' + str(args.embedded_ilias_port))
			ilias_url = ilias_url.replace('web:80', actual_host)

		return ilias_url

	def get(self):
		ilias_version = self.state.get_ilias_version()

		num_db_tables = _query_database_table_count() if _uses_embedded_ilias(self.state.args) else -1

		if ilias_version is None:
			self.render(
				"booting.html",
				is_installing=num_db_tables == 0,
				num_db_tables=num_db_tables)
		else:
			self.render(
				"master.html",
				num_machines=len(self.state.machines),
				ilias_url=self._get_ilias_url(),
				ilias_version=ilias_version.text or "unavailable",
				is_installing=num_db_tables == 0)


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
		self.write(json.dumps(PackagedTest.list()))
		self.flush()


class StartBatchHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def post(self):
		data = json.loads(self.request.body)

		workarounds_dict = data["workarounds"]
		Workarounds.disable_solved(
			workarounds_dict, self.state.get_ilias_version().as_tuple())

		settings = Settings(from_dict=data["settings"])
		workarounds = Workarounds(from_dict=workarounds_dict)
		test_id = data["test"]
		wait_time = 0
		batch_id = self.state.start_batch(
			PackagedTest(test_id), settings, workarounds, wait_time)

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
			self.state.get_ilias_version().as_tuple())

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
			is_looping=self.state.is_looping,
			host_disk_free=humanize.naturalsize(free),
			db_size=humanize.naturalsize(DB.get_size()))))

		self.finish()

	def post(self):
		settings = json.loads(self.request.body)
		self.state.is_looping = settings["is_looping"]


class ReportHandler(tornado.web.RequestHandler):
	def initialize(self, state):
		self.state = state

	def get(self):
		with open_results() as db:
			protocols = db.get_files()

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
				ilias_version=self.state.get_ilias_version().text or "unavailable",
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
	], template_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "html"))


def run_master():
	args = parse_args()
	print("starting master with arguments:")
	for k, v in vars(args).items():
		if 'password' not in k:
			print('%s: %s' % (k, v))
		else:
			print('%s: ***' % k)
	with connect_machines() as machines:
		expose_port = 8080
		print("found %d machines." % len(machines))
		app = make_app(machines, args)
		app.listen(expose_port)
		print("now available at localhost:%d/app." % expose_port)
		tornado.ioloop.IOLoop.current().start()
