#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from decimal import *

from .result import Result, Origin
from .exceptions import *


class XlsResultRow:
	# represents one row in worksheet 0 "Testergebnisse"

	def __init__(self, sheet, row):
		self.sheet = sheet
		self.row = row

	def get(self, column):
		return self.sheet.cell(row=self.row, column=column).value

	def get_username(self):
		return self.get(2)

	def get_reached_score(self):
		return Decimal(self.get(3))

	def get_maximum_score(self):
		return Decimal(self.get(4))

	def get_short_mark(self):
		return str(self.get(5)).strip()

	def get_question_scores(self, workarounds):
		scores = dict()
		column = 20  # magic column "T" where user scores start
		while True:
			title = self.sheet.cell(row=1, column=column).value
			if title is None:
				break
			score = self.get(column)
			if score is None:
				if workarounds.allow_empty_scores:
					scores[title] = Decimal(0)
				else:
					scores[title] = "illegal_empty_score"
			else:
				scores[title] = Decimal(score)
			column += 1
		return scores


def _is_question_header_ilias53(sheet, row):
	return sheet.cell(row=row, column=1).fill.patternType == "solid"


def get_workbook_user_answers(sheet, questions, ilias_version, report=None):
	sections = list()

	if ilias_version < (5, 4):
		for row in range(1, sheet.max_row + 1):
			if _is_question_header_ilias53(sheet, row):
				title = sheet.cell(row=row, column=2).value
				assert isinstance(title, str)
				question = questions[title.strip()]
				sections.append((question, row))
	else:
		for row in range(3, sheet.max_row + 1):
			value = sheet.cell(row=row - 1, column=1).value
			if value is None or len(value.strip()) == 0:
				title = sheet.cell(row=row, column=2).value
				question = questions[title.strip()]
				sections.append((question, row))

	sections.append((None, sheet.max_row + 1))

	answers = list()
	for (question, row0), (_, row1) in zip(sections[:-1], sections[1:]):
		if report:
			report('parsing rows %d-%d in sheet "%s" as answers to question "%s"' % (
				row0, row1, sheet.title, question.title))

		dimensions = list()

		if question.has_xls_score():
			for row in range(row0 + 1, row1):
				entry = question.parse_xls_row(sheet, row)
				if entry:
					dimensions.append(entry)

		answers.append((question.title, tuple(dimensions)))

	return answers


def check_workbook_consistency(wb, questions, workarounds, ilias_version, report):
	if report:
		report("checking workbook participant sheet existence.")

	main_sheet = wb.worksheets[0]

	# check existence of user tabs.
	user_index = 1
	num_users = 0
	while main_sheet.cell(row=user_index + 1, column=1).value is not None:
		# determine full user name, e.g. user, testuser1
		full_username = main_sheet.cell(row=user_index + 1, column=1).value

		if wb.sheetnames[user_index] != full_username:
			raise IntegrityException('user worksheet name wrong: "%s" != "%s"' % (
				wb.sheetnames[user_index], full_username))

		user_sheet = wb.worksheets[user_index]
		num_users += 1
		user_index += 1

	# check order of questions and answers in user tabs.
	if report:
		report("checking workbook participant sheet consistency.")

	if not workarounds.random_xls_participant_sheet_orders:
		answers = get_workbook_user_answers(wb.worksheets[1], questions, ilias_version, report)
		for user_index in range(2, num_users + 1):
			user_sheet = wb.worksheets[user_index]
			other_answers = get_workbook_user_answers(user_sheet, questions, ilias_version, report)
			assert len(answers) == len(other_answers)
			for i in range(len(answers)):
				question_title, dimensions = answers[i]
				other_question_title, other_dimensions = other_answers[i]
				assert question_title == other_question_title
				assert len(dimensions) == len(other_dimensions)
				for j in range(len(dimensions)):
					assert dimensions[j][0] == other_dimensions[j][0]


def workbook_to_result(wb, username, questions, workarounds, ilias_version, report):
	if report:
		report("gathering data from XLS.")

	# extract user result row from general tab (i.e. scores for each question
	# for one user). note that ILIAS sometimes exports empty rows but still
	# yields all users - we ignore empty rows below (which usually seem to
	# indicate that a wrong additional pass has been created, we will detect
	# this in the detailed result check if so).

	main_sheet = wb.worksheets[0]
	result_row = None
	row_index = 2
	while True:
		result_row = XlsResultRow(main_sheet, row_index)
		row_username = result_row.get_username()
		if row_username == username:
			break
		row_index += 1
		if row_index > 1000:
			raise IntegrityException("user %s not found in XLS" % username)
	assert result_row

	# find user tab and extract individual answer information (i.e. specific
	# answers given to each question).

	user_sheet = wb.worksheets[wb.sheetnames.index("user, %s" % username)]

	result = Result(origin=Origin.exported)

	for question_title, dimensions in get_workbook_user_answers(user_sheet, questions, ilias_version):
		for dimension_title, dimension_value in dimensions:
			result.add(Result.key("question", question_title, "answer", dimension_title), dimension_value)

	for title, score in result_row.get_question_scores(workarounds).items():
		result.add(("xls", "question", Result.normalize_question_title(title), "score"), score)

	result.add(("xls", "score_reached"), result_row.get_reached_score())
	result.add(("xls", "score_maximum"), result_row.get_maximum_score())
	result.add(("xls", "short_mark"), result_row.get_short_mark())

	return result
