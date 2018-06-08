#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import subprocess
import os
import requests
import time
import json


def verify_hello(machine):
	for retries in range(5):
		try:
			r = requests.post("http://%s:8888/hello/" % machine, data={})
			if r.status_code == 200 and r.text == "HelloToo":
				print("hello from %s." % machine)
				return True
		except requests.exceptions.ConnectionError as e:
			pass
		time.sleep(1)
	return False


def detect_machines():
	base = os.path.dirname(__file__)
	machines_path = os.path.join(base, "..", "..", "tmp", "machines.json")
	while not os.path.isfile(machines_path):
		print("machines.json not found. waiting 1s.")
		time.sleep(1)
	with open(machines_path, "r") as f:
		machines = json.loads(f.read())
	return machines


class Machines:
	def __init__(self):
		self.process = None
		self.parallel = False

	def __enter__(self):
		machines = detect_machines()

		self.process = None
		self.parallel = True

		if self.parallel and not machines:
			print("no test machines found. running in non-parallel mode. use docker --scale to start test machines.")
			self.parallel = False

		if not self.parallel:
			process = subprocess.Popen(("python", os.path.join(os.path.dirname(__file__), "machine.py")), stdout=subprocess.PIPE)
			assert process.stdout.readline().strip() == "HELLO."
			self.process = process

			machines = dict(machine_1="127.0.0.1")

		print("waiting for machines to start up.")

		responsive = dict()
		for name, ip in machines.items():
			if verify_hello(ip):
				responsive[name] = ip

		if len(responsive) < len(machines):
			print("!! %d machines did not respond and will be excluded from test runs." % (len(machines) - len(responsive)))

		print("%d machines are up and running." % len(responsive))

		return responsive

	def __exit__(self, *args):
		if not self.parallel:
			if self.process:
				self.process.terminate()


def connect_machines():
	return Machines()