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
import signal
from threading import Thread
from collections import defaultdict

py3 = sys.version_info >= (3, 0)

monitor_thread = None
request_quit = False

parser = argparse.ArgumentParser(description='Starts up the TestILIAS test environment.')

parser.add_argument('command', nargs='?', default='start')

parser.add_argument('--verbose', help='verbose output of docker compose logs', action='store_true')
parser.add_argument('--debug', help='output debugging information', action='store_true')
parser.add_argument('--n', nargs='?', const=1, type=int, default=1)
parser.add_argument('--ilias', help='YAML file that specifies an external ILIAS installation to test against')
parser.add_argument('--fork', help='fork up.py', action='store_true')
parser.add_argument('--port', help='port to run TestILIAS on', nargs='?', const=1, type=int, default=11150)
parser.add_argument('--embedded-ilias-port', help='port to run embedded ILIAS on', nargs='?', const=1, type=int, default=11145)
parser.add_argument('--rebuild', help='rebuild docker containers', action='store_true')
parser.add_argument('--rebuild-no-cache', help='rebuild docker containers without cache', action='store_true')

#parser.add_argument('--stop', help='stop all docker containers', action='store_true')
#parser.add_argument('--ps', help='list all docker containers', action='store_true')

args = parser.parse_args()

os.environ['TESTILIAS_PORT'] = str(args.port)
os.environ['EMBEDDED_ILIAS_PORT'] = str(args.embedded_ilias_port)

if args.fork:
	pid = os.fork()
	if pid != 0:
		print("started up.py on pid %d." % pid)
		sys.exit(0)

def monitor_docker_stats(tmp_path, docker_compose_name):
	stream = subprocess.Popen(["docker", "stats"], stdout=subprocess.PIPE)

	name_index = None
	cpu_index = None
	mem_index = None
	stats = defaultdict(lambda: dict(cpu=0, mem=0))

	stats_lock_path = os.path.join(tmp_path, "stats.lock")
	stats_path = os.path.join(tmp_path, "stats.json")

	def parse_percentage(s):
		if '%' in s:
			return float(s.replace('%', ''))
		else:
			return 0

	while not request_quit:
		line = stream.stdout.readline()
		if py3:
			line = line.decode("utf-8")

		if not line:
			break

		row = re.split(r'\s\s+', line.strip())
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
					stats[bin]['cpu'] += parse_percentage(row[cpu_index])
					stats[bin]['mem'] += parse_percentage(row[mem_index])


def instrument_ilias():
	base = os.path.dirname(os.path.realpath(__file__))

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

	return ilias_path


def set_argument_environ(args):
	entrypoint_args = []
	if args.debug:
		entrypoint_args.append('--debug')

	entrypoint_args.extend(['--testilias-port', str(args.port)])

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
		ilias_path = instrument_ilias()
		print("Testing against embedded ILIAS located at %s." % ilias_path)
		embedded_ilias = True
		entrypoint_args.extend([
			'--ilias-url', 'http://web:80/ILIAS?client_id=ilias',
			'--ilias-admin-user', 'root',
			'--ilias-admin-password', 'odysseus'])
		entrypoint_args.extend(['--ext-ilias-port', str(args.embedded_ilias_port)])

	os.environ['ILIASTEST_ARGUMENTS'] = ' '.join(entrypoint_args)

	return embedded_ilias


embedded_ilias = set_argument_environ(args)

if args.command == 'stop':
	subprocess.call(["docker-compose", "stop"])
	sys.exit(0)
elif args.command == 'ps':
	subprocess.call(["docker-compose", "ps"])
	sys.exit(0)
elif args.command != 'start':
	print("illegal command.")
	sys.exit(1)

if args.rebuild_no_cache:
	subprocess.call(["docker-compose", "build", "--no-cache"])
elif args.rebuild:
	subprocess.call(["docker-compose", "build"])

base = os.path.dirname(os.path.realpath(__file__))
os.chdir(base)  # important for docker-compose later
_, docker_compose_name = os.path.split(base)

tmp_path = os.path.join(base, "robot", "files", "tmp")
if not os.path.exists(tmp_path):
	os.makedirs(tmp_path)

machines_path = os.path.join(tmp_path, "machines.json")
if os.path.isfile(machines_path):
	os.remove(machines_path)


def publish_machines(machines):
	with open(machines_path + ".tmp", "w") as f:
		f.write(json.dumps(machines))
	os.rename(machines_path + ".tmp", machines_path)  # hopefully atomic
	if args.verbose:
		print("wrote machines.json at %s" % machines_path)


def check_errors(pipe, output):
	with pipe:
		for line in iter(pipe.readline, b''):
			s = line.decode('utf8').strip()
			if s:
				print('.', end='', flush=True)
				output.append('# ' + s)


# start up docker.
compose_stderr = []
compose = subprocess.Popen(
	["docker-compose", "up", "--scale", "machine=%d" % args.n],
	stdout=subprocess.PIPE,
	stderr=subprocess.PIPE,
	bufsize=1)

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


def terminate():
	global request_quit
	if request_quit:
		return
	request_quit = True
	subprocess.call(["docker-compose", "stop"])
	if monitor_thread:
		monitor_thread.join()
	print('')

def on_terminate_signal(signal, stack):
	terminate()

signal.signal(signal.SIGTERM, on_terminate_signal)

try:
	print("Waiting for docker-compose to start up.", end='')
	Thread(target=check_errors, args=[compose.stderr, compose_stderr]).start()

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
			elif request_quit:
				sys.exit(0)
			elif compose_stderr:
				print("exiting due to Docker errors:")
				print("\n".join(compose_stderr))
				sys.exit(1)


	wait_for_apache()
	print("")

	def find_and_publish_machines():
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
						terminate()
						sys.exit(1)
					break
				except subprocess.CalledProcessError:
					time.sleep(1)
			if py3:
				machine_ip = machine_ip.decode("utf-8")
			machines["machine_%d" % (1 + i)] = machine_ip
			if args.verbose:
				print("detected machine %d at %s." % ((i + 1), machine_ip))

		publish_machines(machines)


	def get_exposed_port(docker_name):
		return subprocess.check_output([
			"docker", "inspect", "-f",
			"{{range $p, $conf := .NetworkSettings.Ports}} {{(index $conf 0).HostPort}} {{end}}",
			docker_name]).strip()


	find_and_publish_machines()

	if embedded_ilias:
		print("Preparing ILIAS. This might take a while...")
		subprocess.call(["docker-compose", "exec", "web", "ilias-startup.sh"])
		print("Done.")

	print("TestILIAS is at http://%s:%d" % (socket.gethostname(), args.port))

	def check_alive():
		status = subprocess.check_output([
			"docker", "inspect", "-f", "{{.State.Status}}", "%s_master_1" % docker_compose_name]).strip()
		if py3:
			status = status.decode("utf-8")
		return status != "exited"

	def print_docker_logs():
		while True:
			if not check_alive():
				if not request_quit:
					print("master has shut down unexpectedly. try to run: docker logs %s_master_1" % docker_compose_name)
				terminate()
				break
			line = compose.stdout.readline()
			if py3:
				line = line.decode("utf-8")
			if line != '':
				if filter_log(line):
					log.write(line)

	def get_docker_container_log_path(container_name):
		path = subprocess.check_output([
			"docker", "inspect", "-f", "{{.LogPath}}", '%s_%s' % (docker_compose_name, container_name)]).strip()
		if py3:
			path = path.decode("utf-8")
		return path

	def get_logs_size():
		size = 0

		size += get_docker_container_log_size('master_1')

		for m in machines.keys():
			size += get_docker_container_log_size(m)

		size += get_docker_container_log_size('web_1')
		size += get_docker_container_log_size('db_1')


	monitor_thread = Thread(target=monitor_docker_stats, args=(tmp_path, docker_compose_name,))
	monitor_thread.start()

	print_docker_logs()

except KeyboardInterrupt:
	print("")
	print("Please wait while docker-compose is shutting down.", end='', flush=True)
	terminate()
finally:
	if not args.verbose:
		log.close()

sys.exit(0)
