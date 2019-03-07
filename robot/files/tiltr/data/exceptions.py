#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#


from enum import Enum, unique

# ErrorDomain:

# Indicates a class of error. Used for serialization. Anything below "integrity" might happen
# sporadically without indicating a fundamental problem. NOTE: higher numeric values need to
# correspond to more severe errors, in order for most_severe() to work properly.


@unique
class ErrorDomain(Enum):
	none = 0
	not_implemented = 1
	interaction = 2
	unexpected = 3
	auto_save = 4
	invalid_save = 5
	integrity = 6


def most_severe(domains):
	domains = list(domains)
	if domains:
		return ErrorDomain(max(x.value for x in domains))
	else:
		return ErrorDomain.none


# TiltrException:

# Generic base class for all TiltR exceptions.


class TiltrException(Exception):
	def __init__(self, domain, *args):
		super().__init__(*args)
		self._domain = domain

	def get_error_domain(self):
		return self._domain

	def get_error_domain_name(self):
		return self._domain.name


# NotImplementedException:

# Indicates that a feature is requested that has not been implemented in TiltR. This does not
# indicate an error in ILIAS.

class NotImplementedException(TiltrException):
	def __init__(self, *args):
		super().__init__(ErrorDomain.not_implemented, *args)


# InteractionException:

# States that an interaction with the web interface or the web driver has failed, e.g. when a
# button wasn't found where it was expected. This doesn't necessarily indicate that ILIAS did
# something wrong, merely that the automation wasn't able to run its tests properly. Can appear
# randomly with very low probability as artefact of the automated testing process.


class InteractionException(TiltrException):
	def __init__(self, *args):
		super().__init__(ErrorDomain.interaction, *args)


# UnexpectedErrorException:

# Indicates that an error occured in ILIAS, even though it shouldn't have. While the data
# consistency is ok, the current operation was aborted.


class UnexpectedErrorException(TiltrException):
	def __init__(self, *args):
		super().__init__(ErrorDomain.unexpected, *args)


# AutoSaveException:

# Indicates that the auto save didn't work properly or as expected. While this might be viewed
# as a kind of integrity error, this might happen sporadically under very heavy server loads
# without indicating any fundamental problems in ILIAS.

class AutoSaveException(TiltrException):
	def __init__(self, *args):
		super().__init__(ErrorDomain.auto_save, *args)


# InvalidSaveException:

# A save operation (seems to) have succeeded that should not have succeeded due to invalid form
# values. In cases where a questions contains different input fields, this can lead to loss of
# data (see https://mantis.ilias.de/view.php?id=23432).

class InvalidSaveException(TiltrException):
	def __init__(self, *args):
		super().__init__(ErrorDomain.invalid_save, *args)


# IntegrityException:

# Indicates that an error has been encountered in ILIAS, which points to some corruption or loss
# of data.

class IntegrityException(TiltrException):
	def __init__(self, *args):
		super().__init__(ErrorDomain.integrity, *args)
