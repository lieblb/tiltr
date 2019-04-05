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
from selenium.common.exceptions import NoAlertPresentException
from PIL import Image
from tiltr.data.exceptions import InteractionException


class PaintStrategy:
	pass


class PaintPathsStrategy(PaintStrategy):
	def set(self, driver, canvas, answer):
		driver.find_element_by_css_selector('div[title="Pencil"]').click()

		d = 5

		x = d
		y = d

		split_chain = False

		i = 0
		while (answer >> i) > 0:
			if ((answer >> i) & 1) > 0:
				dx, dy = (d, 0)
			else:
				dx, dy = (0, d)

			if chain is None:
				chain = ActionChains(driver)

			chain.move_to_element_with_offset(canvas, x, y)
			chain.click_and_hold()
			chain.move_by_offset(dx, dy)
			chain.release()

			if split_chain:
				chain.perform()
				chain = None

			x += dx
			y += dy

			i += 1

		if chain:
			chain.perform()

	def verify(self, pixels, w, h):
		d = 5
		answer = 0

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
		n = 0

		while True:
			if count(x, y, 1, 0):
				x += d
				answer |= 1 << n
			elif count(x, y, 0, 1):
				y += d
			else:
				break
			n += 1

		return answer


class PaintBoxesStrategy(PaintStrategy):
	step = 8
	inset = 3
	ncols = 4

	def set(self, driver, canvas, answer):
		driver.find_element_by_css_selector('div[title="Rectangle"]').click()

		chain = None
		split_chain = False

		step = self.step
		inset = self.inset
		ncols = self.ncols

		if chain is None:
			chain = ActionChains(driver)
			chain.move_to_element_with_offset(canvas, 0, 0)
			chain.click_and_hold()
			chain.move_by_offset(0, ncols * step)
			chain.release()

		for i in range(ncols * ncols):
			if ((answer >> i) & 1) > 0:
				if chain is None:
					chain = ActionChains(driver)

				x = (i % ncols) * step + inset
				y = (i // ncols) * step + inset

				chain.move_to_element_with_offset(canvas, x, y)
				chain.click_and_hold()
				chain.move_by_offset(step - 2 * inset, step - 2 * inset)
				chain.release()

				if split_chain:
					chain.perform()
					chain = None

		if chain:
			chain.perform()

	def parse(self, pixels, w, h):
		answer = 0

		step = self.step
		ncols = self.ncols

		l = 0
		while pixels[l] != 0:
			l += 1
		while pixels[l] == 0:
			l += 1

		for i in range(ncols * ncols):
			x0 = (i % ncols) * step
			y0 = (i // ncols) * step

			n = 0
			for x in range(x0, x0 + step):
				for y in range(y0, y0 + step):
					if pixels[l + x + y * w] == 0:
						n += 1
			if n > 0:
				answer |= 1 << i

		return answer


class PaintAnswer(Answer):
	def __init__(self, driver, question, protocol):
		super().__init__(driver, question, protocol)
		assert question.__class__.__name__ == "PaintQuestion"
		self.current_answer = None
		self._paint_strategy = PaintBoxesStrategy()

	def randomize(self, context):
		self._set_answer(*self.question.get_random_answer(context))
		return Validness()

	def _get_canvas(self):
		return list(self.driver.find_elements_by_css_selector('canvas'))[-1]
		# canvas = self.driver.find_element_by_css_selector('#paintCanvas')

	def _set_answer(self, answer, score):
		# driver.capabilities['browserName'] == 'chrome'

		n_retries = 5
		is_answer_ok = False

		for i in range(n_retries):
			clear = self.driver.find_element_by_css_selector('.lc-clear')
			# clear = self.driver.find_element_by_name('clear')
			clear.click()

			try:
				# note that the following alert is not a standard feature, but currently
				# only exists in https://github.com/lieblb/assPaintQuestion/tree/ur-tweaks
				self.driver.switch_to.alert.accept()
			except NoAlertPresentException:
				pass  # ok, custom / new version

			canvas = self._get_canvas()

			self._paint_strategy.set(self.driver, canvas, answer)

			if self._parse_answer() == answer:
				is_answer_ok = True
				break

			time.sleep(1)  # retry

		# if we fail to draw the correct answer in the firs place,
		# it's not an integrity but an interaction error.

		if not is_answer_ok:
			raise InteractionException(
				"failed to paint requested answer: %d != %d" % (
			   self._parse_answer(), answer))

		self.current_answer = answer
		self.current_score = score

	def _parse_answer(self):
		canvas = self._get_canvas()
		location = canvas.location
		size = canvas.size
		png = self.driver.get_screenshot_as_png()

		im = Image.open(io.BytesIO(png))

		left = location['x']
		top = location['y']
		right = location['x'] + size['width']
		bottom = location['y'] + size['height']

		im = im.crop((left, top, right, bottom))
		im = im.convert('L')

		# im.save('debug.png', 'PNG')
		# self.protocol._add_file("debug.png", data)

		pixels = im.getdata(0)
		w, h = im.size
		return self._paint_strategy.parse(pixels, w, h)

	def verify(self, context, after_crash=False):
		actual_answer = self._parse_answer()

		self.protocol.verify(
			'canvas', bin(self.current_answer), bin(actual_answer), after_crash=after_crash)

	def _get_answer_dimensions(self, context, language):
		return dict()
