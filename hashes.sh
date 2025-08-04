#!/usr/bin/env bash

# hashes.sh
# create a .hashes file for all input files
# MIT license

# https://unix.stackexchange.com/questions/163747/simultaneously-calculate-multiple-digests-md5-sha256

set -u

for input_path in "$@"; do

  output_path="$input_path".hashes

  if ! [ -e "$input_path" ]; then
    echo "error: missing input file: $input_path"
    continue
  fi

  if [ -e "$output_path" ]; then
    echo "error: output file exists: $output_path"
    continue
  fi

  echo "writing $output_path"
  {
    stat -L -c"size:%s" "$input_path"
    {
      # run hashers in parallel
      pv -p -t -e -a -w80 "$input_path" |
      tee >(
      md5sum | sed -E 's/^([0-9a-f]+)\s.*$/md5:\1/' >&3
      ) | tee >(
      sha1sum | sed -E 's/^([0-9a-f]+)\s.*$/sha1:\1/' >&3
      ) | tee >(
      tiger-hash - | sed -E 's/^([0-9a-f]+)\s.*$/tiger:\1/' >&3
      ) | tee >(
      sha256sum | sed -E 's/^([0-9a-f]+)\s.*$/sha256:\1/' >&3
      ) | tee >(
      sha384sum | sed -E 's/^([0-9a-f]+)\s.*$/sha384:\1/' >&3
      ) |
      sha512sum | sed -E 's/^([0-9a-f]+)\s.*$/sha512:\1/' >&3
    } 3>&1
  } >"$output_path"

done
