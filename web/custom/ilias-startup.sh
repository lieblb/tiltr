#!/bin/bash
set -e

mkdir -p /var/ilias
mkdir -p /var/ilias/log
mkdir -p /var/ilias/data/ilias
mkdir -p /var/ilias/data/ilias/mail

chown -R www-data:www-data /var/ilias
chmod -R g+w /var/ilias

echo "Checking file access rights for ILIAS."
if [ "$(stat -c %U /var/www/html)" != "www-data" ]
then
	echo "Fixing file access rights for ILIAS. This might take a moment."
	chown -R www-data:www-data /var/www/html
	chmod -R g+w /var/www/html
	echo "Done."
fi
