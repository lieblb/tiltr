#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import subprocess
import os
import sys
import shutil
import zipfile
import argparse
import re
import time
import json
import socket

py3 = sys.version_info >= (3, 0)

parser = argparse.ArgumentParser(description='Starts up ILIAS robot test environment.')
parser.add_argument('--verbose', help='verbose info with docker compose logs', action='store_true')
parser.add_argument('--n', nargs='?', const=2, type=int)
args = parser.parse_args()

verbose = False

base = os.path.dirname(os.path.realpath(__file__))
os.chdir(base)  # important for docker-compose later
_, docker_compose_name = os.path.split(base)

tmp_path = os.path.join(base, "headless", "robot", "tmp")
if not os.path.exists(tmp_path):
	os.makedirs(tmp_path)

machines_path = os.path.join(tmp_path, "machines.json")
if os.path.isfile(machines_path):
	os.remove(machines_path)

def publish_machines(machines):
	with open(machines_path + ".tmp", "w") as f:
		f.write(json.dumps(machines))
	os.rename(machines_path + ".tmp", machines_path)  # hopefully atomic

ilias_path = os.path.realpath(os.path.join(base, "web", "ILIAS"))
if not os.path.isdir(ilias_path) or not os.path.exists(os.path.join(ilias_path, "ilias.php")):
	print("please put the ILIAS source code you want to test against under %s." % ilias_path)
	print("note that the code you put there will get modified into a default test client.")
	print("aborting.")
	sys.exit(1)

# instrument ILIAS source code for test runner.

shutil.copyfile(
	os.path.join(base, "web", "custom", "ilias.ini.php"),
	os.path.join(base, "web", "ILIAS", "ilias.ini.php"))

client_zip = zipfile.ZipFile(os.path.join(base, "web", "custom", "data.zip"), 'r')
client_zip.extractall(os.path.join(base, "web", "ILIAS"))
client_zip.close()

# start up docker.
compose = subprocess.Popen(["docker-compose", "up", "--scale", "machine=%d" % args.n], stdout=subprocess.PIPE)
print("Waiting for docker-compose to start up.")

if not args.verbose:
	print("docker-compose log files are at %s." % os.path.realpath("docker-compose.log"))
	log = open("docker-compose.log", "w")
else:
	log = sys.stdout


def escape_ansi(line):
	ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]')
	return ansi_escape.sub('', line)


def filter_log(s):
	s = escape_ansi(s)
	return s.startswith("machine_")


try:
	while True:
		line = compose.stdout.readline()
		if py3:
			line = line.decode("utf-8")
		if line != '':
			if verbose:
				print(line)
			if filter_log(line):
				log.write(line)
			if "apache2 -D FOREGROUND" in line:  # web server running?
				break

	machines = dict()
	for i in range(args.n):
		if verbose:
			print("looking for machine %d." % (i + 1))
		while True:
			try:
				machine_ip = subprocess.check_output([
					"docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", "%s_machine_%d" % (docker_compose_name, (i + 1))]).strip()
				if len(str(machine_ip)) == 0:
					print("failed to lookup machine %d. shutting down." % i)
					subprocess.call(["docker-compose", "stop"])
					sys.exit()
				break
			except subprocess.CalledProcessError:
				time.sleep(1)
		if py3:
			machine_ip = machine_ip.decode("utf-8")
		machines["machine_%d" % (1 + i)] = machine_ip
		if verbose:
			print("detected machine %d at %s." % ((i + 1), machine_ip))

	publish_machines(machines)

	print("preparing ILIAS...")
	subprocess.call(["docker-compose", "exec", "web", "ilias-startup.sh"])

	print("TestILIAS is at http://%s:11150" % socket.gethostname())

	def check_alive():
		status = subprocess.check_output(["docker", "inspect", "-f", "{{.State.Status}}", "%s_master_1" % docker_compose_name]).strip()
		if py3:
			status = status.decode("utf-8")
		return status != "exited"

	while True:
		if not check_alive():
			print("master has shut down unexpectedly. try a docker logs %s_master_1" % docker_compose_name)
			subprocess.call(["docker-compose", "stop"])
			sys.exit()
		line = compose.stdout.readline()
		if py3:
			line = line.decode("utf-8")
		if line != '':
			if filter_log(line):
				log.write(line)

except KeyboardInterrupt:
	print("Please wait while docker-compose is shutting down.")
	subprocess.call(["docker-compose", "stop"])
	sys.exit()
finally:
	if not args.verbose:
		log.close()

