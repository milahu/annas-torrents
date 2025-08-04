#!/usr/bin/env bash

set -eu

if [ -e mnt ]; then
  echo "error: mountpoint exists: mnt"
  exit 1
fi

if ! command -v ratarmount &>/dev/null; then
  echo "error: missing command: ratarmount"
  echo "  please install ratarmount. examples:"
  echo "    pip install ratarmount"
  echo "    sudo apt install ratarmount"
  echo "    nix-shell -p ratarmount"
  exit 1
fi

if ! [ -e torrents.tar.xz ]; then
  echo "error: missing file: torrents.tar.xz"
  exit 1
fi

set -x

exec ratarmount torrents.tar.xz mnt
