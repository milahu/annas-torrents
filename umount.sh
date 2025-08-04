#!/usr/bin/env bash

set -eu

# this should be part of every "normal" linux distro
if ! command -v fusermount &>/dev/null; then
  echo "error: missing command: fusermount"
  echo "  please install fuse"
  exit 1
fi

set -x

exec fusermount -u mnt
