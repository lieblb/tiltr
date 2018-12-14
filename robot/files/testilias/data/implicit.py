def looks_like_an_unsigned_number(x):
	return len(x) >= 1 and x.count('.') <= 1 and all(y.isdigit() or len(y) < 1 for y in x.split('.'))


def looks_like_a_number(x):
	if x and x[0] in ("-", "+"):
		return looks_like_an_unsigned_number(x[1:])
	else:
		return looks_like_an_unsigned_number(x)


def implicit_text_to_number(value):
	if len(value) >= 2 and value[0] == '+' and looks_like_a_number(value[1:]):
		# e.g. +9 -> 9
		value = value[1:]

	if looks_like_a_number(value):
		while value.endswith("0") and value.count('.') == 1 and not value.endswith(".0"):
			# e.g. 0.637010 -> 0.63701
			value = value[:-1]

		if len(value) >= 2 and value.endswith("."):
			# e.g. 13. -> 13
			value = value[:-1]
		elif len(value) >= 2 and value.startswith("."):
			# e.g. .17 -> 0.17
			value = "0" + value
		elif value.endswith(".0"):
			# e.g. 5.0 -> 5
			value = value[:-2]

	return value


def implicit_text_to_number_xls(value):
	# there are also several implicit conversions taking place when taking the number
	# from ILIAS into the XLS, but they are different from the ones inside ILIAS itself,
	# i.e. from implicit_text_to_number.

	# also catch more esoteric conversions like 3E6 -> 3000000
	try:
		value = str(float(value))
	except ValueError:
		pass

	if isinstance(value, str) and looks_like_a_number(value):
		while value.endswith("0") and value.count('.') == 1 and not value.endswith(".0"):
			# e.g. 0.637010 -> 0.63701
			value = value[:-1]

		if len(value) >= 2 and value[0] == '.' and value[-1] != '0':
			# e.g. .94853 -> .948530
			value += "0"

		if value == "0.0" or value == "-0.0" or value == "-0":
			# e.g. "0.0" -> "0".  note that other conversions, e.g. 597.0 -> 597, don't
			# take place!
			value = "0"

	return value
