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

from openpyxl import load_workbook
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from .utils import wait_for_page_load, http_get_parameters

from ..question import *
from ..result import *
from ..result.workbook import check_workbook_consistency


class Login:
	def __init__(self, browser, report, username, password):
		self.browser = browser
		self.report = report
		self.username = username
		self.password = password

	def __enter__(self):
		with wait_for_page_load(self.browser):
			self.browser.visit("http://web:80/ILIAS/")
	
		assert not self.browser.find_by_css("#userlog") # assert not logged in.
		if not self.browser.is_element_present_by_css("form[name='formlogin']"):
			raise Exception("login failed (error 1). aborting.")		

		with wait_for_page_load(self.browser):
			self.browser.find_by_css("input[name='username']").fill(self.username)
			self.browser.find_by_css("input[name='password']").fill(self.password)
			self.report("logging in as " + self.username + "/" + self.password + ".")
			self.browser.find_by_css("input[name='cmd[doStandardAuthentication]']").click()

		if self.browser.is_element_present_by_css("form[name='formlogin']"):
			raise Exception("login failed (error 2). aborting.")

		if self.browser.is_element_present_by_css("#il_prop_cont_current_password"):
			self.report("changing password.")
			self.browser.find_by_css("input[name='current_password']").fill(self.password)
			self.browser.find_by_css("input[name='new_password']").fill(self.password + "_")
			self.browser.find_by_css("input[name='new_password_retype']").fill(self.password + "_")
			self.browser.find_by_css("input[name='cmd[savePassword]']").click()

	def __exit__(self, *args):
		try:
			if not self.browser.find_by_css("#userlog"):
				return  # already logged out

			self.browser.find_by_css("#userlog a.dropdown-toggle").click()
			self.browser.find_by_xpath("//a[contains(@href, 'logout.php')]").click()
			self.report("logged out.")
		except Exception as e:
			self.report("logout failed.")
			self.report(e)


def goto_administration_page(browser, id):
	if not browser.is_element_present_by_css("#mm_adm_tr"):
		browser.visit("http://web:80/ILIAS")
	for i in range(5):
		browser.find_by_css("#mm_adm_tr").click()
		if browser.is_element_present_by_css("#%s" % id):
			with wait_for_page_load(browser):
				browser.find_by_css("#%s" % id).click()
			return
		time.sleep(1)
	raise Exception("goto_administration_page failed.")


def goto_test_administration(browser):
	goto_administration_page(browser, "mm_adm_assf")


def goto_user_administration(browser):
	goto_administration_page(browser, "mm_adm_usrf")


def goto_editor_administration(browser):
	goto_administration_page(browser, "mm_adm_adve")


def add_user(browser, username, password):
	#browser.find_by_css(".navbar-toggle").click()
	with wait_for_page_load(browser):
		browser.find_by_xpath("//a[contains(@href, 'cmd=addUser')]").click()
	browser.find_by_css("input[id='gender_m']").click()

	browser.find_by_css("input[name='login']").fill(username)
	browser.find_by_css("input[name='passwd']").fill(password)
	browser.find_by_css("input[name='passwd_retype']").fill(password)
	browser.find_by_css("input[name='firstname']").fill(username)
	browser.find_by_css("input[name='lastname']").fill("user")
	browser.find_by_css("input[name='email']").fill("ilias@localhost")

	#report("adding user " + username + "/" + password + ".")
	with wait_for_page_load(browser):
		browser.find_by_css("input[name='cmd[save]']").click()


def delete_user(browser, username):
	#browser.find_by_css(".navbar-toggle").click()
	browser.find_by_css("input[name='query']").fill(username)
	browser.find_by_css("input[name='cmd[applyFilter]']").click()

	for tr in browser.find_by_css("table tr"):
		for a in tr.find_by_css("td a"):
			if a.text.strip() == username:
				for checkbox in tr.find_by_css("input[type='checkbox']"):
					checkbox.click()

	browser.find_by_css('select[name="selected_cmd"]').first.select("deleteUsers")
	browser.find_by_css('input[name="select_cmd"]').click()

	browser.find_by_name('cmd[confirmdelete]').click()


def verify_admin_setting(name, value, expected, log):
	if value != expected:
		raise Exception("wrong administration setting: %s must be %s." % (name, expected))
	log.append("%s is %s." % (name, expected))


def verify_admin_settings(browser, workarounds):
	log = []

	goto_test_administration(browser)

	verify_admin_setting(
		"locking for tests",
		browser.find_by_css("#ass_process_lock").first.checked,
		True,
		log)

	verify_admin_setting(
		"locking for tests using db tables",
		browser.find_by_css("#ass_process_lock_mode_db").first.checked,
		True,
		log)

	verify_admin_setting(
		"html export for essay questions",
		browser.find_by_css("#export_essay_qst_with_html").first.checked,
		True,
		log)

	goto_editor_administration(browser)
	browser.find_by_css("#tab_adve_rte_settings a").click()

	if not workarounds.supports_non_tinymce:
		verify_admin_setting(
			"TinyMCE",
			browser.find_by_css("#use_tiny").first.checked,
			True,
			log)

	browser.find_by_css("#subtab_adve_assessment_settings a").click()

	for checkbox in browser.find_by_css('input[name="html_tags[]"]'):
		if checkbox["id"] == "html_tags_all__toggle":
			continue  # ignore
		if checkbox.value == "p":
			allow = True  # we must allow <p>, otherwise no new lines
		else:
			allow = False
		verify_admin_setting(
			"TinyMCE setting for <%s>" % checkbox.value,
			checkbox.checked,
			allow,
			log)

	return log


class TemporaryUser:
	def __init__(self):
		self.username = None
		self.password = None

	def create(self, browser, report, unique_id):
		self.username = datetime.datetime.today().strftime('testuser_%Y%m%d%H%M%S') + ("_%s" % unique_id)
		self.password = "dev1234"
		report("creating user %s." % self.username)
		goto_user_administration(browser)
		add_user(browser, self.username, self.password)

	def destroy(self, browser, report):
		try:
			report("deleting user %s." % self.username)
			goto_user_administration(browser)
			delete_user(browser, self.username)
		except Exception as e:
			report("deletion of user failed.")
			report("!traceback")

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
	def __init__(self, browser, report, context, questions):
		self.browser = browser
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
		with wait_for_page_load(self.browser):
			while True:
				if self.browser.is_element_present_by_css(finish_test_css):
					finish_button = self.browser.find_by_css(finish_test_css)
					if finish_button:
						finish_button.click()
						self.confirm_save()
						break
				else:
					# try to go to next question
					if not self.goto_next_question():
						self.browser.reload()

		with wait_for_page_load(self.browser):
			self.browser.find_by_css('input[name="cmd[confirmFinish]"]').click()

		self.protocol.append((time.time(), "test", "finished test."))

	def goto_first_question(self):
		while self.browser.is_element_present_by_css('a[data-nextcmd="previousQuestion"]'):
			self.report("goto previous question.")
			with measure_time(self.dts):
				with wait_for_page_load(self.browser):
					self.browser.find_by_css('a[data-nextcmd="previousQuestion"]').click()
					self.confirm_save();

	def goto_next_question(self):
		if not self.has_next_question():
			return False
		self.report("goto next question.")
		with measure_time(self.dts):
			with wait_for_page_load(self.browser):
				self.browser.find_by_css('a[data-nextcmd="nextQuestion"]').click()
				self.confirm_save()
		return True

	def goto_next_or_previous_question(self):
		with measure_time(self.dts):
			with wait_for_page_load(self.browser):
				if self.has_next_question():
					self.report("goto next question.")
					self.browser.find_by_css('a[data-nextcmd="nextQuestion"]').click()
					self.confirm_save()
					return True
				else:
					self.report("goto previous question.")
					self.browser.find_by_css('a[data-nextcmd="previousQuestion"]').click()
					self.confirm_save()
					return False

	def has_next_question(self):
		return self.browser.is_element_present_by_css('a[data-nextcmd="nextQuestion"]')

	def has_previous_question(self):
		return self.browser.is_element_present_by_css('a[data-nextcmd="previousQuestion"]')

	def confirm_save(self):
		if self.browser.is_element_present_by_css("#tst_save_on_navigation_button"):
			for i in range(2):
				try:
					nav = self.browser.find_by_css("#tst_save_on_navigation_button")
					if nav and nav.first.visible:
						with wait_for_page_load(self.browser):
							nav.first.click()
				except:
					# guard against StaleElementReferenceException
					pass

	def get_sequence_id(self):
		return int(http_get_parameters(self.browser.url)["sequence"])

	def create_answer(self):
		if not self.browser.is_element_present_by_css(".ilc_page_title_PageTitle"):
			raise Exception("no question title found.")
		else:
			title = self.browser.find_by_css("h1.ilc_page_title_PageTitle").first.text
			self.report('entering question "' + title + '"')

		answer = None
		if self.browser.is_element_present_by_css(".ilc_question_SingleChoice"):
			answer = SingleChoiceAnswer(self.browser, self.questions[title])
		elif self.browser.is_element_present_by_css(".ilc_question_MultipleChoice"):
			answer = MultipleChoiceAnswer(self.browser, self.questions[title])
		elif self.browser.is_element_present_by_css(".ilc_question_ClozeTest"):
			answer = ClozeAnswer(self.browser, self.questions[title])
		elif self.browser.is_element_present_by_css(".ilc_question_TextQuestion"):
			answer = LongTextAnswerTinyMCE(self.browser, self.questions[title])
		else:
			raise Exception("unsupported question type encountered. aborting.");

		sequence_id = self.get_sequence_id()
		assert sequence_id not in self.answers
		self.answers[sequence_id] = answer

		return answer

	def randomize_answer(self):
		sequence_id = self.get_sequence_id()
		if sequence_id not in self.answers:
			self.create_answer()
		self.answers[sequence_id].randomize(self.context)
		# self.answers[sequence_id].verify()

	def verify_answer(self):
		sequence_id = self.get_sequence_id()
		if sequence_id not in self.answers:
			raise Exception("cannot verify unknown answer " + str(sequence_id))

		self.report("verifying question " + str(sequence_id) + ".")
		self.answers[sequence_id].verify(self.context)

	def get_expected_result(self):
		def clip_score(score):
			return max(score, 0)  # clamp score to >= 0 (FIXME: check test settings)

		protocol = self.protocol[:]
		result = Result(origin=Origin.recorded)

		for sequence_id, answer in self.answers.items():
			encoded = answer.encode(self.context)
			question_title = encoded["title"]
			
			for dimension_title, dimension_value in encoded["answers"].items():
				result.add("question.%s.%s" % (question_title, dimension_title), dimension_value)

			result.add("score.%s" % question_title, clip_score(answer.current_score))

			for t, what in encoded["protocol"]:
				protocol.append((t, question_title, what))

		expected_total_score = 0
		for answer in self.answers.values():
			expected_total_score += clip_score(answer.current_score)
		result.add("score", expected_total_score)
		result.add("gui.score", expected_total_score)

		protocol.sort(key=lambda x: x[0]) # by time
		protocol_text = "\n".join([
			"%s [%s] %s" % (
				datetime.datetime.fromtimestamp(t).strftime('%H:%M:%S'),
				title,
				what) for t, title, what in protocol])

		result.set_protocol(protocol_text)
		result.set_performance_measurements(self.dts)
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
	def __init__(self, browser, test, report):
		self.browser = browser
		self.test = test
		self.report = report
		self.cached_link = None

	def import_test(self):
		self.report("importing test.")

		# goto Magazin.
		self.browser.visit("http://web:80/ILIAS/goto.php?target=root_1&client_id=ilias")

		# add new item: Test.
		self.browser.find_by_css(".ilNewObjectSelector button").click()
		self.browser.find_by_css(".ilNewObjectSelector #tst").click()

		# click on import to get dedicated import mask.
		for accordion in self.browser.find_by_css(".il_VAccordionInnerContainer"):
			if accordion.find_by_name("cmd[importFile]"):
				accordion.find_by_css(".il_VAccordionToggleDef").click()
				accordion.find_by_name("cmd[importFile]").click()
				break

		# now import.
		with wait_for_page_load(self.browser):
			self.browser.find_by_css(".ilCreationFormSection #xmldoc")
			self.browser.find_by_css("#xmldoc").fill(self.test.get_path())
			self.browser.find_by_name("cmd[importFile]").click()

		with wait_for_page_load(self.browser):
			self.browser.find_by_name("cmd[importVerifiedFile]").click()

		self.make_online()

		self.report("done importing test.")

	def make_online(self):
		# now activate the Test by setting it online.
		self.goto_settings()

		if not self.browser.find_by_css("#online").checked:
			# for some reason, neither self.browser.find_by_css("#online").click()
			# nor self.browser.check("online") works here. this does though:
			self.browser.execute_script('document.getElementById("online").click()')

		self.browser.find_by_name("cmd[saveForm]").click()

		self.report("setting test online.")

	def goto_participants(self):
		assert self.goto()
		self.browser.find_by_css("#tab_participants a").click()

	def goto_settings(self):
		assert self.goto()
		self.browser.find_by_css("#tab_settings a").click()

	def goto_scoring(self):
		self.goto_settings()
		self.browser.find_by_css("#subtab_scoring").click()

	def goto_questions(self):
		assert self.goto()
		self.browser.find_by_css("#tab_assQuestions a").click()

	def goto_statistics(self):
		assert self.goto()
		self.browser.find_by_css("#tab_statistics a").click()

	def goto_export(self):
		assert self.goto()
		self.browser.find_by_css("#tab_export a").click()

	def fetch_exported_workbook(self, batch_id, workarounds):
		self.goto_export()

		self.report("cleaning current exports.")
		select_all = self.browser.find_by_css('.ilTableSelectAll')
		if select_all:
			with wait_for_page_load(self.browser):
				select_all_id = select_all.find_by_css("input").first["id"]
				self.browser.execute_script('document.getElementById("%s").click()' % select_all_id)
				self.browser.find_by_name("cmd[confirmDeletion]").click()
				self.browser.find_by_name("cmd[delete]").click()
		assert not self.browser.find_by_css('.ilTableSelectAll')

		self.report("exporting as XLS.")
		self.browser.select("format", "csv")
		self.browser.find_by_name("cmd[createExportFile]").click()
			
		url = None
		for a in self.browser.find_by_css("table a"):
			params = http_get_parameters(a["href"])
			if params.get('cmd', '') == "download" and params.get('file', '').endswith(".xlsx"):
				url = a["href"]
				break

		assert url is not None

		self.report("downloading XLS.")
		result = requests.get(url, cookies=self.browser.cookies.all())
		xls = result.content

		wb = load_workbook(filename=io.BytesIO(xls))
		check_workbook_consistency(wb, self.report, workarounds)
		return xls, wb

	def get_score(self, username):
		self.goto_statistics()

		reached = None
		login = None
		for index, a in enumerate(self.browser.find_by_css("#tst_eval_all thead th a")):
			nav = http_get_parameters(a["href"])["tst_eval_all_table_nav"].split(":")
			if nav[0] == "reached":
				reached = index
			elif nav[0] == "login":
				login = index

		assert reached is not None
		for tr in self.browser.find_by_css("#tst_eval_all tbody tr"):
			tds = list(tr.find_by_css("td"))
			if tds[login].text.strip() == ("[%s]" % username):
				score = re.split("\s+", tds[reached].text)
				return float(score[0])

		return None

	def get_question_definitions(self):
		self.goto_questions()

		with wait_for_page_load(self.browser):
			self.browser.find_by_css("#subtab_edit_test_questions").click()

		hrefs = []
		for questionbrowser in self.browser.find_by_css('#questionbrowser'):
			for a in questionbrowser.find_by_css('a[href]'):
				# self.report(a, a["href"])
				if "cmd=questions" in a["href"]:
					hrefs.append(a["href"])

		self.report("parsing questions.")

		questions = dict()
		for href in hrefs:
			parameters = http_get_parameters(href)
			if "eqid" in parameters:
				self.browser.visit(href)

				title = self.browser.find_by_css("#title").first.value
				if title in questions:
					raise Exception('duplicate question titled "%s"' % title)

				cmd_class = http_get_parameters(self.browser.url)["cmdClass"]

				if cmd_class == "assclozetestgui":
					self.report('parsing cloze question "%s".' % title)
					questions[title] = ClozeQuestion(self.browser, title)
				elif cmd_class == "asssinglechoicegui":
					self.report('parsing single choice question "%s".' % title)
					questions[title] = SingleChoiceQuestion(self.browser, title)
				elif cmd_class == "assmultiplechoicegui":
					self.report('parsing multiple choice question "%s".' % title)
					questions[title] = MultipleChoiceQuestion(self.browser, title)
				elif cmd_class == "asstextquestiongui":
					self.report('parsing text question "%s".' % title)
					questions[title] = LongTextQuestion(self.browser, title)
				else:
					raise Exception("unsupported question gui cmd_class " + cmd_class)

		return questions

	def delete_all_participants(self):
		self.goto_participants()
		self.report("deleting all test participants.")

		found = False
		for a in self.browser.find_by_css("a.btn"):
			if "cmd=deleteAllUserResults" in a["href"]:
				a.click()
				found = True
				break

		if not found: # no participants in test
			return

		self.browser.find_by_css('input[name="cmd[confirmDeleteAllUserResults]"]').click()		

	def goto(self):
		if self.cached_link is not None:
			self.browser.visit(self.cached_link)
			return True

		for i in range(5):
			self.browser.visit("http://web:80/ILIAS/")
			self.browser.find_by_css(".glyphicon-search").click()
			self.browser.find_by_css('#mm_search_form input[type="submit"]').click()

			#self.browser.visit("http://web:80/ILIAS/ilias.php?baseClass=ilSearchController")
			self.report('searching for test "%s".' % self.test.get_title())

			search_input = self.browser.find_by_css(".ilTabsContentOuter div form input[name='term']")
			if not search_input:
				# sporadically, a "there is no data set with id" comes along; just retry
				if i > 3:
					raise Exception("could not perform search")
				self.browser.visit("http://web:80/ILIAS/")
				continue
			search_input.fill(self.test.get_title())
			break

		# note: one reason this might fail is that the test we search for is still "offline."

		self.report("performing search.")
		with wait_for_page_load(self.browser):
			self.browser.find_by_css("input[name='cmd[performSearch]']").click()
		for i in range(5):
			for link in self.browser.find_link_by_partial_text(self.test.get_title()):
				if link.visible:
					with wait_for_page_load(self.browser):
						link.click()
					self.cached_link = self.browser.url
					return True
			time.sleep(1)

		return False

	def start(self, context, questions, allow_resume=False):
		self.report("starting test.")
		if self.browser.is_element_present_by_css("input[name='cmd[resumePlayer]']"):
			if not allow_resume:
				raise Exception("test has already been started by this user. aborting.")
			with wait_for_page_load(self.browser):
				self.browser.find_by_css("input[name='cmd[resumePlayer]']").click()
		else:
			startButton = self.browser.find_by_css("input[name='cmd[startPlayer]']")
			if startButton:
				with wait_for_page_load(self.browser):
					startButton.click()
			else:
				raise Exception("user does not have rights to start this test. aborting.")

		return ExamDriver(self.browser, self.report, context, questions)

