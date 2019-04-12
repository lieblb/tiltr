FROM alpine AS build-stage

ARG TILTR_ILIAS_DB_VERSION

ADD ilias.${TILTR_ILIAS_DB_VERSION}.sql.zip /ilias.sql.zip
ADD changes.sql /changes.sql
RUN apk update && apk upgrade && apk add zip && unzip /ilias.sql.zip -d /
RUN cat /ilias.sql /changes.sql > /ilias.new.sql && cp /ilias.new.sql /ilias.sql

FROM mysql:5.7
MAINTAINER Bernhard.Liebl@rz.uni-regensburg.de

RUN { echo '[mysqld]'; } >> /etc/mysql/my.cnf
RUN { echo 'sql_mode=NO_ENGINE_SUBSTITUTION'; } >> /etc/mysql/my.cnf
RUN { echo 'max_allowed_packet=16M '; } >> /etc/mysql/my.cnf

COPY --from=build-stage /ilias.sql /docker-entrypoint-initdb.d
CMD ["--character-set-server=utf8mb4", "--collation-server=utf8mb4_unicode_ci"]
