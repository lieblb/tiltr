from pdfminer.layout import LAParams, LTTextBoxHorizontal
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfinterp import PDFPageInterpreter


def _extract_lines(box):
	lines = box.get_text().split("\n")
	return list(filter(lambda s: len(s.strip()) > 0, lines))


def extract_pdf_scores(stream):
	laparams = LAParams()
	rsrcmgr = PDFResourceManager()

	device = PDFPageAggregator(rsrcmgr, laparams=laparams)
	interpreter = PDFPageInterpreter(rsrcmgr, device)

	parser = PDFParser(stream)
	document = PDFDocument(parser)

	page = next(PDFPage.create_pages(document))

	interpreter.process_page(page)
	layout = device.get_result()

	boxes = []
	pivot_y = None
	for element in layout:
		if isinstance(element, LTTextBoxHorizontal):
			boxes.append(element)
			if element.get_text().strip().startswith('Reihenfolge'):
				pivot_y = element.y0

	boxes = sorted(boxes, key=lambda box: -box.y0)
	boxes_y0 = list(map(lambda box: box.y0, boxes))

	tboxes = list(filter(lambda box: box.y0 == pivot_y, boxes))
	tboxes = sorted(tboxes, key=lambda box: box.x0)

	question_titles = _extract_lines(tboxes[2])
	question_titles = list(map(lambda s: s.replace("\t", " "), question_titles))

	scores = _extract_lines(tboxes[4])
	scores = scores[-len(question_titles):]

	result = dict()
	for question_title, score in zip(question_titles, scores):
		result[("pdf", "question", question_title, "score")] = score
	return result
