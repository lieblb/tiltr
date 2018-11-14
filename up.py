#!/usr/bin/env python3
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
import fcntl
from threading import Thread
from collections import defaultdict

py3 = sys.version_info >= (3, 0)

parser = argparse.ArgumentParser(description='Starts up ILIAS robot test environment.')
parser.add_argument('--verbose', help='verbose output of docker compose logs', action='store_true')
parser.add_argument('--debug', help='output debugging information', action='store_true')
parser.add_argument('--n', nargs='?', const=2, type=int)
parser.add_argument('--ilias', help='YAML file that specifies an external ILIAS installation to test against')
args = parser.parse_args()


def monitor_docker_stats(tmp_path, docker_compose_name):
	stream = subprocess.Popen(["docker", "stats"], stdout=subprocess.PIPE)

	name_index = None
	cpu_index = None
	mem_index = None
	stats = defaultdict(lambda: dict(cpu=0, mem=0))

	stats_lock_path = os.path.join(tmp_path, "stats.lock")
	stats_path = os.path.join(tmp_path, "stats.json")

	while True:
		line = stream.stdout.readline()
		if py3:
			line = line.decode("utf-8")

		if not line:
			break

		row = re.split('\s\s+', line.strip())
		is_header = False

		for i, k in enumerate(row):
			k = k.replace(' ', '')
			if k == 'NAME':
				name_index = i
				is_header = True
			elif k == 'CPU%':
				cpu_index = i
				is_header = True
			elif k == 'MEM%':
				mem_index = i
				is_header = True

		if is_header:
			with open(stats_lock_path, "w") as lock_file:
				fcntl.lockf(lock_file, fcntl.LOCK_EX)
				with open(stats_path, "w") as f:
					f.write(json.dumps(stats))
			stats.clear()
		elif name_index and cpu_index and mem_index:
			name = row[name_index].split("_")
			if name and name[0] == docker_compose_name:
				if name[1] in ('web', 'db'):
					bin = 'ilias-' + name[1]
				elif name[1] == 'master' or name[1] == 'machine':
					bin = 'robot'
				else:
					bin = None

				if bin:
					stats[bin]['cpu'] += float(row[cpu_index].replace('%', ''))
					stats[bin]['mem'] += float(row[mem_index].replace('%', ''))


def set_argument_environ(args):
	entrypoint_args = []
	if args.debug:
		entrypoint_args.append('--debug')

	if args.ilias:
		embedded_ilias = False

		dir_path = os.path.dirname(os.path.realpath(__file__))
		if os.path.isabs(args.ilias):
			yaml_path = args.ilias
		else:
			yaml_path = os.path.join(dir_path, args.ilias)

		import yaml  # pip install pyyaml
		with open(yaml_path, "r") as f:
			ilias_config = yaml.load(f)

		entrypoint_args.extend([
			'--ilias-url', ilias_config['url'],
			'--ilias-admin-user', ilias_config['admin']['user'],
			'--ilias-admin-password', ilias_config['admin']['password']])

		print("Testing against external ILIAS at %s." % ilias_config['url'])
	else:
		# use our default embedded ILIAS.
		print("Testing against embedded ILIAS.")
		embedded_ilias = True
		entrypoint_args.extend([
			'--ilias-url', 'http://web:80/ILIAS',
			'--ilias-admin-user', 'root',
			'--ilias-admin-password', 'odysseus'])

	os.environ['ILIASTEST_ARGUMENTS'] = ' '.join(entrypoint_args)

	return embedded_ilias


embedded_ilias = set_argument_environ(args)

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


if embedded_ilias:
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
compose = subprocess.Popen(["docker-compose", "up", "--scale", "machine=%d" % args.n],
	stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
	def wait_for_apache():
		while True:
			line = compose.stdout.readline()
			if py3:
				line = line.decode("utf-8")
			if line != '':
				if args.verbose:
					print(line)
				if filter_log(line):
					log.write(line)
				if "apache2 -D FOREGROUND" in line:  # web server running?
					break

	wait_for_apache()

	machines = dict()
	for i in range(args.n):
		if args.verbose:
			print("looking for machine %d." % (i + 1))
		while True:
			try:
				machine_ip = subprocess.check_output([
					"docker", "inspect", "-f",
					"{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
					"%s_machine_%d" % (docker_compose_name, (i + 1))]).strip()
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
		if args.verbose:
			print("detected machine %d at %s." % ((i + 1), machine_ip))

	publish_machines(machines)

	if embedded_ilias:
		print("Preparing ILIAS. This might take a while...")
		subprocess.call(["docker-compose", "exec", "web", "ilias-startup.sh"])

	print("TestILIAS is at http://%s:11150" % socket.gethostname())

	def check_alive():
		status = subprocess.check_output([
			"docker", "inspect", "-f", "{{.State.Status}}", "%s_master_1" % docker_compose_name]).strip()
		if py3:
			status = status.decode("utf-8")
		return status != "exited"

	def print_docker_logs():
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

	monitor_thread = Thread(target=monitor_docker_stats, args=(tmp_path, docker_compose_name,))
	monitor_thread.start()

	print_docker_logs()

except KeyboardInterrupt:
	print("")
	print("Please wait while docker-compose is shutting down.")
	subprocess.call(["docker-compose", "stop"])
	monitor_thread.join()
	sys.exit()
finally:
	if not args.verbose:
		log.close()

