#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from typing import Any, DefaultDict, Union

import asyncio
import requests
import json
import traceback
import random as rnd
import time
import datetime
import uuid
import base64
import io
import os
import glob
import tempfile
import itertools
from decimal import *

from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing import Lock
import threading

from collections import defaultdict
from contextlib import contextmanager

import selenium
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains

from openpyxl import load_workbook
from texttable import Texttable

from tiltr.data.exceptions import *
from tiltr.data.result import Result, Origin, MaybeDecimal
from tiltr.data.result import open_results
from tiltr.data.workbook import workbook_to_result, check_workbook_consistency
from tiltr.data.context import RandomContext
from tiltr.question.coverage import Coverage

from tiltr.question import *  # needed for pickling
from tiltr.driver.exam_configuration import * # needed for pickling

import pandora

from .commands import TakeExamCommand
from .drivers import UsersBackend, UsersFactory, UserDriver, ImportedTest, Marks, ILIASDriver
from .utils import wait_for_page_load, run_interaction


class PostProcessingRound:
	def __init__(self, index: int, is_reimport: bool):
		self.index = index
		self.is_reimport = is_reimport


monitor_mutex = Lock()


def encode_success(success):
	return "/".join(success)


def take_exam(args):
	asyncio.set_event_loop(asyncio.new_event_loop())

	command = args["command"]
	machine = command.machine
	batch_id = args["batch_id"]
	report = args["report"]

	result_json = None
	report("master", "passing take_exam to %s." % machine)

	try:
		r = requests.post("http://%s:8888/start/%s" % (machine, batch_id),
			data={"command_json": command.to_json()})
		if r.status_code != 200:
			raise InteractionException("start call failed: %s" % r.status_code)

		report("master", "test started on %s." % machine)

		index = 0

		while result_json is None:
			# we don't want too much traffic for updating machine states. only check
			# one at a time.
			monitor_mutex.acquire()
			try:
				time.sleep(1)
				r = requests.get("http://%s:8888/monitor/%s/%d" % (machine, batch_id, index))
			finally:
				monitor_mutex.release()

			if r.status_code != 200:
				raise InteractionException("monitor call failed: %s" % r.status_code)
		
			messages = json.loads(r.text)

			for command, payload in messages:
				if command == "ECHO":
					report(machine, payload)
				elif command == "DONE":
					result_json = payload
				elif command == "ERROR":
					raise Exception(payload)
				else:
					raise InteractionException("unknown command %s" % command)

			index += len(messages)

	except TiltrException as e:
		traceback.print_exc()
		try:
			report("error", "machine %s failed." % machine)
			report("traceback", traceback.format_exc())
		except:
			print("report failed.")
		return Result.from_error(Origin.recorded, e.get_error_domain(), traceback.format_exc())

	except requests.exceptions.ConnectionError:
		traceback.print_exc()
		try:
			report("error", "machine %s failed." % machine)
			report("traceback", traceback.format_exc())
		except:
			print("report failed.")
		return Result.from_error(Origin.recorded, ErrorDomain.interaction, traceback.format_exc())

	except:
		traceback.print_exc()
		try:
			report("error", "machine %s failed." % machine)
			report("traceback", traceback.format_exc())
		except:
			print("report failed.")
		return Result.from_error(Origin.recorded, ErrorDomain.integrity, traceback.format_exc())

	report("master", "received take_exam results from %s." % machine)
	return Result(from_json=result_json)


def _patch_exam_name(path, new_title, output_dir):
	import zipfile
	import os
	import re
	import xml.etree.ElementTree as ET
	from functools import partial

	def patch_xml(patch, data):
		root = ET.fromstring(data.decode('utf8'))
		patch(root)
		return ET.tostring(root, encoding='utf8', method='xml')

	def patch_tst(root):
		for element in root.findall(".//Title"):
			element.text = new_title

	def patch_qti(root):
		for assessment in root.findall(".//assessment"):
			assessment.set("title", new_title)

	with zipfile.ZipFile(path, 'r') as zip_ref:

		export_name, _ = os.path.split(zip_ref.namelist()[0])

		def full_xml_name(name):
			return "%s/%s.xml" % (export_name, name)

		modifiers = dict()
		modifiers[full_xml_name(export_name)] = partial(patch_xml, patch_tst)
		modifiers[full_xml_name(export_name.replace('_tst_', '_qti_'))] = partial(patch_xml, patch_qti)

		modified_path = os.path.join(output_dir, "%s.zip" % export_name)

		with zipfile.ZipFile(modified_path, 'w') as out_zip_ref:
			for name in zip_ref.namelist():
				data = zip_ref.read(name)
				if name in modifiers:
					data = modifiers[name](data)

				out_zip_ref.writestr(name, data)

	return modified_path


class MasterContext:
	def __init__(self, batch, protocol):
		self.batch = batch
		self.protocol = protocol
		self.driver = None
		self.screenshot_url = None
		self.language = None

	def report(self, message):
		try:
			url = self.driver.current_url
			if url != self.screenshot_url:
				self.batch.screenshot = self.driver.get_screenshot_as_base64()
				self.screenshot_url = url
		except:
			self.batch.report("master", "failed to create screenshot.")

		self.batch.report("master", message)
		self.protocol(message)


def remove_trailing_zeros(s):
	parts = s.split(".")
	if len(parts) == 2 and all(x == "0" for x in parts[1]):
		# e.g. 2.00 -> 2
		return parts[0]
	elif len(parts) == 2 and s[-1] == "0":
		# e.g. 2.10 -> 2.1
		while s[-1] == "0":
			s = s[:-1]
		return s
	else:
		return s


def get_most_severe_error_domain(results):
	return most_severe(r.get_most_severe_error_domain() for r in results)


def create_temp_test_name():
	now = datetime.datetime.now()
	now_str = now.strftime("%Y_%m_%d_%H_%M_%S")
	return "TiltR_temp_%s_%d" % (now_str, now.microsecond)


class Run:
	protocols: DefaultDict[str, Union[list, DefaultDict[str, list]]]

	def __init__(self, batch):
		self.success = ("FAIL", "unknown")

		self.performance_data = []
		self.coverage = Coverage()
		self.users = []
		self.users_factory = batch.users_factory
		self.protocols = defaultdict(list)
		self.protocols["postprocessing"] = defaultdict(list)
		self.files = dict()
		self.test_version = 1
		self.test_url = None
		self.language = None

		self.batch = batch
		self.machines = batch.machines
		self.settings = batch.settings
		self.workarounds = batch.workarounds
		self.batch_id = batch.batch_id
		self.ilias_version = batch.ilias_version
		self.wait_time = batch.wait_time

		self.test = batch.test
		self.questions = self.test.cache.questions
		self.exam_configuration = self.test.cache.exam_configuration

	def _make_protocol(self):
		sections = [
			"header",
			"log",

			"preferences/workarounds",
			"preferences/settings",
			"mark_schema"]

		parts = list()

		for section in sections:
			part = self.protocols[section]
			if part:
				if section == "header":
					parts.extend(part)
					parts.append("")
				else:
					parts.append("# " + section.upper())
					parts.append("")
					parts.extend(part)
					parts.append("")

		return "\n".join(parts)

	def _check_results(
		self, processing_round: PostProcessingRound, master, test_driver, workbook, all_recorded_results):

		all_assertions_ok = True

		usernames = [user.get_username() for user in self.users]
		tab_stats = dict()

		tab_stats["statistics_tab"] = test_driver.get_results_from_statistics_tab(usernames)
		if not self.workarounds.ignore_wrong_results_in_results_tab:
			tab_stats["results_tab"] = test_driver.get_results_from_results_tab(usernames)
		web_answers = test_driver.get_answers_from_details_view(self.questions)

		pdfs = test_driver.export_pdf(self.files)
		prefix = 'reimport/' if processing_round.is_reimport else 'original/'

		protocol = self._get_postprocessing_protocol(processing_round, "verification")

		for user, recorded_result in zip(self.users, all_recorded_results):
			master.report("checking results for user %s." % user.get_username())

			# fetch and check results.
			assert self.questions is not None

			ilias_result = workbook_to_result(
				workbook, user.get_username(), self.questions, self.workarounds, self.ilias_version, master.report)

			# check score via statistics gui as well.
			for channel, stats in tab_stats.items():
				ilias_result.add(
					(channel, "score_reached"),
					Result.format_score(stats[user.get_username()].score))
				ilias_result.add(
					(channel, "score_maximum"),
					Result.format_score(stats[user.get_username()].maximum_score))
				ilias_result.add(
					(channel, "percentage_reached"),
					Result.format_percentage(stats[user.get_username()].percentage, self.workarounds))
				ilias_result.add(
					(channel, "short_mark"),
					stats[user.get_username()].short_mark)

			# add scores from pdf.
			for question_title, question_data in pdfs[user.get_username()].scores.items():
				title = Result.normalize_question_title(question_title)
				for k, v in question_data.items():
					ilias_result.add(("pdf", "question", title, k), v)

			# save pdf in tiltr database.
			self.files[prefix + "%s.pdf" % user.get_username()] = pdfs[user.get_username()].bytes

			# perform response checks.
			def report(message):
				if message:
					protocol.append(message)

			protocol.append("")
			protocol_title = "## " + user.get_username() + " "
			protocol.append(protocol_title + ("#" * (80 - len(protocol_title))))
			protocol.append("")

			if not recorded_result.check_against(ilias_result, report, self.workarounds):
				message = "verification failed for user %s." % user.get_username()
				master.report(message)
				self._save_test(test_driver, "verification")
				self.protocols["log"].append("[fail] " + message)
				all_assertions_ok = False

			if not processing_round.is_reimport:
				# add coverage info.
				for question_title, answers in ilias_result.get_answers().items():
					question = self.questions[question_title]
					question.add_export_coverage(self.coverage, answers, self.language)

		return all_assertions_ok

	def _propagate_score_changes(self, all_recorded_results, context):
		maximum_score = Decimal(0)
		for question in self.questions.values():
			maximum_score += question.get_maximum_score(context)

		# recompute (expected) reached scores and marks, i.e. values we will check against.
		for result in all_recorded_results:
			reached_score = Decimal(0)
			for value in result.scores():
				if value.valid():
					reached_score += self.exam_configuration.clip_answer_score(value.to_decimal())

			reached_percentage = Result.score_percentage(MaybeDecimal(reached_score), maximum_score)

			for channel in ("xls", "statistics_tab", "results_tab"):
				if self.workarounds.ignore_wrong_results_in_results_tab and channel == "results_tab":
					continue
				result.update(
					(channel, "score_maximum"),
					Result.format_score(maximum_score))
				result.update(
					(channel, "score_reached"),
					Result.format_score(reached_score))
				if channel != "xls":
					result.update(
						(channel, "percentage_reached"),
						Result.format_percentage(reached_percentage, context.workarounds))

			mark = Marks(self.exam_configuration.marks).lookup(reached_percentage)
			for channel in ("xls", "statistics_tab", "results_tab"):
				if self.workarounds.ignore_wrong_results_in_results_tab and channel == "results_tab":
					continue
				result.update((channel, "short_mark"), str(mark.short).strip())

	def _get_postprocessing_protocol(self, processing_round: PostProcessingRound, readjustment_type):
		protocol_name = "%02d_%s%s" % (
			processing_round.index + 1,
			readjustment_type,
			"_after_reimport" if processing_round.is_reimport else "")
		return self.protocols["postprocessing"][protocol_name + ".txt"]

	def _apply_manual_scoring(self, processing_round, master, test_driver, all_recorded_results):
		context = RandomContext(
			self.questions, self.settings, self.workarounds, self.language, self.ilias_version.as_tuple())

		protocol = self._get_postprocessing_protocol(processing_round, "manual_scoring")

		for question_title, question in self.questions.items():
			if question.can_score_manually():
				protocol.append("manual scores for question " + question_title)
				protocol.append("")

				with wait_for_page_load(master.driver):
					test_driver.goto_manual_scoring()

				max_score = question.get_maximum_score(context)
				manual_scores = dict()

				for user, result in zip(self.users, all_recorded_results):
					accuracy = 4
					score = min(Decimal(context.random.randint(
						0, (1 + int(max_score)) * accuracy)) / Decimal(accuracy), max_score)
					for key in Result.reached_score_keys(question.title):
						result.update(key, Result.format_score(score))
					for key in Result.maximum_score_keys(question.title):
						result.update(key, Result.format_score(max_score))

					username = user.get_username()
					manual_scores[username] = score

					protocol.append("%s: %s" % (username, score))

				protocol.append("")
				test_driver.apply_manual_scoring(question.title, manual_scores)

		self._propagate_score_changes(all_recorded_results, context)

	def _apply_readjustment(self, processing_round, master, test_driver, all_recorded_results):
		# note that this will destroy the original test's scores. usually we should have copied
		# this test and this should only run on a temporary copy.

		context = RandomContext(
			self.questions, self.settings, self.workarounds, self.language, self.ilias_version.as_tuple())

		protocol = self._get_postprocessing_protocol(processing_round, "readjustment")

		def report(s):
			if isinstance(s, Texttable):
				for line in s.draw().split('\n'):
					report(line)
			else:
				protocol.append(s)
				if s:
					master.report(s)

		index = 0
		retries = 0
		modified_questions = set()

		def close_stats_window():
			if self.ilias_version < (5, 4):
				master.driver.execute_script("""
				(function() {
					var overlay = document.getElementsByClassName("ilOverlay")[0];
					if (overlay) {
						overlay.style.display = "none";
					}
				}())
				""")

		while True:
			with wait_for_page_load(master.driver):
				test_driver.goto_scoring_adjustment()

			links = []
			for a in master.driver.find_element_by_name("questionbrowser").find_elements_by_css_selector("table a"):
				question_title = a.text.strip()
				if question_title in self.questions:
					links.append((a, self.questions[question_title]))

			if index >= len(links):
				break

			link, question = links[index]
			with wait_for_page_load(master.driver):
				link.click()

			close_stats_window()

			old_maximum_score = question.get_maximum_score(context)

			try:
				while True:
					report('')
					report('### QUESTION "%s"' % question.title.upper())
					report('')

					# gather all given answer keys for this answer across all users.
					actual_answers = defaultdict(list)
					for result in all_recorded_results:
						for k, v in result.gather(Result.key("question", question.title, "answer")).items():
							actual_answers[k].append(v)

					report("gathered answers:")
					for k, v in actual_answers.items():
						report('%s: %s' % (k, str(v)))
					report('')

					readjusted, removed_answer_keys = question.readjust_scores(
						master.driver, actual_answers, context, report)

					if not readjusted:
						# this question type does not support readjustments.
						break

					modified_questions.add(question.title)

					master.report("saving.")

					with wait_for_page_load(master.driver):
						if self.ilias_version >= (5, 4):
							save_element = master.driver.find_element_by_name("cmd[saveQuestion]")
						else:
							save_element = master.driver.find_element_by_name("cmd[savescoringfortest]")

						# without scrolling into view, clicking save will sometimes produce a
						# WebDriverException ("element is not clickable at point")
						master.driver.execute_script("arguments[0].scrollIntoView();", save_element)

						#chain = ActionChains(master.driver)
						#chain.move_to_element(save_element).click().perform()

						master.driver.execute_script("$(arguments[0]).click();", save_element)

					# save_element.click()

					close_stats_window()

					if master.driver.find_elements_by_css_selector(".alert-danger"):
						maximum_score = question.get_maximum_score(context)

						if maximum_score > 0:
							raise InteractionException(
								"ILIAS rejected new scores even though they are valid (%f)." % maximum_score)
						else:
							report("ILIAS rejected invalid new scores.")

					elif self.ilias_version >= (5, 4) or master.driver.find_elements_by_css_selector(".alert-success"):
						# readjustment seems to have been applied successfully.

						# in certain cases (matching questions), reassessment can remove already given answers
						# from the result sets.
						for key in removed_answer_keys:
							for result in all_recorded_results:
								result.remove(Result.key("question", question.title, "answer", key))

						break

					else:
						# we should either see a success or failure alert.

						raise InteractionError("readjustment save went wrong, could not determine status.")

			except TimeoutException:
				retries += 1
				if retries >= 1:
					raise InteractionException("failed to readjust scores. giving up.")
				else:
					master.report("readjustment failed, retrying.")
				continue

			report("")
			report("maximum score went from %s to %s." % (old_maximum_score, question.get_maximum_score(context)))
			question.explain_maximum_score(context, report)

			index += 1
			retries = 0

		# recompute user score's for all questions.
		report("")
		report("## REASSESSING EXPECTED USER SCORES")
		report("")

		for user, result in zip(self.users, all_recorded_results):
			report("### USER %s" % user.get_username())

			new_scores_table = Texttable()
			new_scores_table.set_deco(Texttable.HEADER)
			new_scores_table.set_cols_dtype(['a', 'a'])

			answers_table = Texttable()
			answers_table.set_deco(Texttable.HEADER)
			answers_table.set_cols_dtype(['a', 'a'])

			any_readjusted = False

			for question_title, question in self.questions.items():

				if question_title not in modified_questions:
					continue

				any_readjusted = True

				score = question.compute_score_from_result(result, context)
				score = self.exam_configuration.clip_answer_score(score)
				score = remove_trailing_zeros(str(score))

				for key in Result.reached_score_keys(question_title):
					result.update(key, Result.format_score(score))
				for key in Result.maximum_score_keys(question_title):
					result.update(key, Result.format_score(question.get_maximum_score(context)))

				new_scores_table.add_row([question_title, score])

				answers_table.add_row(["QUESTION " + question_title, ""])
				for key, value in result.properties.items():
					if key[0] == "question" and key[1] == question_title and key[2] == "answer":
						dimensions = key[3:]
						if len(dimensions) == 1:
							dimension = str(dimensions[0])
						else:
							dimension = str(list(map(lambda x: '"%s"' % str(x), dimensions)))
						answers_table.add_row([dimension, value])
				answers_table.add_row(["", ""])

			if any_readjusted:
				report("recomputed these scores:")
				for line in new_scores_table.draw().split("\n"):
					report(line)
				report("")
				report("based on these answers:")
				for line in answers_table.draw().split("\n"):
					report(line)
				report("")

		self._propagate_score_changes(all_recorded_results, context)

	def _users_backend(self, master):
		ilias_driver = ILIASDriver(
			master.driver,
			self.batch.ilias_url, self.ilias_version,
			self.workarounds, self.settings,
			master.report)

		master.report("_users_backend called")

		return lambda: UsersBackend(ilias_driver, master.report)

	def prepare(self, master, test_driver):
		self.language = master.language
		master.report("running with admin language '%s'" % self.language)

		master.report("running with workarounds:")
		self.workarounds.print_status(master.report)
		self.workarounds.print_status(self.protocols["preferences/workarounds"].append)

		master.report("running with settings:")
		self.settings.print_status(master.report)
		self.settings.print_status(self.protocols["preferences/settings"].append)

		header = self.protocols["header"]
		header.append("Tested on ILIAS %s." % self.ilias_version.text)
		header.append('Using test "%s".' % self.test.get_title())

		ilias_driver = ILIASDriver(
			master.driver,
			self.batch.ilias_url, self.ilias_version,
			self.workarounds, self.settings,
			master.report)

		self.protocols["settings"].extend(
			ilias_driver.verify_admin_settings())

		self.users = self.users_factory.acquire(self._users_backend(master))

		if not test_driver.goto_or_fail():
			# if test does not exist, add it first.
			test_driver.import_test_from_template()
		else:
			test_driver.delete_all_participants()

		# grab exam configuration from UI.
		if self.exam_configuration is None:
			self.exam_configuration = test_driver.parse_exam_configuration()
			self.test.cache.exam_configuration = self.exam_configuration

		# grab question definitions from UI.
		if self.questions is None:
			self.questions = test_driver.parse_question_definitions(self.settings)
			self.test.cache.questions = self.questions

		# now configure test.
		test_driver.configure_test(self.workarounds, self.exam_configuration)

		# print out sorted mark scheme.
		table = Texttable()
		table.set_deco(Texttable.HEADER)
		table.set_cols_dtype(['f', 't', 't'])
		table.add_row(['percentage', 'grade (short)', 'grade (long)'])

		for mark in sorted(self.exam_configuration.marks, key=lambda x: float(x[0])):
			table.add_row(mark)

		for line in table.draw().split('\n'):
			self.protocols["mark_schema"].append(line)

		# find URL of test, since this saves us a lot of time in the clients.
		self.test_url = test_driver.get_test_url()

	def run_exams(self):
		# now run exams.
		take_exam_args = []
		for i, machine, user in zip(range(len(self.users)), self.machines.values(), self.users):
			take_exam_args.append(
				dict(
					batch_id=self.batch_id,
					report=self.report,
					command=TakeExamCommand(
						ilias_url=self.batch.ilias_url,
						verify_ssl=self.batch.verify_ssl,
						ilias_version=self.batch.ilias_version.as_tuple(),
						machine=machine,
						machine_index=i + 1,
						username=user.get_username(),
						password=user.get_password(),
						test_id=self.test.get_id(),
						test_url=self.test_url,
						questions=self.questions,
						exam_configuration=self.exam_configuration,
						settings=self.settings,
						workarounds=self.workarounds,
						wait_time=self.wait_time,
						admin_lang=self.language)))

		pool = ThreadPool(len(self.users))
		try:
			all_recorded_results = pool.map(take_exam, take_exam_args)
			self.report("master", "waiting for results.")
			pool.close()
			pool.join()
			self.report("master", "all results arrived.")
			return all_recorded_results
		except:
			traceback.print_exc()
			self.report("error", "one of the machines failed.")
			self.report("traceback", traceback.format_exc())
			raise Exception("aborted due to error in machines %s." % traceback.format_exc())

	def _save_test(self, test_driver, *args):
		names = ", ".join(a for a in args if a)
		content, filename = test_driver.export_xmlres()
		self.files["test/v%d [%s]/%s" % (self.test_version, names, filename)] = content
		self.test_version += 1
		return content

	def _verify_reimport(self, master, test_driver, all_recorded_results, exported_test_data):
		xmlres_zip = exported_test_data

		with tempfile.NamedTemporaryFile() as temp:
			temp.write(xmlres_zip)
			temp.flush()

			with tempfile.TemporaryDirectory() as tmpdir:
				temp_test_name = create_temp_test_name()
				test_path = _patch_exam_name(temp.name, temp_test_name, tmpdir)
				self.report("master", "reimporting test as %s" % temp_test_name)
				master.user_driver.import_test(test_path)
				self.report("master", "reimport of test as %s done." % temp_test_name)

			verify_result = None
			try:
				reimported_test = ImportedTest(temp_test_name)
				reimported_test_driver = master.user_driver.create_test_driver(reimported_test)

				verify_result = self._verify_xls(
					master, reimported_test_driver, all_recorded_results, is_reimport=True)

			except Exception as e:
				self._save_error_screenshot(master)
				raise e

			finally:
				try:
					master.user_driver.delete_test(temp_test_name)
				except:
					if verify_result is None:
						# we got here through another exception. don't override it.
						self.report("error", "could not delete test")
						self.report("traceback", traceback.print_exc())
					else:
						raise

		return verify_result

	def _verify_xls(self, master, test_driver, all_recorded_results, is_reimport=False):
		rounds = list()

		rounds.append("check")
		if not is_reimport:
			# ensure test export here, since we might always fail while doing round 0 (we still
			# want to have one test export then).
			exported_test_data = self._save_test(test_driver, "initial")
			rounds.append("reimport")

		if not is_reimport:
			# operations we do on the main test (not the reimported version).
			num_readjustments = max(0, int(self.settings.num_readjustments))
		else:
			# operations we do on the reimported test (not the main version).

			# always do >= 1 readjustment on the reimported test. this might look superfluous, but
			# in fact it's an essential regression test: scores and marks are imported from the xml,
			# but not recomputed by default, i.e. if there's an error in the underlying data import
			# of the responses given, score errors will only be visible after one readjustment. this
			# error has happened before, see Mantis bug 18553.

			num_readjustments = 1

		for _ in range(num_readjustments):
			rounds.append("readjust")
			rounds.append("check")

		rounds.append("manual")
		rounds.append("check")

		prefix = 'reimport/' if is_reimport else 'original/'

		all_assertions_ok = False

		for round_index, round in enumerate(rounds):
			processing_round = PostProcessingRound(round_index, is_reimport)

			if round == "check":
				xls = test_driver.export_xls()
				workbook = load_workbook(filename=io.BytesIO(xls))

				try:
					check_workbook_consistency(
						workbook, self.questions, self.workarounds, self.ilias_version, master.report)
				except:
					raise IntegrityException("failed to check workbook consistency")

				if round_index == 0:
					self.files[prefix + "exported_r%d.xlsx" % round_index] = xls

				all_assertions_ok = self._check_results(
					processing_round, master, test_driver, workbook, all_recorded_results)
				if not all_assertions_ok:
					break

			elif round == "reimport":
				all_assertions_ok = all_assertions_ok and self._verify_reimport(
					master, test_driver, all_recorded_results, exported_test_data) == "OK"
				if not all_assertions_ok:
					break

			elif round == "readjust":
				self._apply_readjustment(
					processing_round, master, test_driver, all_recorded_results)

				self._save_test(test_driver, "reimported" if is_reimport else "", "readjustments")

			elif round == "manual":
				self._apply_manual_scoring(
					processing_round, master, test_driver, all_recorded_results)

				self._save_test(test_driver, "reimported" if is_reimport else "", "manual scoring")

			else:
				raise RuntimeError("illegal round type %s" % round)

		return "OK" if all_assertions_ok else "FAIL"

	def analyze(self, master, test_driver, all_recorded_results):
		# gather coverage data.
		coverage = self.coverage
		for recorded_result in all_recorded_results:
			coverage.extend(recorded_result.coverage)
		self.add_to_protocol("header", "Coverage estimated at %d%%." % coverage.get_percentage())

		# copy protocols and files.
		for user, recorded_result in zip(self.users, all_recorded_results):
			header = ["# TEST RUN FOR %s" % user.get_username().upper(), ""]
			self.protocols[user.get_username()] = header + recorded_result.protocol

			for k, v in recorded_result.files.items():
				self.files[user.get_username() + '_' + k] = v

		# gather performance data.
		for recorded_result in all_recorded_results:
			self.performance_data.extend(recorded_result.performance)

		# abort if any errors.
		worst_domain = get_most_severe_error_domain(all_recorded_results)
		if worst_domain.value > ErrorDomain.none.value:
			err = "failed with unknown details"
			for r in all_recorded_results:
				if worst_domain.name in r.errors:
					err = str(r.errors[worst_domain.name])
					break
			raise TiltrException(worst_domain, err)

		# detailed integrity checks.
		if self._verify_xls(master, test_driver, all_recorded_results) == "OK":
			self.success = ("OK",)
		else:
			raise IntegrityException("integrity assertions failed")

	def add_to_protocol(self, type, text):
		self.protocols[type].append(text)

	def protocol_master(self, text):
		self.add_to_protocol("master", text)

	def store_into_database(self, elapsed_time):
		files = self.files.copy()
		files['protocol.txt'] = self._make_protocol().encode('utf8')

		for protocol_name, protocol_text in self.protocols["postprocessing"].items():
			files['postprocessing/%s' % protocol_name] = ("\n".join(protocol_text)).encode('utf8')

		for part in itertools.chain(["master"], (user.get_username() for user in self.users)):
			files['machines/%s.txt' % part] = ("\n".join(self.protocols[part])).encode('utf8')

		try:
			files_data = dict((k, base64.b64encode(v).decode('utf8')) for k, v in files.items())
		except:
			files['error.txt'] = ("failed to write files data: %s" % traceback.format_exc()).encode('utf8')
			files_data = dict()

		with open_results() as db:
			db.put(
				batch_id=self.batch_id,
				success=encode_success(self.success),
				files=json.dumps(files_data),
				num_users=len(self.users),
				elapsed_time=elapsed_time)
			db.put_performance_data(self.performance_data)
			db.put_coverage_data(self.coverage)

	def cleanup(self, master):
		self.users_factory.release(self._users_backend(master))
		# keep self.users for storing some information on them later.

	def _save_error_screenshot(self, master):
		try:
			i = 1
			while True:
				name = 'error/master.%d' % i
				if ('%s.png' % name) not in self.files:
					break
				i += 1
			self.files['%s.png' % name] = base64.b64decode(
				master.driver.get_screenshot_as_base64())
			self.files['%s.html' % name] = master.driver.page_source.encode("utf8")
		except:
			traceback.print_exc()

	def run(self):
		t0 = time.time()

		# we copy the test for each run, since checking readjustments will
		# destroy the test and would influence following test runs.
		copy_test = True

		temp_test = None  # the temporary copy of the test (deleted soon).
		used_test = None  # the test actually used (copied or not, depends).

		try:
			with self.batch.in_master(self.protocol_master) as master:
				try:
					if copy_test:
						with tempfile.TemporaryDirectory() as tmpdir:
							temp_test_name = create_temp_test_name()
							test_path = _patch_exam_name(
								self.test.get_path(), temp_test_name, tmpdir)
							master.user_driver.import_test(test_path)

						temp_test = ImportedTest(temp_test_name)
						used_test = temp_test

						temp_test.cache.transfer_invariants(self.test.cache)
					else:
						used_test = self.test

					test_driver = master.user_driver.create_test_driver(used_test)
					self.prepare(master, test_driver)

					if temp_test:
						self.test.cache.transfer_invariants(temp_test.cache)
				except Exception as e:
					traceback.print_exc()
					self._save_error_screenshot(master)
					raise e

			try:
				all_recorded_results = self.run_exams()
			except Exception as e:
				# in case of an error, always try to export XLS for later analysis.
				try:
					with self.batch.in_master(self.protocol_master) as master:
						test_driver = master.user_driver.create_test_driver(used_test)
						self.files["error/exported.xlsx"] = test_driver.export_xls()
				except:
					pass  # ignore
				raise e  # original exception

			with self.batch.in_master(self.protocol_master) as master:
				try:
					test_driver = master.user_driver.create_test_driver(used_test)
					self.analyze(master, test_driver, all_recorded_results)

					if temp_test:
						master.user_driver.delete_test(temp_test.get_title())
						temp_test = None
				except Exception as e:
					self._save_error_screenshot(master)
					raise e

		except selenium.common.exceptions.WebDriverException as e:
			self.success = ("FAIL", "interaction")
			traceback.print_exc()
			self.report("error", str(e))
			self.report("traceback", traceback.format_exc())
			self.add_to_protocol("header", "Error: %s" % traceback.format_exc())

		except TiltrException as e:
			self.success = ("FAIL", e.get_error_domain_name())
			traceback.print_exc()
			self.report("error", str(e))
			self.report("traceback", traceback.format_exc())
			self.add_to_protocol("header", "Error: %s" % traceback.format_exc())

		except:
			self.success = ("FAIL", "unknown")
			traceback.print_exc()
			self.report("error", "unexpected exception received. please inspect traceback.")
			self.report("traceback", traceback.format_exc())
			self.add_to_protocol("header", "Error: %s" % traceback.format_exc())

		finally:
			self.add_to_protocol("header", "Finished with status %s." % encode_success(self.success))

			if temp_test:
				try:
					with self.batch.in_master(self.protocol_master) as master:
						master.user_driver.delete_test(temp_test.get_title())
				except:
					traceback.print_exc()

			try:
				if self.users:
					with self.batch.in_master(self.protocol_master) as master:
						self.cleanup(master)
			except:
				self.report("error", "cleanup failed")
				self.report("traceback", traceback.format_exc())
				traceback.print_exc()

			try:
				self.store_into_database(time.time() - t0)
			except:
				traceback.print_exc()
				self.report("error", "could not save results to db")
				self.report("traceback", traceback.format_exc())
			finally:
				self.report("master", "finished with status %s." % encode_success(self.success))

		return self.success

	def report(self, origin, message):
		self.add_to_protocol("log", "[%s] %s" % (origin, message))
		self.batch.report(origin, message)


class Batch(threading.Thread):
	def __init__(self, machines, ilias_version, test, settings, workarounds, wait_time):
		threading.Thread.__init__(self)
		self._profiling = False

		self.sockets = []
		self.buffered = []
		self.print_mutex = Lock()

		self.machines = machines
		self.ilias_version = ilias_version

		self.settings = settings
		self.workarounds = workarounds
		self.wait_time = wait_time

		self.machines_lookup = dict((v, k) for k, v in machines.items())
		self.machines_lookup["master"] = "master"
		self.machines_lookup["error"] = "error"
		self.machines_lookup["traceback"] = "traceback"

		self.test = test
		self.users_factory = UsersFactory(test, len(machines))

		self.screenshot = None

		self.batch_id = datetime.datetime.today().strftime('%Y%m%d%H%M%S-') + str(uuid.uuid4())
		self._is_done = False
		self._success = None

		self.debug = False
		self.ilias_url = None
		self.ilias_admin_user = None
		self.ilias_admin_password = None
		self.verify_ssl = True

	@contextmanager
	def in_master(self, protocol):
		context = MasterContext(self, protocol)

		with run_interaction():
			self.report("master", "connecting to client browser.")

			args = dict(
				browser=self.settings.browser,
				wait_time=self.wait_time,
				resolution=self.settings.resolution)

			with pandora.Browser(**args) as browser:
				self.report(
					'master', 'running on user agent %s' % browser.driver.execute_script('return navigator.userAgent'))

				context.driver = browser.driver
				context.user_driver = UserDriver(
					browser.driver, self.ilias_url, self.ilias_version, context.report, verify_ssl=self.verify_ssl)

				with context.user_driver.login(self.ilias_admin_user, self.ilias_admin_password) as login:
					context.language = login.language

					yield context

	def get_id(self):
		return self.batch_id

	def set_recycle_users(self, recycle):
		#self.users_factory.recycle = recycle
		pass

	def configure(self, args):
		self.debug = args.debug
		self.ilias_url = args.ilias_url
		self.ilias_admin_user = args.ilias_admin_user
		self.ilias_admin_password = args.ilias_admin_password
		self.verify_ssl = True if args.verify_ssl is None else json.loads(args.verify_ssl.lower())

	def run(self):
		# clear ILIAS temp data (exported pdf and html files). if we don't do this
		# regularly, GB and GB of data will fill up our disk until it's full.
		for f in glob.glob('/tiltr/tmp/iliastemp/*'):
			if os.path.isdir(f):
				if len(os.listdir(f)) == 0:
					os.rmdir(f)
			else:
				os.remove(f)

		if self._profiling:
			import cProfile
			profiler = cProfile.Profile()
			profiler.enable()

		success = ("FAIL", "unknown")
		try:
			asyncio.set_event_loop(asyncio.new_event_loop())

			self.report("master", "connecting to ILIAS %s." % self.ilias_version.text)

			run = Run(self)
			success = run.run()
		finally:
			try:
				self.report_done(success)
			except:
				print("failed to report done status %s." % run.success)

		if self._profiling:
			profiler.disable()
			profiler.print_stats(sort='time')

	def get_screenshot_as_base64(self):
		return self.screenshot

	def is_done(self):
		return self._is_done

	def get_success(self):
		return self._success

	def report(self, origin, message):
		if self.debug:  # don't dump to console, this only makes Docker logs big over time.
			self.print_mutex.acquire()
			try:
				print("[%s] %s" % (origin, message))
			except UnicodeEncodeError:
				# this should not happen, as our docker-compose file sets PYTHONIOENCODING
				traceback.print_exc()
			finally:
				self.print_mutex.release()

		encoded = json.dumps(dict(
			command="report",
			origin=self.machines_lookup.get(origin, "machine_unknown"),
			message=message))

		self.buffered.append(encoded)
		self.flush()

	def flush(self):
		if self.sockets:
			for socket in self.sockets:
				try:
					for buffered in self.buffered:
						socket.write_message(buffered)
				except:
					# web socket failed. happens quite often with some browsers. ignore so
					# we don't fill up our docker logs with garbage.
					pass

			self.buffered = []

	def add_socket(self, socket):
		self.sockets.append(socket)
		self.flush()

		if self.is_done():
			self.report_done("UNKNOWN")

	def remove_socket(self, socket):
		if socket in self.sockets:
			self.sockets.remove(socket)

	def report_done(self, success):
		self._is_done = True
		self._success = success

		self.flush()

		encoded = json.dumps(dict(command="done", success=encode_success(success)))
		for socket in self.sockets:
			try:
				socket.write_message(encoded)
			except:
				pass
