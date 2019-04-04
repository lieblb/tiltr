FROM ubuntu:latest
MAINTAINER Bernhard.Liebl@rz.uni-regensburg.de

# install essential dependencies.
RUN apt-get update -y && apt-get install -y firefox wget iputils-ping vim npm curl unzip python3-pip \
    && pip3 install selenium requests openpyxl tornado pytz humanize pdb-clone pillow pdfminer3 PyMySQL texttable numpy scipy \
    && npm i -g bulma jquery open-iconic plotly.js bulma-accordion
