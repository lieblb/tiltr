#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from .answer import Answer, Validness

import io

from selenium.webdriver.common.action_chains import ActionChains
from PIL import Image
from decimal import *


class PaintAnswer(Answer):
	def __init__(self, driver, question, protocol):
		assert question.__class__.__name__ == "PaintQuestion"
		self.driver = driver
		self.question = question
		self.current_answer = None
		self.current_score = Decimal(0)
		self.protocol = protocol

	def randomize(self, context):
		self._set_answer(*self.question.get_random_answer(context))
		return Validness.VALID

	def _set_answer(self, answer, score):
		clear = self.driver.find_element_by_name('clear')
		clear.click()

		# note that the following alert is not a standard feature, but currently
		# only exists in https://github.com/lieblb/assPaintQuestion/tree/ur-tweaks
		self.driver.switch_to.alert.accept()

		canvas = self.driver.find_element_by_css_selector('#paintCanvas')
		d = 5

		x = d
		y = d

		chain = ActionChains(self.driver)
		chain.move_to_element_with_offset(canvas, x, y)
		chain.click_and_hold()

		i = 0
		while (answer >> i) > 0:
			if ((answer >> i) & 1) > 0:
				dx, dy = (d, 0)
			else:
				dx, dy = (0, d)

			chain.move_by_offset(dx, dy)

			i += 1

		chain.release()
		chain.perform()

		self.current_answer = answer
		self.current_score = Decimal(0)

	def verify(self, context, after_crash=False):
		element = self.driver.find_element_by_id('paintCanvas')
		location = element.location
		size = element.size
		png = self.driver.get_screenshot_as_png()

		im = Image.open(io.BytesIO(png))

		left = location['x']
		top = location['y']
		right = location['x'] + size['width']
		bottom = location['y'] + size['height']

		im = im.crop((left, top, right, bottom))
		im = im.convert('L')

		pixels = im.getdata(0)
		w, h = im.size

		d = 5

		def count(x, y, dx, dy):
			n = 0
			while pixels[x + y * w] == 0:
				x += dx
				y += dy
				n += 1
				if n == d:
					return True
			return False

		x = d
		y = d
		actual_answer = 0
		n = 0

		while True:
			if count(x, y, 1, 0):
				x += d
				actual_answer |= 1 << n
			elif count(x, y, 0, 1):
				y += d
			else:
				break
			n += 1

		self.protocol.verify('canvas', bin(self.current_answer), bin(actual_answer), after_crash=after_crash)

	def to_dict(self, context, language):
		return dict(
			title=self.question.title,
			answers=dict(),
			protocol=self.protocol.to_dict())
