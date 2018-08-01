#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import os
import datetime
import io
import requests
import time
import traceback

from openpyxl import load_workbook
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from decimal import *

from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By


from .utils import wait_for_page_load, http_get_parameters, set_inputs,\
	wait_for_css, wait_for_css_visible, set_element_value_by_css, set_element_value, is_driver_alive

from ..question import *
from ..result import *


class Login:
	def __init__(self, driver, report, username, password):
		self.driver = driver
		self.report = report
		self.username = username
		self.password = password

	def __enter__(self):
		self.report("opening login page.")

		with wait_for_page_load(self.driver):
			self.driver.get("http://web:80/ILIAS/")

		driver = self.driver

		wait_for_css(driver, "form[name='formlogin']")

		with wait_for_page_load(self.driver):
			set_inputs(
				driver,
				username=self.username,
				password=self.password)

			self.report("logging in as " + self.username + "/" + self.password + ".")
			driver.find_element_by_css_selector("input[name='cmd[doStandardAuthentication]']").click()

		try:
			driver.find_element_by_css_selector("form[name='formlogin']")
			raise Exception("login failed (error 2). aborting.")
		except NoSuchElementException:
			pass  # expected

		change_password = False
		try:
			driver.find_element_by_css_selector("#il_prop_cont_current_password")
			change_password = True
		except NoSuchElementException:
			pass

		if change_password:
			self.report("changing password.")
			with wait_for_page_load(self.driver):
				set_inputs(
					driver,
					current_password=self.password,
					new_password=self.password + "_",
					new_password_retype=self.password + "_"
				)
				driver.find_element_by_css_selector("input[name='cmd[savePassword]']").click()

	def __exit__(self, *args):
		try:
			driver = self.driver

			if not is_driver_alive(driver):
				self.report("driver is no longer alive. skipping logout.")
				return

			try:
				driver.find_element_by_css_selector("#userlog")
			except NoSuchElementException:
				return  # already logged out

			with wait_for_page_load(self.driver):
				driver.find_element_by_css_selector("#userlog a.dropdown-toggle").click()
				logout = "//a[contains(@href, 'logout.php')]"
				WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.XPATH, logout)))
				driver.find_element_by_xpath(logout).click()
			self.report("logged out.")
		except:
			self.report("logout failed.")
			self.report(traceback.format_exc())


def goto_administration_page(driver, id):
	for i in range(2):
		try:
			wait_for_css(driver, "#mm_adm_tr", 1)
			driver.find_element_by_css_selector("#mm_adm_tr").click()

			wait_for_css(driver, "#%s" % id)
			with wait_for_page_load(driver):
				driver.find_element_by_css_selector("#%s" % id).click()

			return
		except:
			with wait_for_page_load(driver):
				driver.get("http://web:80/ILIAS")

	raise Exception("going to admin page %s failed." % id)


def goto_test_administration(driver):
	goto_administration_page(driver, "mm_adm_assf")


def goto_user_administration(driver):
	goto_administration_page(driver, "mm_adm_usrf")


def goto_editor_administration(driver):
	goto_administration_page(driver, "mm_adm_adve")


def add_user(driver, username, password):
	with wait_for_page_load(driver):
		driver.find_element_by_xpath("//a[contains(@href, 'cmd=addUser')]").click()

	driver.find_element_by_css_selector("input[id='gender_m']").click()

	set_inputs(
		driver,
		login=username,
		passwd=password,
		passwd_retype=password,
		firstname=username,
		lastname="user",
		email="ilias@localhost")

	with wait_for_page_load(driver):
		driver.find_element_by_css_selector("input[name='cmd[save]']").click()


def delete_user(driver, username):
	try:
		activator = driver.find_element_by_css_selector(".ilTableFilterActivator")
		activator.click()
	except WebDriverException:
		pass

	apply_filter = "input[name='cmd[applyFilter]']"
	wait_for_css_visible(driver, apply_filter)

	set_element_value_by_css(driver, "input[name='query']", username)
	driver.find_element_by_css_selector(apply_filter).click()

	for tr in driver.find_elements_by_css_selector("table tr"):
		for a in tr.find_elements_by_css_selector("td a"):
			if a.text.strip() == username:
				for checkbox in tr.find_elements_by_css_selector("input[type='checkbox']"):
					checkbox.click()

	Select(driver.find_element_by_css_selector('select[name="selected_cmd"]')).select_by_value("deleteUsers")
	with wait_for_page_load(driver):
		driver.find_element_by_css_selector('input[name="select_cmd"]').click()

	with wait_for_page_load(driver):
		driver.find_element_by_name('cmd[confirmdelete]').click()


def verify_admin_setting(name, value, expected, log):
	if value != expected:
		raise Exception("wrong administration setting: %s must be %s." % (name, expected))
	log.append("%s is %s." % (name, expected))


def verify_admin_settings(driver, workarounds, report):
	log = []

	goto_test_administration(driver)
	report("verifying test admin settings.")

	verify_admin_setting(
		"locking for tests",
		driver.find_element_by_id("ass_process_lock").is_selected(),
		True,
		log)

	verify_admin_setting(
		"locking for tests using db tables",
		driver.find_element_by_id("ass_process_lock_mode_db").is_selected(),
		True,
		log)

	verify_admin_setting(
		"html export for essay questions",
		driver.find_element_by_id("export_essay_qst_with_html").is_selected(),
		True,
		log)

	goto_editor_administration(driver)
	report("verifying editor admin settings.")

	driver.find_element_by_css_selector("#tab_adve_rte_settings a").click()

	if workarounds.force_tinymce:
		verify_admin_setting(
			"TinyMCE",
			driver.find_element_by_id("use_tiny").is_selected(),
			True,
			log)

	driver.find_element_by_css_selector("#subtab_adve_assessment_settings a").click()

	for checkbox in driver.find_elements_by_css_selector('input[name="html_tags[]"]'):
		if checkbox.get_attribute("id") == "html_tags_all__toggle":
			continue  # ignore
		if checkbox.get_attribute("value") == "p":
			allow = True  # we must allow <p>, otherwise no new lines
		else:
			allow = False
		verify_admin_setting(
			"TinyMCE setting for <%s>" % checkbox.get_attribute("value"),
			checkbox.is_selected(),
			allow,
			log)

	return log


class TemporaryUser:
	def __init__(self):
		self.username = None
		self.password = None

	def create(self, driver, report, unique_id):
		# note: self.username must always stay <= 31 chars, as Excel tab names are limited to that
		# size and we fail to match names if names are longer here.
		self.username = datetime.datetime.today().strftime('tu_%Y%m%d%H%M%S') + ("_%s" % unique_id)
		self.password = "dev1234"

		retries = 0
		while True:
			try:
				goto_user_administration(driver)
				report("creating user %s." % self.username)
				add_user(driver, self.username, self.password)
				break
			except WebDriverException:
				retries += 1
				if retries >= 3:
					raise

	def destroy(self, driver, report):
		try:
			report("deleting user %s." % self.username)
			goto_user_administration(driver)
			delete_user(driver, self.username)
		except:
			report("deletion of user failed.")
			report(traceback.format_exc())

	def get_username(self):
		return self.username

	def get_password(self):
		return self.password


class MeasureTime:
	def __init__(self, dts):
		self.dts  = dts

	def __enter__(self):
		self.start_time = time.time()
		return self

	def __exit__(self, *args):
		self.dts.append(time.time() - self.start_time)


def measure_time(dts):
	return MeasureTime(dts)


class ExamDriver:
	def __init__(self, driver, report, context, questions):
		self.driver = driver
		self.report = report
		self.context = context
		self.questions = questions
		self.answers = dict()
		self.protocol = []
		self.dts = []

	def __enter__(self):
		self.protocol.append((time.time(), "test", "entered test."))
		return self

	def __exit__(self, *args):
		self.report("finishing test.")

		finish_test_css = 'a[data-nextcmd="finishTest"]'
		with wait_for_page_load(self.driver):
			while True:
				try:
					finish_button = self.driver.find_element_by_css_selector(finish_test_css)
					finish_button.click()
					self.confirm_save()
					break
				except NoSuchElementException:
					# try to go to next question
					if not self.goto_next_question():
						self.driver.refresh()

		with wait_for_page_load(self.driver):
			self.driver.find_element_by_css_selector('input[name="cmd[confirmFinish]"]').click()

		self.protocol.append((time.time(), "test", "finished test."))

	def simulate_crash(self, wait):
		sequence_id = self.get_sequence_id()
		answer = self.answers[sequence_id]

		# simulate crash or loss of session.
		answer.protocol.add("starting wait for simulated crash.")

		t0 = time.time()
		t1 = t0 + wait
		while time.time() < t1:
			time.sleep(0.5)
			# keep Selenium alive, otherwise we'll get a closed pipe exception.
			is_driver_alive(self.driver)

		self.report('edited question "%s" for %.1f seconds, now crashing.' % (
			answer.question.title, time.time() - t0))
		#  autosave should have kicked in by now.

		answer.protocol.add("simulating crash.")

		with wait_for_page_load(self.driver):
			self.driver.refresh()

		self.verify_answer()

	def goto_first_question(self):
		while True:
			try:
				button = self.driver.find_element_by_css_selector(
					'a[data-nextcmd="previousQuestion"]')
			except NoSuchElementException:
				return  # done
			self.report("goto previous question.")
			with measure_time(self.dts):
				with wait_for_page_load(self.driver):
					button.click()
					self.confirm_save()

	def goto_next_question(self):
		self.protocol.append((time.time(), "test", "goto next question."))

		try:
			button = self.driver.find_element_by_css_selector(
				'a[data-nextcmd="nextQuestion"]')
		except NoSuchElementException:
			return False

		self.report("goto next question.")
		with measure_time(self.dts):
			with wait_for_page_load(self.driver):
				button.click()
				self.confirm_save()

		return True

	def goto_next_or_previous_question(self):
		self.protocol.append((time.time(), "test", "goto next or previous question."))

		for what in ("next", "previous"):
			try:
				button = self.driver.find_element_by_css_selector(
					'a[data-nextcmd="%sQuestion"]' % what)
			except NoSuchElementException:
				continue

			self.report("goto %s question." % what)
			with measure_time(self.dts):
				with wait_for_page_load(self.driver):
					button.click()
					self.confirm_save()
			return True

		return False

	def has_next_question(self):
		try:
			self.driver.find_element_by_css_selector(
				'a[data-nextcmd="nextQuestion"]')
			return True
		except NoSuchElementException:
			return False

	def has_previous_question(self):
		try:
			self.driver.find_element_by_css_selector(
				'a[data-nextcmd="previousQuestion"]')
			return True
		except NoSuchElementException:
			return False

	def confirm_save(self):
		for i in range(2):
			try:
				button = self.driver.find_element_by_id("tst_save_on_navigation_button")
			except NoSuchElementException:
				return

			try:
				if button.is_displayed():
					# prevent popup on future navigation.
					self.driver.find_element_by_id("save_on_navigation_prevent_confirmation").click()

					with wait_for_page_load(self.driver):
						button.click()
			except:
				# guard against StaleElementReferenceException
				pass

	def get_sequence_id(self):
		return int(http_get_parameters(self.driver.current_url)["sequence"])

	def create_answer(self):
		try:
			page_title = self.driver.find_element_by_css_selector(".ilc_page_title_PageTitle")
		except NoSuchElementException:
			raise Exception("no question title found.")

		title = page_title.text
		self.report('entering question "' + title + '"')

		for css, answer_class in [
			(".ilc_question_SingleChoice", SingleChoiceAnswer),
			(".ilc_question_MultipleChoice", MultipleChoiceAnswer),
			(".ilc_question_KprimChoice", KPrimAnswer),
			(".ilc_question_ClozeTest", ClozeAnswer),
			(".ilc_question_TextQuestion", LongTextAnswerTinyMCE)
		]:
			try:
				self.driver.find_element_by_css_selector(css)
			except NoSuchElementException:
				continue

			answer = answer_class(self.driver, self.questions[title])
			break

		sequence_id = self.get_sequence_id()
		assert sequence_id not in self.answers
		self.answers[sequence_id] = answer

		return answer

	def randomize_answer(self):
		sequence_id = self.get_sequence_id()
		if sequence_id not in self.answers:
			self.create_answer()
		answer = self.answers[sequence_id]
		self.report('answering question "%s".' % answer.question.title)
		answer.randomize(self.context)

	def verify_answer(self):
		sequence_id = self.get_sequence_id()
		if sequence_id not in self.answers:
			raise Exception("cannot verify unknown answer " + str(sequence_id))

		answer = self.answers[sequence_id]
		self.report('verifying question "%s".' % answer.question.title)
		answer.verify(self.context)

	def copy_protocol(self, result):
		protocol = self.protocol[:]

		for sequence_id, answer in self.answers.items():
			encoded = answer.encode(self.context)
			question_title = encoded["title"]

			for t, what in encoded["protocol"]:
				protocol.append((t, question_title, what))

		protocol.sort(key=lambda x: x[0])  # by time
		protocol_lines = [
			"%s [%s] %s" % (
				datetime.datetime.fromtimestamp(t).strftime('%H:%M:%S'),
				title,
				what) for t, title, what in protocol]

		result.attach_protocol(protocol_lines)

	def get_expected_result(self):
		def clip_score(score):
			return max(score, Decimal(0))  # clamp score to >= 0 (FIXME: check test settings)

		def format_score(score):
			s = str(score)
			if '.' in s:
				s = s.rstrip('0')
				if s.endswith('.'):
					s = s.rstrip('.')
			return s

		result = Result(origin=Origin.recorded)

		for sequence_id, answer in self.answers.items():
			encoded = answer.encode(self.context)
			question_title = encoded["title"]
			
			for dimension_title, dimension_value in encoded["answers"].items():
				result.add(("question", question_title, "answer", dimension_title), dimension_value)

			result.add(("question", question_title, "score"), format_score(clip_score(answer.current_score)))

		expected_total_score = Decimal(0)
		for answer in self.answers.values():
			expected_total_score += clip_score(answer.current_score)
		result.add(("exam", "score", "total"), format_score(expected_total_score))
		result.add(("exam", "score", "gui"), format_score(expected_total_score))

		self.copy_protocol(result)
		result.attach_performance_measurements(self.dts)
		return result


class Test:
	def __init__(self, test_id):
		self.test_id = test_id
		self.path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tests", test_id + ".zip"))
		with ZipFile(self.path, 'r') as zf:
			root = ET.fromstring(zf.read("%s/%s.xml" % (test_id, test_id)))
		self.title = root.findall(".//Title")[0].text

	def get_id(self):
		return self.test_id

	def get_path(self):
		return self.path

	def get_title(self):
		return self.title

	@staticmethod
	def list():
		tests = dict()
		path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tests"))
		for filename in os.listdir(path):
			if filename.endswith(".zip"):
				test = Test(os.path.splitext(filename)[0])
				tests[test.get_title()] = test.get_id()
		return tests


class TestDriver():
	def __init__(self, driver, test, workarounds, report):
		self.driver = driver
		self.test = test
		self.workarounds = workarounds
		self.report = report
		self.cached_link = None
		self.autosave_time = 5

	def import_test(self):
		driver = self.driver

		self.report("importing test.")

		# goto Magazin.
		driver.get("http://web:80/ILIAS/goto.php?target=root_1&client_id=ilias")

		# add new item: Test.
		driver.find_element_by_css_selector(".ilNewObjectSelector button").click()
		driver.find_element_by_css_selector(".ilNewObjectSelector #tst").click()
		wait_for_css(driver, 'input[name="cmd[importFile]"]')

		# click on import to get dedicated import mask.
		import_button = None
		for accordion in driver.find_elements_by_css_selector(".il_VAccordionInnerContainer"):
			accordion.find_element_by_css_selector(".il_VAccordionToggleDef").click()
			try:
				import_button = accordion.find_element_by_name("cmd[importFile]")
				break
			except NoSuchElementException:
				pass

		if not import_button:
			raise Exception("test import button not found.")
		with wait_for_page_load(driver):
			#driver.execute_script("document.getElementById('xmldoc').value = arguments[0]", self.test.get_path())
			driver.find_element_by_id("xmldoc").send_keys(self.test.get_path())
			import_button.click()

		# now import.
		#with wait_for_page_load(driver):
		#	driver.find_element_by_css_selector(".ilCreationFormSection #xmldoc")
		#	set_element_value_by_css(driver, "#xmldoc", self.test.get_path())
		#	driver.find_element_by_name("cmd[importFile]").click()

		with wait_for_page_load(driver):
			driver.find_element_by_name("cmd[importVerifiedFile]").click()

		self.report("done importing test.")

	def configure(self):
		self.make_online()
		self.configure_autosave()

	def make_online(self):
		# now activate the Test by setting it online.
		self.goto_settings()

		if not self.driver.find_element_by_id("online").is_selected():
			self.driver.execute_script('document.getElementById("online").click()')

		with wait_for_page_load(self.driver):
			self.driver.find_element_by_name("cmd[saveForm]").click()

		self.report("setting test online.")

	def configure_autosave(self):
		self.goto_settings()

		autosave = self.driver.find_element_by_id("autosave")
		if self.workarounds.enable_autosave:
			if not autosave.is_selected():
				self.driver.execute_script('document.getElementById("autosave").click()')
			wait_for_css_visible(self.driver, "#autosave_ival")
			set_element_value_by_css(self.driver, "#autosave_ival", self.autosave_time)
			self.report("enabling autosave every %.1fs." % self.autosave_time)
		else:
			if autosave.is_selected():
				self.driver.execute_script('document.getElementById("autosave").click()')
			self.report("disabling autosave.")

		with wait_for_page_load(self.driver):
			self.driver.find_element_by_name("cmd[saveForm]").click()

	def goto_participants(self):
		assert self.goto()
		self.driver.find_element_by_css_selector("#tab_participants a").click()

	def goto_settings(self):
		assert self.goto()
		self.driver.find_element_by_css_selector("#tab_settings a").click()

	def goto_scoring(self):
		self.goto_settings()
		self.driver.find_element_by_css_selector("#subtab_scoring").click()

	def goto_questions(self):
		assert self.goto()
		self.driver.find_element_by_css_selector("#tab_assQuestions a").click()

	def goto_statistics(self):
		assert self.goto()
		self.driver.find_element_by_css_selector("#tab_statistics a").click()

	def goto_export(self):
		assert self.goto()
		self.driver.find_element_by_css_selector("#tab_export a").click()

	def goto_scoring_adjustment(self):
		assert self.goto()
		self.driver.find_element_by_css_selector("#tab_scoringadjust a").click()

	def fetch_exported_workbook(self):
		self.goto_export()

		driver = self.driver

		self.report("cleaning current exports.")
		select_all = None
		try:
			select_all = self.driver.find_element_by_css_selector('.ilTableSelectAll')
		except NoSuchElementException:
			pass
		if select_all:
			with wait_for_page_load(driver):
				select_all_id = select_all.find_element_by_css_selector("input").get_attribute("id")
				driver.execute_script('document.getElementById("%s").click()' % select_all_id)
				driver.find_element_by_name("cmd[confirmDeletion]").click()
			with wait_for_page_load(driver):
				driver.find_element_by_name("cmd[delete]").click()

		self.report("exporting as XLS.")
		with wait_for_page_load(driver):
			Select(driver.find_element_by_name("format")).select_by_value("csv")
			driver.find_element_by_name("cmd[createExportFile]").click()
			
		url = None
		for a in driver.find_elements_by_css_selector("table a"):
			params = http_get_parameters(a.get_attribute("href"))
			if params.get('cmd', '') == "download" and params.get('file', '').endswith(".xlsx"):
				url = a.get_attribute("href")
				break

		assert url is not None

		self.report("downloading XLS.")

		cookies = dict((cookie['name'], cookie['value']) for cookie in driver.get_cookies())
		result = requests.get(url, cookies=cookies)
		xls = result.content

		wb = load_workbook(filename=io.BytesIO(xls))
		return xls, wb

	def get_gui_scores(self, usernames):
		self.goto_statistics()

		reached = None
		login = None
		for index, a in enumerate(self.driver.find_elements_by_css_selector("#tst_eval_all thead th a")):
			nav = http_get_parameters(a.get_attribute("href"))["tst_eval_all_table_nav"].split(":")
			if nav[0] == "reached":
				reached = index
			elif nav[0] == "login":
				login = index

		assert reached is not None
		scores = dict()

		for tr in self.driver.find_elements_by_css_selector("#tst_eval_all tbody tr"):
			tds = list(tr.find_elements_by_css_selector("td"))
			for username in usernames:
				if tds[login].text.strip() == ("[%s]" % username):
					score = re.split("\s+", tds[reached].text)
					scores[username] = Decimal(score[0])

		return scores

	def get_question_definitions(self):
		driver = self.driver

		self.goto_questions()

		with wait_for_page_load(self.driver):
			driver.find_element_by_css_selector("#subtab_edit_test_questions").click()

		hrefs = []
		for questionbrowser in driver.find_elements_by_css_selector('#questionbrowser'):
			for a in questionbrowser.find_elements_by_css_selector('a[href]'):
				# self.report(a, a["href"])
				if "cmd=questions" in a.get_attribute("href"):
					hrefs.append(a.get_attribute("href"))

		self.report("parsing questions.")

		questions = dict()
		for href in hrefs:
			parameters = http_get_parameters(href)
			if "eqid" in parameters:
				with wait_for_page_load(self.driver):
					self.driver.get(href)

				title = driver.find_element_by_css_selector("#title").get_attribute("value")
				if title in questions:
					# our data structures use question titles as a primary key for questions.
					raise Exception('duplicate question titled "%s" is not allowed.' % title)

				cmd_class = http_get_parameters(self.driver.current_url)["cmdClass"]

				if cmd_class == "assclozetestgui":
					self.report('parsing cloze question "%s".' % title)
					questions[title] = ClozeQuestion(driver, title)
				elif cmd_class == "asssinglechoicegui":
					self.report('parsing single choice question "%s".' % title)
					questions[title] = SingleChoiceQuestion(driver, title)
				elif cmd_class == "assmultiplechoicegui":
					self.report('parsing multiple choice question "%s".' % title)
					questions[title] = MultipleChoiceQuestion(driver, title)
				elif cmd_class == "asskprimchoicegui":
					self.report('parsing kprim question "%s".' % title)
					questions[title] = KPrimQuestion(driver, title)
				elif cmd_class == "asstextquestiongui":
					self.report('parsing text question "%s".' % title)
					questions[title] = LongTextQuestion(driver, title)
				else:
					raise Exception("unsupported question gui cmd_class " + cmd_class)

		return questions

	def delete_all_participants(self):
		self.goto_participants()
		self.report("deleting all test participants.")

		found = False
		for a in self.driver.find_elements_by_css_selector("a.btn"):
			if "cmd=deleteAllUserResults" in a.get_attribute("href"):
				a.click()
				found = True
				break

		if not found: # no participants in test
			return

		self.driver.find_element_by_css_selector('input[name="cmd[confirmDeleteAllUserResults]"]').click()

	def goto(self):
		if self.cached_link is not None:
			with wait_for_page_load(self.driver):
				self.driver.get(self.cached_link)
			return True

		driver = self.driver

		for i in range(5):
			with wait_for_page_load(driver):
				driver.get("http://web:80/ILIAS/")

			driver.find_element_by_css_selector(".glyphicon-search").click()
			with wait_for_page_load(driver):
				driver.find_element_by_css_selector('#mm_search_form input[type="submit"]').click()

			#self.browser.visit("http://web:80/ILIAS/ilias.php?baseClass=ilSearchController")
			self.report('searching for test "%s".' % self.test.get_title())

			try:
				wait_for_css(driver, ".ilTabsContentOuter div form input[name='term']")

				search_input = driver.find_element_by_css_selector(
					".ilTabsContentOuter div form input[name='term']")
			except TimeoutException:
				# sporadically, a "there is no data set with id" comes along; just retry
				pass

			if search_input:
				set_element_value(driver, search_input, self.test.get_title())
				break

		# note: one reason this might fail is that the test we search for is still "offline."

		self.report("performing search.")
		with wait_for_page_load(driver):
			driver.find_element_by_css_selector("input[name='cmd[performSearch]']").click()
		for i in range(5):
			for link in driver.find_elements_by_partial_link_text(self.test.get_title()):
				if link.is_displayed():
					with wait_for_page_load(driver):
						link.click()
					self.cached_link = driver.current_url
					return True
			time.sleep(1)

		return False

	def start(self, context, questions, allow_resume=False):
		driver = self.driver

		self.report("starting test.")

		resume_player = None
		try:
			resume_player = driver.find_element_by_css_selector("input[name='cmd[resumePlayer]']")
		except NoSuchElementException:
			pass

		if resume_player:
			if not allow_resume:
				raise Exception("test has already been started by this user. aborting.")
			with wait_for_page_load(self.driver):
				resume_player.click()
		else:
			start_button = driver.find_element_by_css_selector(
				"input[name='cmd[startPlayer]']")
			try:
				with wait_for_page_load(self.driver):
					start_button.click()
			except NoSuchElementException:
				raise Exception("user does not have rights to start this test. aborting.")

		return ExamDriver(driver, self.report, context, questions)

