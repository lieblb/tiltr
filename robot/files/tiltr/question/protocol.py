import time

from ..data.exceptions import *


def _normalize_answer(value):
	if isinstance(value, str):
		value = value.replace("\n", "\\n")
	return value


class AnswerProtocol:
	def __init__(self, title, get_debug_info):
		self._title = title
		self._get_debug_info = get_debug_info
		self._entries = []
		self._files = dict()

	def choose(self, key, value):
		self._entries.append((time.time(), "answered '%s' with '%s'" % (key, _normalize_answer(value))))

	def verify(self, key, expected, actual, after_crash=False):
		now = time.time()

		if expected == actual:
			self._entries.append(
				(now, "OK verified that '%s' is still '%s'" % (key, _normalize_answer(expected))))
		else:
			err = "FAIL answer on '%s' was stored incorrectly: answer was '%s', but ILIAS stored '%s'" % (
				key, _normalize_answer(expected), _normalize_answer(actual))
			self._entries.append((now, err))

			infos = self._get_debug_info(self._title)
			if infos:
				for k, v in infos.items():
					full_name = self._add_file(k, v)
					self._entries.append((now, '## more debug info in file %s.' % full_name))

			if after_crash:
				raise AutoSaveException("answer mismatch after crash: " + err)
			else:
				raise IntegrityException("answer mismatch during in-test verification: " + err)

	def add(self, text):
		self._entries.append((time.time(), text))

	def _add_file(self, name, text):
		full_name = '%s_%d_%s' % (self._title, 1 + len(self._files), name)
		self._files[full_name] = text
		return full_name

	@property
	def lines(self):
		return tuple(self._entries)

	@property
	def files(self):
		return self._files
