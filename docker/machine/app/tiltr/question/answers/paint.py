#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from .answer import Answer, Validness

import io
import time

from selenium.webdriver.common.action_chains import ActionChains
from PIL import Image
from tiltr.data.exceptions import InteractionException


class PaintAnswer(Answer):
	def __init__(self, driver, question, protocol):
		super().__init__(driver, question, protocol)
		assert question.__class__.__name__ == "PaintQuestion"
		self.current_answer = None

	def randomize(self, context):
		self._set_answer(*self.question.get_random_answer(context))
		return Validness()

	def _set_answer(self, answer, score):
		# driver.capabilities['browserName'] == 'chrome'

		n_retries = 5
		is_answer_ok = False

		for i in range(n_retries):
			clear = self.driver.find_element_by_name('clear')
			clear.click()

			# note that the following alert is not a standard feature, but currently
			# only exists in https://github.com/lieblb/assPaintQuestion/tree/ur-tweaks
			self.driver.switch_to.alert.accept()

			canvas = self.driver.find_element_by_css_selector('#paintCanvas')
			d = 5

			x = d
			y = d

			chain = None
			split_chain = False

			i = 0
			while (answer >> i) > 0:
				if ((answer >> i) & 1) > 0:
					dx, dy = (d, 0)
				else:
					dx, dy = (0, d)

				if chain is None:
					chain = ActionChains(self.driver)
					chain.move_to_element_with_offset(canvas, x, y)
					chain.click_and_hold()

				chain.move_by_offset(dx, dy)

				if split_chain:
					chain.release()
					chain.perform()
					chain = None

					x += dx
					y += dy

				i += 1

			if chain:
				chain.release()
				chain.perform()

			if self._parse_answer() == answer:
				is_answer_ok = True
				break

			time.sleep(1)  # retry

		# if we fail to draw the correct answer in the firs place,
		# it's not an integrity but an interaction error.

		if not is_answer_ok:
			raise InteractionException("failed to paint requested answer")

		self.current_answer = answer
		self.current_score = score

	def _parse_answer(self):
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

		return actual_answer

	def verify(self, context, after_crash=False):
		actual_answer = self._parse_answer()

		self.protocol.verify(
			'canvas', bin(self.current_answer), bin(actual_answer), after_crash=after_crash)

	def _get_answer_dimensions(self, context, language):
		return dict()
