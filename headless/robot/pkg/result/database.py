#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

import os
import sqlite3
import json
import datetime
import zipfile


class DB:
	def __init__(self):
		pass

	def __enter__(self):
		db_path = os.path.join(os.path.dirname(__file__), "..", "..", "tmp", "results.db")
		self.db = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
		c = self.db.cursor()
		c.execute("CREATE TABLE IF NOT EXISTS results (created TIMESTAMP, batch TEXT PRIMARY KEY, success TEXT, xls BLOB, protocol TEXT, nusers INTEGER)")
		c.execute("CREATE TABLE IF NOT EXISTS performance (id INTEGER PRIMARY KEY AUTOINCREMENT, dt INTEGER)")
		self.db.commit()
		c.close()
		return self

	def __exit__(self, *args):
		self.db.close()

	def put(self, batch_id, success, xls, protocol, num_users):
		c = self.db.cursor()
		c.execute("INSERT INTO results (created, batch, success, xls, protocol, nusers) VALUES (?, ?, ?, ?, ?, ?)",
			(datetime.datetime.now(), batch_id, success, sqlite3.Binary(xls), protocol, num_users))
		self.db.commit()
		c.close()

	def put_performance_data(self, dts):
		c = self.db.cursor()
		c.executemany("insert into performance(dt) values (?)", [(1000 * dt,) for dt in dts])
		self.db.commit()
		c.close()

	def get_json(self):
		c = self.db.cursor()

		c.execute("SELECT success, COUNT(success), SUM(nusers) FROM results GROUP BY success")
		counts = dict()
		while True:
			row = c.fetchone()
			if row is None:
				break
			counts[row[0]] = dict(
				runs=row[1],
				users=row[2])

		c.execute("SELECT created, batch, success FROM results ORDER BY created")

		entries = []
		while True:
			r = c.fetchone()
			if r is None:
				break

			timestamp, batch, success = r

			entries.append(dict(
				time=timestamp.strftime('%d.%m.%Y %H:%M:%S'),
				batch=batch,
				success=success
			))
		c.close()
		return json.dumps(dict(counts=counts, entries=entries))

	def get_performance_data_json(self):
		c = self.db.cursor()
		c.execute("SELECT dt FROM performance")
		dts = []
		while True:
			row = c.fetchone()
			if row is None:
				break
			dts.append(row[0] / 1000.0)
		c.close()
		return json.dumps(dts)

	def clear(self):
		c = self.db.cursor()
		c.execute("DELETE FROM results")
		c.execute("DELETE FROM performance")
		self.db.commit()
		c.close()		

	def get_zipfile(self, batch_id, file):
		c = self.db.cursor()
		c.execute("SELECT xls, protocol FROM results WHERE batch=?", (batch_id,))
		xls, protocol = c.fetchone()

		with zipfile.ZipFile(file, "w") as z:
			z.writestr("/exported.xls", xls)
			z.writestr("/protocol.txt", protocol.encode("utf8"))
