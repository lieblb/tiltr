FROM ubuntu:latest
MAINTAINER Bernhard.Liebl@rz.uni-regensburg.de

# install essential dependencies.
RUN apt-get update -y && apt-get install -y firefox wget iputils-ping vim npm curl unzip python3-pip \
    && pip3 install selenium requests openpyxl tornado pytz humanize pdb-clone pillow pdfminer.six \
    && npm i -g bulma jquery open-iconic plotly.js bulma-accordion

# install a recent phantomjs so we have a working PDF export environment. older (apt) phantomjs versions
# produce absolute garbage. install script from https://gist.github.com/telbiyski/ec56a92d7114b8631c906c18064ce620

ENV PHANTOM_JS phantomjs-2.1.1-linux-x86_64
RUN apt-get update -y && apt-get install -y wget && cd ~ && wget https://github.com/Medium/phantomjs/releases/download/v2.1.1/$PHANTOM_JS.tar.bz2 &&  tar xvjf $PHANTOM_JS.tar.bz2 && mv $PHANTOM_JS /usr/local/share && ln -sf /usr/local/share/$PHANTOM_JS/bin/phantomjs /usr/bin/phantomjs
