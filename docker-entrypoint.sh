#!/bin/sh
# Runs as root only to make the mounted data volume writable by the unprivileged
# `app` user, then drops privileges and execs the server as `app`.
set -e

mkdir -p /data/collections
chown -R app:app /data

exec gosu app "$@"
