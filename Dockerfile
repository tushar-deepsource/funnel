FROM python:3.9-slim-bullseye

RUN apt-get -y update

# install curl 
RUN apt-get -y install curl

# get install script and pass it to execute: 
RUN curl -sL https://deb.nodesource.com/setup_14.x | bash

# and install node 
RUN apt-get -y install nodejs git wget unzip

RUN wget --quiet https://github.com/markokr/pghashlib/archive/master.zip -O pghashlib.zip \
  && unzip pghashlib.zip \
  && cd pghashlib-master \
  && PG_CONFIG=/usr/lib/postgresql/$PG_MAJOR/bin/pg_config make \
  && PG_CONFIG=/usr/lib/postgresql/$PG_MAJOR/bin/pg_config make install \
  && ldconfig

RUN sed -ri "s/^#?(shared_preload_libraries\s*=\s*)\S+/\1'pg_stat_statements'/" /usr/share/postgresql/$PG_MAJOR/postgresql.conf.sample

# We don't want to run our application as root if it is not strictly necessary, even in a container.
# Create a user and a group called 'app' to run the processes.
# A system user is sufficient and we do not need a home.

RUN adduser --system --group --no-create-home app


# Place the application components in a dir below the root dir
COPY . /app

# Make the directory the working directory for subsequent commands
WORKDIR /app

# Install from the requirements.txt we copied above
COPY requirements.txt /tmp
RUN pip install -r requirements.txt
COPY . /tmp/myapp
RUN pip install /tmp/myapp

# Hand everything over to the 'app' user
RUN chown -R app:app /app

# Subsequent commands, either in this Dockerfile or in a
# docker-compose.yml, will run as user 'app'
USER app

# We are done with setting up the image.
# As this image is used for different
# purposes and processes no CMD or ENTRYPOINT is specified here,
# this is done in docker-compose.yml.


