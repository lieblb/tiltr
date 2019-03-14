import argparse


def parse_args():
	parser = argparse.ArgumentParser()

	parser.add_argument('--master', action='store_true')
	parser.add_argument('--machine', action='store_true')
	parser.add_argument('--debug', action='store_true')

	parser.add_argument('--ilias-url')
	parser.add_argument('--ilias-admin-user')
	parser.add_argument('--ilias-admin-password')

	parser.add_argument('--tiltr-port')
	parser.add_argument('--ext-ilias-port', nargs='?')

	return parser.parse_args()
