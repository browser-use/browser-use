FROM selenium/node-chrome:latest

USER root

RUN apt-get update -qqy \
  && rm -rf /var/lib/apt/lists/* /var/cache/apt/* \
  && rm /bin/sh && ln -s /bin/bash /bin/sh \
  && chown seluser /usr/local

ENV NVM_DIR /usr/local/nvm
RUN mkdir -p $NVM_DIR \
  && wget -qO- https://raw.githubusercontent.com/creationix/nvm/v0.35.2/install.sh | bash \
  && source $NVM_DIR/nvm.sh \
  && nvm install v12

ENV CHROME_BIN /opt/google/chrome/chrome
ENV INSIDE_DOCKER=1

WORKDIR /usr/src
ENTRYPOINT source $NVM_DIR/nvm.sh && npm i && npm test