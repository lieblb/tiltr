#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import io
import re

from pdfminer3.layout import LAParams, LTTextBoxHorizontal
from pdfminer3.converter import PDFPageAggregator
from pdfminer3.pdfparser import PDFParser
from pdfminer3.pdfdocument import PDFDocument
from pdfminer3.pdfpage import PDFPage
from pdfminer3.pdfinterp import PDFResourceManager
from pdfminer3.pdfinterp import PDFPageInterpreter


def _extract_pdf_scores(stream):
	# these laparams seem to work ok with the ILIAS default PDF
	# formatting as well as with UR custom styling.

	# see pdf/tests/default_style.pdf and pdf/tests.ur_style.pdf

	laparams = LAParams(
		line_overlap=0,
		char_margin=20,
		word_margin=0.1,
		boxes_flow=0,
		detect_vertical=False)

	rsrcmgr = PDFResourceManager()

	device = PDFPageAggregator(rsrcmgr, laparams=laparams)
	interpreter = PDFPageInterpreter(rsrcmgr, device)

	parser = PDFParser(stream)
	document = PDFDocument(parser)

	page = next(PDFPage.create_pages(document))

	interpreter.process_page(page)
	layout = device.get_result()

	boxes = []
	table_head_y = None	 # y position of result table header

	for element in layout:
		if isinstance(element, LTTextBoxHorizontal):
			boxes.append(element)
			if 'Reihenfolge' in element.get_text().strip():
				table_head_y = element.y0

	for box in boxes:
		print(box)

	tboxes = list(filter(lambda box: box.y0 == table_head_y, boxes))

	# if LAParams is set correctly, head should extract the whole
	# results table's text now.
	table = tboxes[0].get_text().replace('\t', '')

	table = table[table.find('Reihenfolge'):]

	# note: question titles might lack spaces; this is no problem
	# since we compare question names and scores only through
	# Result.normalize_question_title() later.

	scores = dict()
	cols = []
	for line in table.split("\n")[1:]:
		cols += re.split(r'\s+', line)
		if len(cols) >= 6:
			scores[cols[2]] = cols[4]
			cols = cols[6:]

	return scores


class PDF:
	def __init__(self, bytes):
		self.bytes = bytes
		self.scores = _extract_pdf_scores(io.BytesIO(bytes))
