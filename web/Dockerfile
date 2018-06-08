FROM php:7.1-apache
MAINTAINER Bernhard.Liebl@rz.uni-regensburg.de

RUN apt-get update && apt-get install -y  vim less && \
	docker-php-ext-install mbstring mysqli pdo pdo_mysql && \
	apt-get install -y zlib1g-dev && docker-php-ext-install zip && \
	apt-get install -y libpng-dev && \
	apt-get install -y libldap2-dev && docker-php-ext-configure ldap --with-libdir=lib/x86_64-linux-gnu/ && \
	docker-php-ext-install ldap && \
	apt-get install -y zip imagemagick && \
	apt-get install -y libxslt-dev && docker-php-ext-install xsl && \
	apt-get install -y libjpeg-dev && \
	docker-php-ext-configure gd --with-jpeg-dir=/usr/lib/x86_64-linux-gnu && \
	docker-php-ext-install gd && \
	apt-get install -y libmagickwand-dev && \
	docker-php-ext-install opcache
RUN yes '' | pecl install imagick

COPY custom/php.ini /usr/local/etc/php/php.ini
COPY custom/prologue.php /var/www/html/prologue.php
COPY custom/ilias-startup.sh /usr/local/bin/

