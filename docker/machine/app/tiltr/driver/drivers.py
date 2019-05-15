#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import os
import datetime
import io
import re
import json
import requests
import traceback
from urllib.parse import urlparse, parse_qs
from decimal import *
from collections import namedtuple, defaultdict

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

from tiltr.data.exceptions import *
from tiltr.question import *
from tiltr.data.result import *
from tiltr.question.protocol import AnswerProtocol
from tiltr.data.pdf import PDF


UserStat = namedtuple('UserStat', ['score', 'percentage', 'short_mark'])

Mark = namedtuple('Mark', ['level', 'short', 'official'])

class Marks:
	def __init__(self, marks):
		self._marks = marks

	def lookup(self, percentage):
		best = None

		for mark in self._marks:
			if percentage >= mark.level:
				if best is None or mark.level > best.level:
					best = mark

		return best


class Login:
	def __init__(self, user_driver, username, password):
		self.driver = user_driver.driver
		self.report = user_driver.report
		self.url = user_driver.ilias_url
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


class ILIASVersion:
	def __init__(self, text, as_tuple):
		self.text = text
		self._tuple = as_tuple

	def as_tuple(self):
		return self._tuple

	def __lt__(self, v):
		return self._tuple < v

	def __gt__(self, v):
		return self._tuple > v

	def __le__(self, v):
		return self._tuple <= v

	def __ge__(self, v):
		return self._tuple >= v


class ILIASDriver:
	def __init__(self, driver, url, version, workarounds, settings, report):
		self.driver = driver

		self.url = url
		self.version = version

		self.workarounds = workarounds
		self.settings = settings

		self.report = report

	def _goto_administration_page(self, panel_id):
		driver = self.driver

		for i in range(2):
			try:
				if self.version >= (5, 4):
					for a in driver.find_elements_by_css_selector("#ilTopNav li.dropdown > a"):
						if a.text.strip().lower() == "administration":
							a.click()
							break
				else:
					wait_for_css(driver, "#mm_adm_tr", 1)
					driver.find_element_by_css_selector("#mm_adm_tr").click()

				wait_for_css(driver, "#%s" % panel_id)

				with wait_for_page_load(driver):
					href = driver.find_element_by_css_selector("#%s" % panel_id).get_attribute("href")
					driver.get(href)
					return

					# work around "element not clickable" exception in Selenium
					#element = driver.find_element_by_css_selector("#%s" % panel_id)
					#driver.execute_script("$(arguments[0]).click();", element)
					#driver.find_element_by_css_selector("#%s" % panel_id).click()

				return
			except:
				traceback.print_exc()

				with wait_for_page_load(driver):
					driver.get(self.url)

		raise InteractionException("going to admin page %s failed." % panel_id)

	def goto_test_administration(self):
		self._goto_administration_page("mm_adm_assf")

	def goto_user_administration(self):
		self._goto_administration_page("mm_adm_usrf")

	def goto_editor_administration(self):
		self._goto_administration_page("mm_adm_adve")

	def _verify_admin_setting(self, name, value, expected, log):
		if value != expected:
			raise InteractionException("wrong administration setting: %s must be %s." % (name, expected))
		log.append("%s is %s." % (name, expected))

	def verify_admin_settings(self):
		log = []
		driver = self.driver

		# test admin settings.

		self.goto_test_administration()
		self.report("verifying test admin settings.")

		self._verify_admin_setting(
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

		self._verify_admin_setting(
			"html export for essay questions",
			driver.find_element_by_id("export_essay_qst_with_html").is_selected(),
			True,
			log)

		if int(self.settings.num_readjustments) > 0:
			def checked(css):
				return [e.is_selected() for e in driver.find_elements_by_css_selector(css)]

			enabled = checked('input[name="chb_scoring_adjustment[]"]')
			enabled.extend(checked("#il_prop_cont_chb_scoring_adjust input"))

			if not all(enabled):
				raise InteractionException(
					"in order to verify readjustments, please enable readjustments "
					"for all question types in the T&A administration")

		# editor admin settings.

		self.goto_editor_administration()
		self.report("verifying editor admin settings.")

		driver.find_element_by_css_selector("#tab_adve_rte_settings a").click()

		if self.workarounds.force_tinymce:
			self._verify_admin_setting(
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
			self._verify_admin_setting(
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
		SubElement(user, 'ApproveDate').text = '2018-2019-01-31 00:00:00'

	users.extend(children)

	return ''.join([
		'<?xml version="1.0" encoding="utf-8"?>',
		'<!DOCTYPE Users PUBLIC "-//ILIAS//DTD UserImport//EN" "%s/xml/ilias_user_5_1.dtd">' % base_url,
		tostring(users).decode("utf8")
	])


class UsersBackend:
	def __init__(self, ilias_driver, report):
		self.ilias_driver = ilias_driver
		self.driver = ilias_driver.driver
		self.report = report
		self.batch_limit = 2

	def _add_user(self, driver, username, password):
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

	def _delete_users(self, driver, username_prefix, n):
		n_clicked = 0

		while n_clicked < n:
			self.ilias_driver.goto_user_administration()

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

	def create(self, prefix, n):
		self.report("creating %d users." % n)
		users = []
		if n >= self.batch_limit:
			users = self._create_n_users(prefix, n)
		else:
			for i in range(n):
				users.append(self._create_1_user(prefix, i))
		self.report("done creating users.")
		return users

	def destroy(self, prefix, users):
		if len(users) >= self.batch_limit:
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

		xml_path = os.path.abspath(os.path.join("/tiltr/tmp", "users.xml"))

		users = []
		for i in range(n):
			users.append(self._create_temporary_user(prefix, i))
		xml = create_users_xml(base_url, users)

		with open(xml_path, "w") as f:
			f.write(xml)

		self.ilias_driver.goto_user_administration()

		with wait_for_page_load(self.driver):
			self.driver.find_element_by_xpath("//a[contains(@href, 'cmd=importUserForm')]").click()

		self.report("uploading xml user file with %d users." % n)

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
			n = self._delete_users(self.driver, prefix, len(users))
			self.report("deleted %d user(s)." % n)
		except:
			self.report("deletion of user failed.")
			self.report(traceback.format_exc())

	def _create_1_user(self, prefix, unique_id):
		user = self._create_temporary_user(prefix, unique_id)

		def perform_action():
			self.ilias_driver.goto_user_administration()
			self.report("creating user %s." % user.username)
			self._add_user(self.driver, user.username, user.password)

		interact(self.driver, perform_action)

		return user

	def _delete_1_user(self, prefix, user):
		try:
			n = self._delete_users(self.driver, user.username, 1)
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

		if self.test.cache.recycled_users:
			prefix, users = self.test.cache.recycled_users
			if len(users) == n:
				self.prefix = prefix
				self.users = users
				self.test.cache.recycled_users = None

		self.recycle = False

	def acquire(self, make_backend):
		assert self.prefix is not None
		if not self.users:
			self.users = make_backend().create(self.prefix, self.n)
		return self.users

	def release(self, make_backend):
		if self.recycle:
			self.test.cache.recycled_users = (self.prefix, self.users)
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

		self.report('waiting for %.1f seconds.' % wait)

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

	def assert_error_on_save(self, invalid_answers, context):
		if context.workarounds.dont_test_invalid_save:
			return

		self.protocol.append((
			time.time(), "test",
			"checking error when saving %d invalid answers:" % len(invalid_answers)))
		for x in invalid_answers:
			self.protocol.append((time.time(), "test", "invalid answer: %s" % json.dumps(x)))

		sequence_id = self.get_sequence_id()

		# we actually try to submit twice to detect an additional class of errors,
		# compare https://github.com/bheyser/ILIAS/pull/7
		n_retries = 2

		for retry in range(n_retries):
			self.goto_next_or_previous_question(context, random_dir=True)

			err_text = None

			# after save, we should be still on the same page and see an error, like e.g.
			# "please enter a numeric value." if we entered text in a numeric gap.
			if self.get_sequence_id() != sequence_id:
				err_text = "save succeeded even though saved data was invalid."

			if err_text is None:
				self.confirm_save()

				try:
					self.driver.find_element_by_css_selector('div.alert-danger')
				except NoSuchElementException:
					err_text = "save presented no error though saved data was invalid."

			if err_text:
				self.protocol.append((time.time(), "test", err_text))
				raise InvalidSaveException(err_text)

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
			time.sleep(1)

			try:
				button = self.driver.find_element_by_id("tst_save_on_navigation_button")
			except NoSuchElementException:
				return

			try:
				if button.is_displayed():
					# prevent popup on future navigation.
					self.driver.find_element_by_id("save_on_navigation_prevent_confirmation").click()
					button.click()
			except:
				# guard against StaleElementReferenceException
				traceback.print_exc()
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
			raise InteractionException("no question content found for '%s'." % title)

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

	def add_protocol_to_result(self, result):

		lines = list(itertools.chain(
			self.protocol, *[answer.protocol_lines for answer in self.answers.values()]))

		lines.sort(key=lambda x: x[0])  # by time

		result.attach_protocol([
			"%s [%s] %s" % (
				datetime.datetime.fromtimestamp(t).strftime('%H:%M:%S'),
				title,
				what) for t, title, what in lines])

		for answer in self.answers.values():
			for filename, what in answer.protocol_files.items():
				result.attach_file(filename, what.encode('utf8'))

	def get_expected_result(self, language):
		result = Result(origin=Origin.recorded)

		maximum_score = Decimal(0)
		for question in self.questions.values():
			maximum_score += question.get_maximum_score(self.context)

		expected_reached_score = Decimal(0)
		for answer in self.answers.values():
			score = answer.add_to_result(
				result, self.context,
				language, self.exam_configuration.clip_answer_score)
			expected_reached_score += score

		# always clip final score on 0.
		expected_reached_score = max(expected_reached_score, Decimal(0))

		expected_reached_percentage = (100 * expected_reached_score) / maximum_score

		mark = Marks(self.exam_configuration.marks).lookup(expected_reached_percentage)

		result.add_as_formatted_score(("xls", "score_maximum"), maximum_score)

		for channel in ("xls", "statistics_tab"):
			result.add_as_formatted_score((channel, "score_reached"), expected_reached_score)
			result.add((channel, "short_mark"), str(mark.short).strip())

		result.add(("statistics_tab", "percentage_reached"), Result.format_percentage(expected_reached_percentage))

		self.add_protocol_to_result(result)
		result.attach_performance_measurements(self.dts)
		return result


class TestCache:
	def __init__(self):
		self.cached_link = None
		self.recycled_users = None
		self.questions = None
		self.exam_configuration = None

	def transfer_invariants(self, cache):
		# transfer those attributes from "cache" that are invariant wrt
		# test runs (i.e. won't change on reimports).
		self.questions = cache.questions
		self.exam_configuration = cache.exam_configuration


class AbstractTest:
	def __init__(self):
		self.cache = TestCache()

	def get_title(self):
		raise NotImplementedError()


class PackagedTest(AbstractTest):
	def __init__(self, test_id):
		super().__init__()

		self.test_id = test_id
		self.path = os.path.abspath(os.path.join(
			"/tiltr/tests", test_id + ".zip"))

		with ZipFile(self.path, 'r') as zf:
			main = None
			for name in zf.namelist():
				if re.match(r"^[^/]*/[^/]+_tst_[^/]+\.xml$", name):
					main = name
					break

			if main is None:
				raise RuntimeError("did not find test xml in zip")

			root = ET.fromstring(zf.read(main))

		self.title = root.findall(".//Title")[0].text

	def get_id(self):
		return self.test_id

	def get_path(self):
		return self.path

	def get_title(self):
		return self.title

	@staticmethod
	def list():
		tests = list()

		for filename in os.listdir("/tiltr/tests"):
			if filename.endswith(".zip"):
				try:
					test = PackagedTest(os.path.splitext(filename)[0])
					tests.append((test.get_title(), test.get_id()))
				except:
					print("could not inspect Test %s." % filename)
					traceback.print_exc()

		return sorted(tests, key=lambda t: t[0])


class ImportedTest(AbstractTest):
	def __init__(self, title):
		super().__init__()
		self.title = title

	def get_title(self):
		return self.title


def extract_first_number(s):
	m = re.search(r'\d+(\.\d+)?', s)
	if m:
		return m.group(0)
	else:
		raise InteractionException("could not extract number from '%s'" % s)


class TestDriver:
	def __init__(self, user_driver, test):
		self.driver = user_driver.driver
		self.user_driver = user_driver
		self.test = test

		self.ilias_url = user_driver.ilias_url
		self.ilias_base_url = user_driver.ilias_base_url
		self.client_id = user_driver.client_id
		self.ilias_version = user_driver.ilias_version

		self.report = user_driver.report
		self.autosave_time = 5
		self.allow_resume = False

	def _get_ref_id(self):
		url = self.driver.current_url
		return int(http_get_parameters(url)["ref_id"])

	def import_test_from_template(self):
		self.user_driver.import_test(self.test.get_path())

	def configure_test(self, workarounds, exam_configuration):
		self.make_online()
		self.configure_autosave(workarounds)
		self.configure_random_mark_schema(exam_configuration)

	def make_online(self):
		# activate the Test by setting it online.
		self.goto_settings()

		if not self.driver.find_element_by_id("online").is_selected():
			self.driver.execute_script('document.getElementById("online").click()')

		self.report("setting test online.")

		with wait_for_page_load(self.driver):
			self.driver.find_element_by_name("cmd[saveForm]").click()

	def configure_autosave(self, workarounds):
		self.goto_settings()

		autosave = self.driver.find_element_by_id("autosave")
		if workarounds.enable_autosave:
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

	def configure_random_mark_schema(self, exam_configuration):
		import random as rnd
		random = rnd.SystemRandom()

		n_grades = random.randint(2, 20)

		self.report("configuring %s random marks." % n_grades)

		def generate_numbers(n, fmt, ab):
			while True:
				numbers = set()
				for _ in range(n):
					numbers.add(fmt % random.uniform(*ab))
				if len(numbers) == n:
					break
			return sorted(list(numbers), key=lambda s: float(s))


		grades = generate_numbers(n_grades - 1, "%.1f", (1, 5.9))
		levels = generate_numbers(n_grades - 1, "%.2f", (0.01, 100))

		grades.append("6.0")
		levels = ["0.00"] + levels

		self.goto_mark_schema()

		for mark_checkbox in self.driver.find_elements_by_css_selector('input[name="marks[]"]'):
			mark_checkbox.click()

		with wait_for_page_load(self.driver):
			self.driver.find_element_by_css_selector(
				'input[name="cmd[deleteMarkSteps]"]').click()

		for _ in range(n_grades):
			with wait_for_page_load(self.driver):
				self.driver.find_element_by_css_selector(
					'button[name="cmd[addMarkStep]"]').click()

		entries = list(zip(reversed(grades), levels))
		rnd.shuffle(entries)  # enter in random order

		marks = list()
		for i, (grade, percentage) in enumerate(entries):
			official = "Note %s" % grade
			marks.append(Mark(short=grade, official=official, level=Decimal(percentage)))
			set_element_value(self.driver, self.driver.find_element_by_id("mark_short_%d" % i), grade)
			set_element_value(self.driver, self.driver.find_element_by_id("mark_official_%d" % i), official)
			set_element_value(self.driver, self.driver.find_element_by_id("mark_percentage_%d" % i), percentage)

		passed = self.driver.find_element_by_css_selector('input[name="passed_%d"]' % (n_grades - 1))
		if not passed.is_selected():
			passed.click()

		with wait_for_page_load(self.driver):
			self.driver.find_element_by_css_selector('input[name="cmd[saveMarks]"]').click()

		exam_configuration.marks = marks

	def goto_participants(self):
		assert self.goto()
		if self.ilias_version >= (5, 4):
			self.driver.find_element_by_css_selector("#tab_results a").click()
		else:
			self.driver.find_element_by_css_selector("#tab_participants a").click()

	def goto_settings(self):
		assert self.goto()
		self.driver.find_element_by_css_selector("#tab_settings a").click()

	def goto_mark_schema(self):
		self.goto_settings()
		self.driver.find_element_by_css_selector("#subtab_mark_schema").click()

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
		# if this fails, it might mean we have readjustments deactivated in the
		# administration settings. should have been checked by verify_admin_settings().
		self.driver.find_element_by_css_selector("#tab_scoringadjust a").click()

	def goto_manual_scoring(self):
		assert self.goto()
		self.driver.find_element_by_css_selector("#tab_manscoring").click()

	def apply_manual_scoring(self, question_title, scores):
		found = False

		select = self.driver.find_element_by_css_selector(".ilTableFilterInput #question")
		for option in select.find_elements_by_css_selector("option"):
			if question_title in option.text:
				Select(select).select_by_value(option.get_attribute("value"))
				found = True
				break

		if not found:
			raise InteractionException(
				"did not find question %s in manual scoring selection" % question_title)

		with wait_for_page_load(self.driver):
			apply_filter = self.driver.find_element_by_css_selector(
				'input[name="cmd[applyManScoringByQuestionFilter]"]')
			apply_filter.click()

		scoring_table = None
		for table in self.driver.find_elements_by_css_selector("table"):
			if table.get_attribute("id").startswith("man_scor_by_qst_"):
				scoring_table = table
				break

		if not scoring_table:
			raise InteractionException("did not find scoring table")

		for tr in scoring_table.find_elements_by_css_selector("tr"):
			cols = list(tr.find_elements_by_css_selector("td"))
			if cols:
				name = cols[0].text
				for username, score in scores.items():
					if username in name:
						points_input = cols[1].find_element_by_css_selector("input")
						set_element_value(self.driver, points_input, str(score))
						break

		with wait_for_page_load(self.driver):
			self.driver.find_element_by_css_selector(
				'input[name="cmd[saveManScoringByQuestion]"]').click()


	def _clean_exports(self):
		self.report("cleaning current exports.")
		select_all = None
		try:
			select_all = self.driver.find_element_by_css_selector('.ilTableSelectAll')
		except NoSuchElementException:
			pass
		if select_all:
			with wait_for_page_load(self.driver):
				select_all_id = select_all.find_element_by_css_selector("input").get_attribute("id")
				self.driver.execute_script('document.getElementById("%s").click()' % select_all_id)
				self.driver.find_element_by_name("cmd[confirmDeletion]").click()
			with wait_for_page_load(self.driver):
				self.driver.find_element_by_name("cmd[delete]").click()

	def _iterate_detailed_results(self, f):
		driver = self.driver
		ref_id = self._get_ref_id()

		row_index = 0
		while True:
			with wait_for_page_load(driver):
				self.goto_participants()

			# set filter to display up to 800 participants.
			dropdown = driver.find_element_by_id("ilAdvSelListAnchorText_sellst_rows_tst_participants_%d" % ref_id)
			dropdown.click()
			driver.find_element_by_id("sellst_rows_tst_participants_%d_800" % ref_id).click()

			trs = list(driver.find_elements_by_css_selector("#tst_participants_%d tbody tr" % ref_id))
			if row_index >= len(trs):
				break
			tr = trs[row_index]

			tds = list(tr.find_elements_by_css_selector("td"))
			if len(tds) < 2:
				row_index += 1
				continue

			user_id = tds[2].find_element_by_css_selector("label").text.strip()

			tr.find_element_by_css_selector("input[name='chbUser[]']").click()

			with wait_for_page_load(driver):
				select = Select(driver.find_element_by_css_selector(".ilTableCommandRowTop select"))
				select.select_by_value("showDetailedResults")
				driver.find_element_by_css_selector(".ilTableCommandRowTop input[type='submit']").click()

			f(user_id)

			row_index += 1

	def _export(self, format, filetype):
		self.goto_export()

		self._clean_exports()

		self.report("exporting %s." % format)
		with wait_for_page_load(self.driver):
			Select(self.driver.find_element_by_name("format")).select_by_value(format)
			self.driver.find_element_by_name("cmd[createExportFile]").click()

		filename = None
		url = None
		for a in self.driver.find_elements_by_css_selector("table a"):
			params = http_get_parameters(a.get_attribute("href"))
			if params.get('cmd', '') == "download" and params.get('file', '').endswith(".%s" % filetype):
				filename = params.get('file')
				url = a.get_attribute("href")
				break

		if url is None:
			raise InteractionException("could not find exported %s." % format)

		self.report("downloading exported %s." % format)

		cookies = dict((cookie['name'], cookie['value']) for cookie in self.driver.get_cookies())
		result = requests.get(url, cookies=cookies)
		return result.content, filename

	def export_xmlres(self):
		return self._export("xmlres", "zip")

	def export_xls(self):
		content, _ = self._export("csv", "xlsx")
		return content

	def export_pdf(self):
		self.report("exporting PDFs.")

		pdfs = dict()

		def get_pdf(user_id):
			assert user_id not in pdfs

			toolbar = self.driver.find_element_by_css_selector(".ilToolbarItems")
			for navbar in toolbar.find_elements_by_css_selector(".navbar-form"):
				if 'PDF' not in navbar.text:
					continue

				self.report("downloading PDF for %s." % user_id)

				url = navbar.find_element_by_css_selector("a").get_attribute("href")
				cookies = dict((cookie['name'], cookie['value']) for cookie in self.driver.get_cookies())
				result = requests.get(url, cookies=cookies)

				pdfs[user_id] = PDF(result.content)

		self._iterate_detailed_results(get_pdf)

		return pdfs

	def get_answers_from_details_view(self, questions):
		answers = defaultdict(dict)  # by user id

		def get_user_answers(user_id):
			user_answers = answers[user_id]

			for printview in self.driver.find_elements_by_css_selector(".questionPrintview"):
				text = printview.find_element_by_css_selector(".questionTitle").text

				# match e.g. "1. Zeichenaufgabe [ID: 197783]"
				m = re.match(r'^[0-9]+\.\s+([^[]+)\s+\[', text.strip())
				if m:
					question_title = m.group(1)

					if question_title in questions:
						a = questions[question_title].get_answer_from_details_view(printview)
						if a is not None:
							for k, v in a.items():
								user_answers[("question", self.question.title, "answer", k)] = v

		self._iterate_detailed_results(get_user_answers)

		return answers

	def get_results_from_results_tab(self, user_ids):
		# same as get_results_from_statistics_tab, but this time use "results" tab,
		# which displays similar information.

		driver = self.driver
		ref_id = self._get_ref_id()

		with wait_for_page_load(driver):
			self.goto_participants()

		# set filter to display up to 800 participants.
		dropdown = driver.find_element_by_id("ilAdvSelListAnchorText_sellst_rows_tst_participants_%d" % ref_id)
		dropdown.click()
		driver.find_element_by_id("sellst_rows_tst_participants_%d_800" % ref_id).click()

		# build column index.
		columns_index = dict()
		ths = list(driver.find_elements_by_css_selector("#tst_participants_%d thead tr th" % ref_id))
		for i, th in enumerate(ths):
			links = th.find_elements_by_css_selector("a")
			if links:
				p = http_get_parameters(links[0].get_attribute("href"))
				nav = p["tst_participants_%d_table_nav" % ref_id].split(":")
				columns_index[nav[0]] = i

		# gather information from table.
		stats = dict()

		for tr in driver.find_elements_by_css_selector("#tst_participants_%d tbody tr" % ref_id):
			columns_list = list(tr.find_elements_by_css_selector("td"))
			columns = dict((k, columns_list[i]) for k, i in columns_index.items())

			# we assume that the long mark form contains the numeric short mark form, e.g. "Note 1.5"
			short_mark = extract_first_number(columns['final_mark'].text)

			stats[columns['login'].text.strip()] = UserStat(
				score=Decimal(extract_first_number(columns['reached_points'].text)),
				percentage=Decimal(extract_first_number(columns['percent_result'].text)),
				short_mark=short_mark)

			# contents of the columns:
			# columns['login']  # username
			# columns['reached_points']  # e.g. "1 von 22"
			# columns['percent_result']  # e.g. "4.55 %"
			# columns['final_mark']  # e.g. "Note 3.2"

		missing = set(user_ids) - set(stats.keys())
		if missing:
			raise InteractionException("did not find entries in results tab for users %s" % missing)

		return stats

	def get_results_from_statistics_tab(self, user_ids):

		def fetch_column_index():
			with wait_for_page_load(self.driver):
				self.goto_statistics()

			index = dict()
			for i, a in enumerate(self.driver.find_elements_by_css_selector("#tst_eval_all thead th a")):
				nav = http_get_parameters(a.get_attribute("href"))["tst_eval_all_table_nav"].split(":")
				index[nav[0]] = i

			if all(k in index for k in ("reached", "mark", "login")):
				return index
			else:
				raise InteractionException("unable to get gui scores")

		columns_index = interact(self.driver, fetch_column_index, refresh=True)

		# configure table to show up to 800 entries.
		form = self.driver.find_element_by_css_selector("#evaluation_all")

		button = form.find_element_by_css_selector("#ilAdvSelListAnchorText_sellst_rows_tst_eval_all")
		button.click()

		href_800 = form.find_element_by_css_selector("#sellst_rows_tst_eval_all_800")
		#span_800 = group.find_element_by_xpath("//span[contains(text(), '800')]")
		#href_800 = span_800.find_element_by_xpath("..")
		href_800.click()

		# now read out the scores for all participants.
		stats = dict()
		unassigned = dict(("[%s]" % name, name) for name in user_ids)

		for tr in self.driver.find_elements_by_css_selector("#tst_eval_all tbody tr"):
			columns_list = list(tr.find_elements_by_css_selector("td"))
			columns = dict((k, columns_list[i]) for k, i in columns_index.items())

			key = columns["login"].text.strip()
			user_id = unassigned.get(key)
			if user_id:
				del unassigned[key]

				score_text = columns["reached"].text  # e.g. "13.75 von 38.2 (35.99 %)"

				m = re.search(r'\(([^%]+)%\s*\)', score_text)
				if not m:
					raise InteractionException("unexpected score text format")

				stats[user_id] = UserStat(
					score=Decimal(extract_first_number(score_text)),
					percentage=Decimal(m.group(1).strip()),
					short_mark=columns["mark"].text.strip())

		if len(unassigned) > 0:
			raise InteractionException(
				"failed to read out gui scores for %s" % ",".join(unassigned.keys()))

		return stats

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

		constructors = dict(
			assclozetestgui=ClozeQuestion,
			asssinglechoicegui=SingleChoiceQuestion,
			assmultiplechoicegui=MultipleChoiceQuestion,
			asskprimchoicegui=KPrimQuestion,
			asstextquestiongui=LongTextQuestion,
			assmatchingquestiongui=MatchingQuestion,
			asspaintquestiongui=PaintQuestion,
			asscodequestiongui=CodeQuestion
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
				constructor = constructors.get(cmd_class)
				if constructor is None:
					raise NotImplementedException("unsupported question gui cmd_class " + cmd_class)

				self.report('parsing "%s" as %s.' % (title, constructor.__name__))
				questions[title] = constructor(driver, title, settings)

		return questions

	def delete_all_participants(self):
		self.goto_participants()
		self.report("deleting all test participants.")

		found = False
		for form in self.driver.find_elements_by_css_selector(".navbar-form"):
			for a in form.find_elements_by_css_selector("a.btn"):
				if "cmd=deleteAllUserResults" in a.get_attribute("href"):
					a.click()
					found = True
					break
			if found:
				break

		if not found:  # no participants in test
			return

		self.driver.find_element_by_css_selector(
			'input[name="cmd[confirmDeleteAllUserResults]"]').click()

	def get_test_url(self):
		if not self.test.cache.cached_link:
			self.goto()
		return self.test.cache.cached_link

	def goto_or_fail(self, url=None):
		if self.test.cache.cached_link is None and url:
			self.test.cache.cached_link = url

		if self.test.cache.cached_link is not None:
			with wait_for_page_load(self.driver):
				self.driver.get(self.test.cache.cached_link)
			return True

		self.user_driver.search_test(self.test.get_title())

		driver = self.driver
		for i in range(10):
			for link in driver.find_elements_by_partial_link_text(self.test.get_title()):
				if link.is_displayed():
					if link.text.strip() == self.test.get_title():
						with wait_for_page_load(driver):
							link.click()
						self.test.cache.cached_link = driver.current_url
						return True
			time.sleep(1)

		return False

	def goto(self, url=None):
		if not self.goto_or_fail(url):
			raise InteractionException("test '%s' was not found in ILIAS" % self.test.get_title())
		return True

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

	def skip_list_of_questions(self):
		if self.driver.find_elements_by_css_selector('#listofquestions'):
			pass  # 'table tbody tr td a'


	def start(self, username, context, questions, exam_configuration, allow_resume=False):
		self.report("starting test.")
		self.allow_resume = allow_resume
		if not self._try_start_or_resume():
			raise InteractionException("user does not have rights to start this test. aborting.")
		self.skip_list_of_questions()
		return ExamDriver(self.driver, self.ilias_url, username, self.report, context, questions, exam_configuration)


class UserDriver:
	def __init__(self, driver, ilias_url, ilias_version, report):
		self.driver = driver

		self.ilias_url = ilias_url
		parsed_url = urlparse(self.ilias_url)
		self.ilias_base_url = parsed_url.scheme + "://" + parsed_url.netloc + parsed_url.path
		self.client_id = parse_qs(parsed_url.query)['client_id'][0]

		self.ilias_version = ilias_version
		self.report = report

	def login(self, username, password):
		return Login(self, username, password)

	def import_test(self, path):
		driver = self.driver

		self.report('importing test from file "%s".' % os.path.basename(path))

		# goto root ("Magazin")
		root_url = self.ilias_base_url + ("/goto.php?target=root_1&client_id=%s" % self.client_id)
		with wait_for_page_load(driver):
			driver.get(root_url)

		# add new item: Test.
		wait_for_css(driver, '.ilNewObjectSelector button')
		driver.find_element_by_css_selector(".ilNewObjectSelector button").click()
		wait_for_css(driver, '.ilNewObjectSelector #tst')
		driver.find_element_by_css_selector(".ilNewObjectSelector #tst").click()
		wait_for_css(driver, 'input[name="cmd[importFile]"]')

		self.report("looking for import button.")

		def roll(l):  # we know it's the second accordion, usually.
			return l[1:] + l[:1]

		# click on import to get dedicated import mask.
		import_button = None
		for _ in range(5):
			for accordion in roll(list(driver.find_elements_by_css_selector(".il_VAccordionInnerContainer"))):
				accordion.find_element_by_css_selector(".il_VAccordionToggleDef").click()
				try:
					wait_for_css_visible(driver, 'input[name="cmd[importFile]"]', timeout=1)
					import_button = accordion.find_element_by_name("cmd[importFile]")
					break
				except (NoSuchElementException, TimeoutException):
					pass
			if import_button:
				break

		if not import_button:
			raise InteractionException("test import button not found.")
		with wait_for_page_load(driver):
			#driver.execute_script("document.getElementById('xmldoc').value = arguments[0]", self.test.get_path())
			driver.find_element_by_id("xmldoc").send_keys(path)
			import_button.click()

		self.report("importing.")

		with wait_for_page_load(driver):
			driver.find_element_by_name("cmd[importVerifiedFile]").click()

		self.report("done importing test.")

	def delete_test(self, test_name):
		self.search_test(test_name)

		self.report('deleting test "%s".' % test_name)

		rows = list(self.driver.find_elements_by_css_selector(".ilObjListRow"))
		if len(rows) != 1:
			raise InteractionException("expected exactly 1 test to delete, got %d named '%s'" % (len(rows), test_name))

		row = rows[0]
		link_text = row.find_element_by_css_selector("a.il_ContainerItemTitle").text.strip()
		if link_text != test_name:
			raise InteractionException("link text mismatch")

		button = row.find_element_by_css_selector(".dropdown-toggle")
		button.click()

		#wait_for_css_visible(self.driver, "ul.dropdown-menu")  # let's hope there's only one

		found_link = False
		for _ in range(5):
			menu = row.find_element_by_css_selector("ul.dropdown-menu")
			for link in menu.find_elements_by_css_selector("a"):
				if "cmd=delete" in link.get_attribute("href"):
					with wait_for_page_load(self.driver):
						link.click()
						found_link = True
					break
			if found_link:
				break
			time.sleep(1)

		delete_button = self.driver.find_element_by_css_selector('input[name="cmd[performDelete]"]')
		with wait_for_page_load(self.driver):
			delete_button.click()

	def search_test(self, test_name):
		driver = self.driver

		self.report("preparing to search.")
		for i in range(5):
			with wait_for_page_load(driver):
				driver.get(self.ilias_url)

			driver.find_element_by_css_selector(".glyphicon-search").click()
			with wait_for_page_load(driver):
				driver.find_element_by_css_selector('#mm_search_form input[type="submit"]').click()

			#self.browser.visit(self.ilias_url + "/ilias.php?baseClass=ilSearchController")
			self.report('searching for test "%s".' % test_name)

			search_input = None

			try:
				wait_for_css(driver, ".ilTabsContentOuter div form input[name='term']")

				search_input = driver.find_element_by_css_selector(
					".ilTabsContentOuter div form input[name='term']")
			except TimeoutException:
				# sporadically, a "there is no data set with id" comes along; just retry
				pass

			if search_input:
				set_element_value(driver, search_input, test_name)
				break

		# note: one reason this might fail is that the test we search for is still "offline."

		self.report("performing search.")
		with wait_for_page_load(driver):
			driver.find_element_by_css_selector("input[name='cmd[performSearch]']").click()

	def create_test_driver(self, test):
		return TestDriver(self, test)
