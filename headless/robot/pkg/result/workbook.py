#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from . import Result, Origin
from ..exceptions import *
from decimal import *


class XlsResultRow():
	# represents one row in worksheet 0 "Testergebnisse"

	def __init__(self, sheet, row):
		self.sheet = sheet
		self.row = row

	def get(self, column):
		return self.sheet.cell(row=self.row, column=column).value

	def get_username(self):
		return self.get(2)

	def get_total_score(self):
		return Decimal(self.get(3))

	def get_question_scores(self):
		scores = dict()
		column = 20  # magic column "T" where user scores start
		while True:
			title = self.sheet.cell(row=1, column=column).value
			if title is None:
				break
			score = self.get(column)
			if score is None:
				scores[title] = "illegal_empty_score"
			else:
				scores[title] = Decimal(score)
			column += 1
		return scores


def get_workbook_user_answers(sheet, report=None):
	answers = []

	row = 3
	while True:
		question_title = sheet.cell(row=row, column=2).value
		if question_title is None:
			break
		assert isinstance(question_title, str)
		row += 1
		if report:
			report('detected question title "%s".' % question_title)

		dimensions = []
		while sheet.cell(row=row, column=1).value is not None:
			key = sheet.cell(row=row, column=1).value
			assert key is not None
			value = sheet.cell(row=row, column=2).value
			if value is None:
				value = ""  # an empty gap in cloze question, for example
			dimensions.append((key, value))
			row += 1

		answers.append((question_title.strip(), dimensions))
		row += 1

	return answers


def check_workbook_consistency(wb, report, workarounds):
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

	answers = get_workbook_user_answers(wb.worksheets[1], report)

	if not workarounds.random_xls_participant_sheet_orders:
		for user_index in range(2, num_users + 1):
			user_sheet = wb.worksheets[user_index]
			other_answers = get_workbook_user_answers(user_sheet)
			assert len(answers) == len(other_answers)
			for i in range(len(answers)):
				question_title, dimensions = answers[i]
				other_question_title, other_dimensions = other_answers[i]
				assert question_title == other_question_title
				assert len(dimensions) == len(other_dimensions)
				for j in range(len(dimensions)):
					assert dimensions[j][0] == other_dimensions[j][0]


def workbook_to_result(wb, username, report):
	if report:
		report("gathering data from XLS.")

	# extract user result row from general tab (i.e. scores for each question
	# for one user). note that ILIAS sometimes exports empty rows but still
	# yields all users - we ignore empty rows below.

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

	for question_title, dimensions in get_workbook_user_answers(user_sheet):
		for dimension_title, dimension_value in dimensions:
			result.add(("question", question_title, "answer", dimension_title), dimension_value)

	for title, score in result_row.get_question_scores().items():
		result.add(("question", title, "score"), score)

	result.add(("exam", "score", "total"), result_row.get_total_score())

	return result
