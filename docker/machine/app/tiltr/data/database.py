#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from typing import List, Dict, Tuple

import os
import sqlite3
import json
import base64
import datetime
import zipfile
from collections import defaultdict
import pytz

from tiltr.question.coverage import Coverage


class DB:
	def __init__(self):
		pass

	def __enter__(self):
		db_path = os.path.join("/tiltr/tmp", "results.db")
		self.db = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)

		c = self.db.cursor()
		c.execute("CREATE TABLE IF NOT EXISTS results (created TIMESTAMP, batch TEXT PRIMARY KEY, success TEXT, files BLOB, nusers INTEGER, elapsed INTEGER)")

		c.execute("CREATE TABLE IF NOT EXISTS performance (id INTEGER PRIMARY KEY AUTOINCREMENT, dt INTEGER)")
		c.execute("CREATE TABLE IF NOT EXISTS coverage_cases (id INTEGER PRIMARY KEY AUTOINCREMENT, question VARCHAR(255), name TEXT, UNIQUE(name))")
		c.execute("CREATE TABLE IF NOT EXISTS coverage_occurrences (id INTEGER PRIMARY KEY AUTOINCREMENT, question VARCHAR(255), name TEXT, UNIQUE(name))")
		c.execute("CREATE TABLE IF NOT EXISTS longterm (created TIMESTAMP, success INTEGER, detail TEXT, nusers INTEGER)")

		c.execute("CREATE INDEX IF NOT EXISTS index_results_created ON results(created)")
		c.execute("CREATE INDEX IF NOT EXISTS index_longterm_created ON longterm(created)")

		self.db.commit()
		c.close()

		return self

	def __exit__(self, *args):
		self.db.close()

	@staticmethod
	def get_size() -> int:
		path = os.path.join("/tiltr/tmp", "results.db")
		if os.path.exists(path):
			return os.path.getsize(path)
		else:
			return 0

	def put(self, batch_id: str, success: str, files: str, num_users: int, elapsed_time: int):
		c = self.db.cursor()
		now = datetime.datetime.now()
		c.execute("INSERT INTO results (created, batch, success, files, nusers, elapsed) VALUES (?, ?, ?, ?, ?, ?)",
			(now, batch_id.encode(), success.encode(), files.encode("utf-8"), num_users, elapsed_time))

		success_code = dict(OK=1, FAIL=0).get(success.split("/")[0], 0)
		c.execute("INSERT INTO longterm (created, success, detail, nusers) VALUES (?, ?, ?, ?)",
			(now, success_code, success, num_users));

		self.db.commit()
		c.close()

	def put_performance_data(self, dts: List[int]):
		c = self.db.cursor()
		c.executemany("insert into performance(dt) values (?)", [(1000 * dt,) for dt in dts])
		self.db.commit()
		c.close()

	def put_coverage_data(self, coverage: Coverage):
		c = self.db.cursor()
		c.executemany("INSERT OR IGNORE INTO coverage_cases(question, name) VALUES (?, ?)",
			[(x[0].encode("utf-8"), json.dumps(x).encode("utf-8")) for x in coverage.get_cases()])
		c.executemany("INSERT OR IGNORE INTO coverage_occurrences(question, name) VALUES (?, ?)",
			[(x[0].encode("utf-8"), json.dumps(x).encode("utf-8")) for x in coverage.get_occurrences()])
		self.db.commit()
		c.close()

	def get_coverage(self) -> Dict:
		c = self.db.cursor()

		c.execute("SELECT COUNT(*) FROM coverage_cases")
		num_cases = int(c.fetchone()[0])

		c.execute("SELECT COUNT(*) FROM coverage_occurrences o INNER JOIN coverage_cases c ON c.name = o.name")
		num_occurrences = int(c.fetchone()[0])

		questions = defaultdict(dict)
		c.execute("SELECT question, COUNT(*) FROM coverage_cases GROUP BY question")
		while True:
			row = c.fetchone()
			if row is None:
				break
			questions[row[0].decode("utf-8")]["cases"] = row[1]

		c.execute("SELECT o.question, COUNT(*) FROM coverage_occurrences o "
			"INNER JOIN coverage_cases c ON c.name = o.name GROUP BY o.question")
		while True:
			row = c.fetchone()
			if row is None:
				break
			questions[row[0].decode("utf-8")]["observed"] = row[1]

		c.close()

		for name, q in questions.items():
			q["name"] = name

		return dict(
			cases=num_cases,
			observed=num_occurrences,
			questions=list(questions.values()))

	def get_counts(self) -> Dict:
		c = self.db.cursor()

		c.execute("SELECT success, COUNT(success), SUM(nusers) FROM results GROUP BY success")
		counts = dict()
		while True:
			row = c.fetchone()
			if row is None:
				break
			counts[row[0].decode("utf-8")] = dict(
				runs=row[1],
				users=row[2])

		c.close()
		return counts

	def get_details(self) -> List[Dict]:
		c = self.db.cursor()
		c.execute("SELECT created, elapsed, batch, success FROM results ORDER BY created")
		rows = c.fetchall()
		c.close()

		entries = []
		tz = pytz.timezone('Europe/Berlin')
		for timestamp, elapsed, batch, success in rows:
			timestamp = timestamp.replace(tzinfo=pytz.utc).astimezone(tz)
			entries.append(dict(
				time=timestamp.strftime('%d.%m.%Y %H:%M:%S'),
				elapsed=int(elapsed) or 0,
				batch=batch.decode("utf-8"),
				success=success.decode("utf-8")
			))

		return entries

	def get_performance_data(self) -> List[float]:
		c = self.db.cursor()
		c.execute("SELECT dt FROM performance")
		rows = c.fetchall()
		c.close()

		return [row[0] / 1000.0 for row in rows]

	def get_longterm_data(self) -> List[Tuple]:
		c = self.db.cursor()
		c.execute("SELECT created, success, nusers FROM longterm ORDER BY created")
		rows = c.fetchall()
		c.close()

		tz = pytz.timezone('Europe/Berlin')
		values = []

		for timestamp, success, n_users in rows:
			timestamp = timestamp.replace(tzinfo=pytz.utc).astimezone(tz)
			values.append((timestamp.strftime('%d.%m.%Y %H:%M:%S'), success, n_users))

		return values

	def get_files(self) -> Dict[str, str]:
		c = self.db.cursor()
		c.execute("SELECT batch, files FROM results")
		files = dict()
		while True:
			row = c.fetchone()
			if row is None:
				break
			files[row[0].decode("utf-8")] = row[1].decode("utf-8")
		c.close()
		return files

	def clear(self):
		c = self.db.cursor()
		c.execute("DELETE FROM results")
		c.execute("DELETE FROM performance")
		c.execute("DELETE FROM coverage_cases")
		c.execute("DELETE FROM coverage_occurrences")
		self.db.commit()
		c.close()		

	def get_zipfile(self, batch_id: str, file: str):
		c = self.db.cursor()
		c.execute("SELECT files FROM results WHERE batch=?", (batch_id.encode("utf-8"),))
		files_json = c.fetchone()[0]

		with zipfile.ZipFile(file, "w") as z:
			files = json.loads(files_json.decode("utf-8"))
			for k, v in files.items():
				z.writestr('/' + k, base64.b64decode(v))
