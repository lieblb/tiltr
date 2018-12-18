from enum import Enum


class CountSystem(Enum):
	partial = 0
	complete = 1


class MCScoring(Enum):
	do_not_save_empty = 0
	save_empty = 1


class ScoreCutting(Enum):
	per_question = 0
	per_test = 1


class PassScoring(Enum):
	last_pass = 0
	best_pass = 1


class ExamConfiguration:
	def __init__(self):
		self.count_system = None
		self.mc_scoring = None
		self.score_cutting = None
		self.pass_scoring = None

	def set_count_system(self, value):
		self.count_system = CountSystem(value)

	def set_mc_scoring(self, value):
		self.mc_scoring = MCScoring(value)

	def set_score_cutting(self, value):
		self.score_cutting = ScoreCutting(value)

	def set_pass_scoring(self, value):
		self.pass_scoring = PassScoring(value)
