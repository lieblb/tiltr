#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import os
import datetime
import io
import re
import requests
import traceback
from urllib.parse import urlparse, parse_qs
from decimal import *

from openpyxl import load_workbook
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element, SubElement, tostring

from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from .utils import *
from .exam_configuration import *

from testilias.question import *
from testilias.data.result import *
from testilias.question.protocol import AnswerProtocol


class Login:
	def __init__(self, driver, report, url, username, password):
		self.driver = driver
		self.report = report
		self.url = url
		self.username = username
		self.password = password
		self.language = None

	def __enter__(self):
		self.report("opening login page.")

		with wait_for_page_load(self.driver):
			self.driver.get(self.url)

		driver = self.driver

		wait_for_css(driver, "form[name='formlogin']")

		def do_login(button):
			set_inputs(
				driver,
				username=self.username,
				password=self.password)

			button.click()

		self.report("logging in as " + self.username + "/" + self.password + ".")
		try_submit(driver, "input[name='cmd[doStandardAuthentication]']", do_login)

		change_password = False
		try:
			driver.find_element_by_css_selector("#il_prop_cont_current_password")
			change_password = True
		except NoSuchElementException:
			pass

		if change_password:
			# will only happen if admin setting "change password on first login" is enabled.
			self.report("changing password.")

			def do_change_password(button):
				set_inputs(
					driver,
					current_password=self.password,
					new_password=self.password + "_",
					new_password_retype=self.password + "_"
				)
				button.click()

			try_submit(self.driver, "input[name='cmd[savePassword]']", do_change_password)

		# only after login can we determine the user's language setting, that ILIAS properly reports
		# in the <html> tag. needed for checking exported XLS contents.
		self.language = driver.find_element_by_css_selector("html").get_attribute("lang")

		return self

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


def goto_administration_page(driver, ilias_url, panel_id):
	for i in range(2):
		try:
			wait_for_css(driver, "#mm_adm_tr", 1)
			driver.find_element_by_css_selector("#mm_adm_tr").click()

			wait_for_css(driver, "#%s" % panel_id)
			with wait_for_page_load(driver):
				driver.find_element_by_css_selector("#%s" % panel_id).click()

			return
		except:
			with wait_for_page_load(driver):
				driver.get(ilias_url)

	raise InteractionException("going to admin page %s failed." % panel_id)


def goto_test_administration(driver, ilias_url):
	goto_administration_page(driver, ilias_url, "mm_adm_assf")


def goto_user_administration(driver, ilias_url):
	goto_administration_page(driver, ilias_url, "mm_adm_usrf")


def goto_editor_administration(driver, ilias_url):
	goto_administration_page(driver, ilias_url, "mm_adm_adve")


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


def delete_users(driver, ilias_url, username_prefix, n):
	n_clicked = 0

	while n_clicked < n:
		goto_user_administration(driver, ilias_url)

		try:
			activator = driver.find_element_by_css_selector(".ilTableFilterActivator")
			activator.click()
		except WebDriverException:
			pass

		apply_filter = "input[name='cmd[applyFilter]']"
		wait_for_css_visible(driver, apply_filter)

		set_element_value_by_css(driver, "input[name='query']", username_prefix)
		driver.find_element_by_css_selector(apply_filter).click()
		n_clicked_old = n_clicked

		for tr in driver.find_elements_by_css_selector("table tr"):
			for a in tr.find_elements_by_css_selector("td a"):
				if a.text.strip().startswith(username_prefix):
					for checkbox in tr.find_elements_by_css_selector("input[type='checkbox']"):
						checkbox.click()
						n_clicked += 1

		if n_clicked_old == n_clicked:  # error - not all users found.
			break

		Select(driver.find_element_by_css_selector('select[name="selected_cmd"]')).select_by_value("deleteUsers")
		with wait_for_page_load(driver):
			driver.find_element_by_css_selector('input[name="select_cmd"]').click()

		with wait_for_page_load(driver):
			driver.find_element_by_name('cmd[confirmdelete]').click()

	return n_clicked


def verify_admin_setting(name, value, expected, log):
	if value != expected:
		raise InteractionException("wrong administration setting: %s must be %s." % (name, expected))
	log.append("%s is %s." % (name, expected))


def verify_admin_settings(driver, workarounds, ilias_url, report):
	log = []

	goto_test_administration(driver, ilias_url)
	report("verifying test admin settings.")

	verify_admin_setting(
		"locking for tests",
		driver.find_element_by_id("ass_process_lock").is_selected(),
		True,
		log)

	lock_mode = dict()
	for s in ('ass_process_lock_mode_file', 'ass_process_lock_mode_db'):
		lock_mode[s] = driver.find_element_by_id(s).is_selected()
		log.append("%s is %s." % (s, lock_mode[s]))

	# only ass_process_lock_mode_db is safe, as only ilAssQuestionProcessLockerDb
	# uses ilAtomQuery to build an atomic write using a DB transaction.

	if not lock_mode['ass_process_lock_mode_db']:
		raise Exception("need lock mode to be db")

	verify_admin_setting(
		"html export for essay questions",
		driver.find_element_by_id("export_essay_qst_with_html").is_selected(),
		True,
		log)

	goto_editor_administration(driver, ilias_url)
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

	def get_username(self):
		return self.username

	def get_password(self):
		return self.password


def create_users_xml(base_url, tmp_users):
	users = Element('Users')
	SubElement(users, 'UDFDefinitions')

	children = []
	for tmp_user in tmp_users:
		user = Element('User', Language='de', Action='Update')
		children.append(user)

		SubElement(user, 'Login').text = tmp_user.get_username()
		SubElement(user, 'Password', Type='PLAIN').text = tmp_user.get_password()

		SubElement(user, 'Firstname').text = tmp_user.get_username()
		SubElement(user, 'Lastname').text = 'user'
		SubElement(user, 'Gender').text = 'm'
		SubElement(user, 'Email').text = 'ilias@localhost'

		SubElement(user, 'Role', Id='il_0_role_4', Type='Global').text = 'User'
		SubElement(user, 'Active').text = 'true'
		SubElement(user, 'TimeLimitOwner').text = '7'
		SubElement(user, 'TimeLimitUnlimited').text = '1'
		SubElement(user, 'TimeLimitMessage').text = '0'
		SubElement(user, 'AuthMode', type='default')
		SubElement(user, 'ApproveDate').text = '2018-01-31 00:00:00'

	users.extend(children)

	return ''.join([
		'<?xml version="1.0" encoding="utf-8"?>',
		'<!DOCTYPE Users PUBLIC "-//ILIAS//DTD UserImport//EN" "%s/xml/ilias_user_5_1.dtd">' % base_url,
		tostring(users).decode("utf8")
	])


class UsersBackend:
	def __init__(self, driver, ilias_url, report):
		self.driver = driver
		self.ilias_url = ilias_url
		self.report = report
		self.as_batch = True

	def create(self, prefix, n):
		self.report("creating %d users." % n)
		users = []
		if self.as_batch:
			users = self._create_n_users(prefix, n)
		else:
			for i in range(n):
				users.append(self._create_1_user(prefix, i))
		self.report("done creating users.")
		return users

	def destroy(self, prefix, users):
		if self.as_batch:
			self._delete_n_users(prefix, users)
		else:
			for user in users:
				self._delete_1_user(prefix, user)

	def _create_temporary_user(self, prefix, unique_id):
		user = TemporaryUser()

		# note: self.username must always stay <= 31 chars, as Excel tab names are limited to that
		# size and we fail to match names if names are longer here.
		user.username = prefix + str(unique_id)
		user.password = "dev1234"

		return user

	def _create_n_users(self, prefix, n):
		parsed = urlparse(self.driver.current_url)
		base_url = parsed.scheme + "://" + parsed.netloc + '/'.join(parsed.path.split('/')[:-1])

		xml_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tmp", "users.xml"))

		users = []
		for i in range(n):
			users.append(self._create_temporary_user(prefix, i))
		xml = create_users_xml(base_url, users)

		with open(xml_path, "w") as f:
			f.write(xml)

		goto_user_administration(self.driver, self.ilias_url)

		with wait_for_page_load(self.driver):
			self.driver.find_element_by_xpath("//a[contains(@href, 'cmd=importUserForm')]").click()

		import_button = self.driver.find_element_by_name('cmd[importUserRoleAssignment]')

		with wait_for_page_load(self.driver):
			self.driver.find_element_by_css_selector("#il_prop_cont_importFile input").send_keys(xml_path)
			import_button.click()

		with wait_for_page_load(self.driver):
			self.driver.find_element_by_css_selector("option[value='update_on_conflict']").click()
			import_users_button = self.driver.find_element_by_name('cmd[importUsers]')
			interact(self.driver, lambda: import_users_button.click())

		return users

	def _delete_n_users(self, prefix, users):
		try:
			n = delete_users(self.driver, self.ilias_url, prefix, len(users))
			self.report("deleted %d user(s)." % n)
		except:
			self.report("deletion of user failed.")
			self.report(traceback.format_exc())

	def _create_1_user(self, prefix, unique_id):
		user = self._create_temporary_user(prefix, unique_id)

		def perform_action():
			goto_user_administration(self.driver, self.ilias_url)
			self.report("creating user %s." % user.username)
			add_user(self.driver, user.username, user.password)

		interact(self.driver, perform_action)

		return user

	def _delete_1_user(self, prefix, user):
		try:
			n = delete_users(self.driver, self.ilias_url, user.username, 1)
			self.report("deleted %d user(s)." % n)
		except:
			self.report("deletion of user failed.")
			self.report(traceback.format_exc())


class UsersFactory:
	def __init__(self, test, n):
		self.test = test
		self.n = n

		self.prefix = datetime.datetime.today().strftime('tu_%Y%m%d%H%M%S') + '_'
		self.users = None

		if self.test.recycled_users:
			prefix, users = self.test.recycled_users
			if len(users) == n:
				self.prefix = prefix
				self.users = users
				self.test.recycled_users = None

		self.recycle = False

	def acquire(self, make_backend):
		assert self.prefix is not None
		if not self.users:
			self.users = make_backend().create(self.prefix, self.n)
		return self.users

	def release(self, make_backend):
		if self.recycle:
			self.test.recycled_users = (self.prefix, self.users)
		else:
			make_backend().destroy(self.prefix, self.users)

		self.users = None
		self.prefix = None


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
	def __init__(self, driver, ilias_url, username, report, context, questions, exam_configuration):
		self.driver = driver

		self.ilias_url = ilias_url
		parsed_url = urlparse(self.ilias_url)
		self.ilias_base_url = parsed_url.scheme + "://" + parsed_url.netloc + parsed_url.path
		self.client_id = parse_qs(parsed_url.query)['client_id']

		self.username = username
		self.report = report
		self.context = context
		self.questions = questions
		self.exam_configuration = exam_configuration
		self.answers = dict()
		self.protocol = []
		self.dts = []
		self.protocol.append((time.time(), "test", "entered test."))

	def add_protocol(self, s):
		self.protocol.append((time.time(), "test", s))

	def close(self):
		self.report("finishing test.")

		finish_test_css = 'a[data-nextcmd="finishTest"]'

		def finish_test(finish_button):
			finish_button.click()
			self.confirm_save()

		def confirm_finish(button):
			button.click()

		try:
			try_submit(self.driver, finish_test_css, finish_test, allow_reload=True)

			try_submit(self.driver, 'input[name="cmd[confirmFinish]"]', confirm_finish, allow_empty=True)

		except WebDriverException:
			raise InteractionException("failed to properly finish test")

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

		self.verify_answer(after_crash=True)

	def _click_save(self, css, n_tries=5):
		def click_to_save(button):
			button.click()
			self.confirm_save()

		with measure_time(self.dts):
			try_submit(self.driver, css, click_to_save, allow_reload=False, n_tries=n_tries)

	def _has_element(self, get_element):
		while True:
			try:
				get_element()
				return True
			except NoSuchElementException:
				return False
			except TimeoutException:
				pass

	def goto_first_question(self):
		def find_button():
			return self.driver.find_element_by_css_selector(
				'a[data-nextcmd="previousQuestion"]')

		while self._has_element(find_button):
			self.report("goto previous question.")
			self._click_save('a[data-nextcmd="previousQuestion"]')

	def goto_next_question(self):
		self.protocol.append((time.time(), "test", "goto next question."))

		def find_button():
			return self.driver.find_element_by_css_selector(
				'a[data-nextcmd="nextQuestion"]')

		if self._has_element(find_button):
			self.report("goto next question.")
			self._click_save('a[data-nextcmd="nextQuestion"]')
			return True
		else:
			return False

	def goto_next_or_previous_question(self, context, random_dir=False):
		self.protocol.append((time.time(), "test", "goto next or previous question."))

		options = ('next', 'previous')
		if random_dir and context.random.random() < 0.5:
			options = reversed(options)

		for command in options:
			css = 'a[data-nextcmd="%sQuestion"]' % command

			def find_button():
				return self.driver.find_element_by_css_selector(css)

			if self._has_element(find_button):
				self.report("goto %s question." % command)
				self._click_save(css)

				return True

		return False

	def assert_error_on_save(self, context):
		self.protocol.append((time.time(), "test", "checking error on invalid save."))

		sequence_id = self.get_sequence_id()
		self.goto_next_or_previous_question(context, random_dir=True)

		err_text = None

		# after save, we should be still on the same page and see an error, like e.g.
		# "please enter a numeric value." if we entered text in a numeric gap.
		if self.get_sequence_id() != sequence_id:
			err_text = "save succeeded even though saved data was invalid."

		if err_text is None:
			try:
				self.driver.find_element_by_css_selector('div.alert-danger')
			except NoSuchElementException:
				err_text = "save presented no error though saved data was invalid."

		if err_text:
			self.protocol.append((time.time(), "test", err_text))
			raise IntegrityException(err_text)

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

	def get_sequence_id(self, allow_reload=False):
		exc = []

		for _ in range(3):
			url = None
			try:
				url = self.driver.current_url
				return int(http_get_parameters(url)["sequence"])
			except:
				exc.append('url "%s" / %s' % (url, traceback.format_exc()))
				self.report('get_sequence_id failed on url %s' % url)

				if url is not None:
					allow_reload = True  # once we were thrown out, we may as well reload.

				is_resumed = False
				try:
					# sometimes we get kicked out and we need _try_start_or_resume to resume
					# the test. allow this as non-error.
					is_resumed = self._try_start_or_resume(True)
					if is_resumed:
						self.report('starting or resuming test after it spuriously paused.')
					is_resumed = True
				except:
					pass

				self.report('is_resumed = %s' % is_resumed)

				if not is_resumed:
					if not allow_reload:
						time.sleep(1)
					else:
						with wait_for_page_load(self.driver):
							self.driver.refresh()

		self.report('get_sequence_id failed: %s' % '\n\n'.join(exc))

		raise create_detailed_exception(self.driver)

	def _get_debug_info(self, question_title):
		base_url = self.ilias_base_url + '/Customizing/uni-regensburg/extensions/'
		cookies = dict((cookie['name'], cookie['value']) for cookie in self.driver.get_cookies())

		info = dict()

		try:
			r = requests.get(base_url + 'Versions/debug.php', cookies=cookies, params=dict(
				client_id=self.client_id,
				question=question_title
			))
			info['version_log.html'] = r.text
		except:
			pass

		try:
			r = requests.get(base_url + 'RequestLog/debug.php', cookies=cookies, params=dict(
				client_id=self.client_id
			))
			info['request_log.html'] = r.text
		except:
			pass

		return info

	def create_answer(self):
		page_title = None

		for i in range(3):
			try:
				page_title = self.driver.find_element_by_css_selector(".ilc_page_title_PageTitle")
			except (NoSuchElementException, TimeoutException):
				with wait_for_page_load(self.driver):
					self.driver.refresh()

		if page_title is None:
			raise InteractionException("no question title found.")

		title = page_title.text

		if title not in self.questions:
			raise InteractionException("no question content found for '%s'." % page_title)

		self.report('entering question "' + title + '"')

		answer = self.questions[title].create_answer(
			self.driver, AnswerProtocol(title, self._get_debug_info))

		sequence_id = self.get_sequence_id()
		assert sequence_id not in self.answers
		self.answers[sequence_id] = answer

		return answer

	def randomize_answer(self):
		sequence_id = self.get_sequence_id(True)
		if sequence_id not in self.answers:
			self.create_answer()
		answer = self.answers[sequence_id]
		self.report('answering question "%s" [%d].' % (answer.question.title, sequence_id))
		valid = answer.randomize(self.context)
		answer.verify(self.context, after_crash=False)
		return valid

	def verify_answer(self, after_crash=False):
		sequence_id = self.get_sequence_id()
		if sequence_id not in self.answers:
			raise InteractionException("cannot verify unknown answer " + str(sequence_id))

		answer = self.answers[sequence_id]
		self.report('verifying question "%s" [%d].' % (answer.question.title, sequence_id))

		interact(self.driver, lambda: answer.verify(self.context, after_crash))

	def copy_protocol(self, result):
		protocol = self.protocol[:]

		for sequence_id, answer in self.answers.items():
			encoded = answer.to_dict(self.context, "de")
			question_title = encoded["title"]

			for t, what in encoded["protocol"]["lines"]:
				protocol.append((t, question_title, what))

			for filename, what in encoded["protocol"]["files"].items():
				result.attach_file(filename, what)

		protocol.sort(key=lambda x: x[0])  # by time
		protocol_lines = [
			"%s [%s] %s" % (
				datetime.datetime.fromtimestamp(t).strftime('%H:%M:%S'),
				title,
				what) for t, title, what in protocol]

		result.attach_protocol(protocol_lines)

	def get_expected_result(self, language):
		if self.exam_configuration.score_cutting == ScoreCutting.QUESTION:
			def clip_question_score(score):
				return max(score, Decimal(0))
		else:
			def clip_question_score(score):
				return score  # do not clip on question level

		def format_score(score):
			s = str(score)
			if '.' in s:
				s = s.rstrip('0')
				if s.endswith('.'):
					s = s.rstrip('.')
			return s

		result = Result(origin=Origin.recorded)

		for sequence_id, answer in self.answers.items():
			encoded = answer.to_dict(self.context, language)
			question_title = encoded["title"]
			key_prefix = ("question", question_title, "answer")

			# format of full result key:
			# ("question", title of question, "answer", key_1, ..., key_n)

			for dimension_key, dimension_value in encoded["answers"].items():
				result.add(Result.key(*key_prefix, dimension_key), dimension_value)

			result.add(
				("question", question_title, "score"),
				format_score(clip_question_score(answer.current_score)))

		expected_total_score = Decimal(0)
		for answer in self.answers.values():
			expected_total_score += clip_question_score(answer.current_score)

		# always clip final score on 0.
		expected_total_score = max(expected_total_score, Decimal(0))

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

		self.questions = None
		self.exam_configuration = None

		self.cached_link = None
		self.recycled_users = None

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


class TestDriver:
	def __init__(self, driver, test, username, workarounds, ilias_url, report):
		self.driver = driver
		self.test = test
		self.username = username
		self.workarounds = workarounds

		self.ilias_url = ilias_url
		parsed_url = urlparse(self.ilias_url)
		self.ilias_base_url = parsed_url.scheme + "://" + parsed_url.netloc + parsed_url.path
		self.client_id = parse_qs(parsed_url.query)['client_id']

		self.report = report
		self.autosave_time = 5
		self.allow_resume = False

	def import_test(self):
		driver = self.driver

		self.report("importing test.")

		# goto Magazin.
		driver.get(self.ilias_base_url + ("/goto.php?target=root_1&client_id=%s" % self.client_id))

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
			raise InteractionException("test import button not found.")
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

	def get_gui_scores(self, user_ids):
		def fetch_scores():
			with wait_for_page_load(self.driver):
				self.goto_statistics()

			reached = None
			login = None

			for index, a in enumerate(self.driver.find_elements_by_css_selector("#tst_eval_all thead th a")):
				nav = http_get_parameters(a.get_attribute("href"))["tst_eval_all_table_nav"].split(":")
				if nav[0] == "reached":
					reached = index
				elif nav[0] == "login":
					login = index

			if reached is not None and login is not None:
				return reached, login
			else:
				raise InteractionException("unable to get gui scores")

		reached, login = interact(self.driver, fetch_scores, refresh=True)

		# configure table to show up to 800 entries.
		form = self.driver.find_element_by_css_selector("#evaluation_all")

		button = form.find_element_by_css_selector("#ilAdvSelListAnchorText_sellst_rows_tst_eval_all")
		button.click()

		href_800 = form.find_element_by_css_selector("#sellst_rows_tst_eval_all_800")
		#span_800 = group.find_element_by_xpath("//span[contains(text(), '800')]")
		#href_800 = span_800.find_element_by_xpath("..")
		href_800.click()

		# now read out the scores for all participants.
		scores = dict()
		unassigned = dict(("[%s]" % name, name) for name in user_ids)

		for tr in self.driver.find_elements_by_css_selector("#tst_eval_all tbody tr"):
			columns = list(tr.find_elements_by_css_selector("td"))
			key = columns[login].text.strip()
			user_id = unassigned.get(key)
			if user_id:
				del unassigned[key]
				score = re.split("\s+", columns[reached].text)
				scores[user_id] = Decimal(score[0])

		if len(unassigned) > 0:
			raise InteractionException("failed to read out gui scores for %s" % ",".join(unassigned.keys()))

		return scores

	def parse_exam_configuration(self):
		self.report("parsing exam configuration.")

		self.goto_scoring()

		settings = ExamConfiguration()
		for name in ('count_system', 'mc_scoring', 'score_cutting', 'pass_scoring'):
			for radio in self.driver.find_elements_by_css_selector('input[name="%s"]' % name):
				if radio.is_selected():
					setter = getattr(settings, 'set_%s' % name)
					setter(int(radio.get_attribute('value')))

		return settings

	def parse_question_definitions(self, settings):
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

		question_classes = dict(
			assclozetestgui=ClozeQuestion,
			asssinglechoicegui=SingleChoiceQuestion,
			assmultiplechoicegui=MultipleChoiceQuestion,
			asskprimchoicegui=KPrimQuestion,
			asstextquestiongui=LongTextQuestion,
			assmatchingquestiongui=MatchingQuestion
		)

		questions = dict()
		for href in hrefs:
			parameters = http_get_parameters(href)
			if "eqid" in parameters:
				with wait_for_page_load(self.driver):
					self.driver.get(href)

				title = driver.find_element_by_css_selector("#title").get_attribute("value")
				if title in questions:
					# our data structures use question titles as a primary key for questions.
					raise InteractionException('duplicate question titled "%s" is not allowed.' % title)

				cmd_class = http_get_parameters(self.driver.current_url)["cmdClass"]
				question_class = question_classes.get(cmd_class)
				if question_class is None:
					raise NotImplementedException("unsupported question gui cmd_class " + cmd_class)

				self.report('parsing "%s" as %s.' % (title, question_class.__name__))
				questions[title] = question_class(driver, title, settings)

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

		if not found:  # no participants in test
			return

		self.driver.find_element_by_css_selector('input[name="cmd[confirmDeleteAllUserResults]"]').click()

	def get_test_url(self):
		if not self.test.cached_link:
			self.goto()
		return self.test.cached_link

	def goto(self, url=None):
		if self.test.cached_link is None and url:
			self.test.cached_link = url

		if self.test.cached_link is not None:
			with wait_for_page_load(self.driver):
				self.driver.get(self.test.cached_link)
			return True

		driver = self.driver

		for i in range(5):
			with wait_for_page_load(driver):
				driver.get(self.ilias_url)

			driver.find_element_by_css_selector(".glyphicon-search").click()
			with wait_for_page_load(driver):
				driver.find_element_by_css_selector('#mm_search_form input[type="submit"]').click()

			#self.browser.visit(self.ilias_url + "/ilias.php?baseClass=ilSearchController")
			self.report('searching for test "%s".' % self.test.get_title())

			search_input = None

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
		for i in range(10):
			for link in driver.find_elements_by_partial_link_text(self.test.get_title()):
				if link.is_displayed():
					if link.text.strip() == self.test.get_title():
						with wait_for_page_load(driver):
							link.click()
						self.test.cached_link = driver.current_url
						return True
			time.sleep(1)

		raise InteractionException("test '%s' was not found in ILIAS" % self.test.get_title())

	def _try_start_or_resume(self, force_allow_resume=False):
		resume_player = None
		try:
			resume_player = self.driver.find_element_by_css_selector("input[name='cmd[resumePlayer]']")
		except NoSuchElementException:
			pass

		if resume_player:
			if not (self.allow_resume or force_allow_resume):
				raise InteractionException("test has already been started by this user. aborting.")
			with wait_for_page_load(self.driver):
				resume_player.click()
				return True
		else:
			try:
				try_submit(self.driver, "input[name='cmd[startPlayer]']", lambda button: button.click())
				return True
			except NoSuchElementException:
				return False

	def start(self, context, questions, exam_configuration, allow_resume=False):
		self.report("starting test.")
		self.allow_resume = allow_resume
		if not self._try_start_or_resume():
			raise InteractionException("user does not have rights to start this test. aborting.")
		return ExamDriver(self.driver, self.ilias_url, self.username, self.report, context, questions, exam_configuration)

