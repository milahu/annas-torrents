#!/usr/bin/env python3

torrents_archive_path = "torrents.tar.xz"
version_file_path = "version.txt"

move_content_file_list = [
    torrents_archive_path,
]

copy_content_file_list = [
    version_file_path,
    "mount.sh",
    "release.py",
    "shell.nix",
    "umount.sh",
    "update.py",
]

# https://github.com/ngosang/trackerslist
# https://github.com/ngosang/trackerslist/blob/master/trackers_all_ip.txt
# https://github.com/milahu/deutschetorrents/blob/main/trackerlist.txt
trackerlist = """
udp://45.9.60.30:6969/announce
udp://185.216.179.62:25/announce
udp://93.158.213.92:1337/announce
udp://107.189.2.131:1337/announce
"""



import os
import sys
import time
import re
import shutil
import urllib.parse
import dataclasses
import subprocess
import json

# from torf import Torrent
import torf



def parse_trackerlist(trackerlist):
  return re.findall(
    r"(?:^|\n)([a-z]{3,5}://\S+)",
    trackerlist,
    re.S
  )

trackers = parse_trackerlist(trackerlist)

print("trackers")
for t in trackers:
    print(f"  {t}")



def main():

    with open(version_file_path) as f:
        version = f.read().strip()

    # content_path = f"release/{version}/annas-torrents"
    content_path = f"release/annas-torrents-{version}"
    # content_path = os.path.normpath(content_path)
    print("content_path", content_path)

    if os.path.exists(content_path):
        print(f"error: content_path exists: {content_path}")
        return 1

    os.makedirs(content_path)

    for content_file in move_content_file_list + copy_content_file_list:
        assert os.path.exists(content_file), f"missing file: {content_file}"

    for content_file in move_content_file_list:
        dst = f"{content_path}/{content_file}"
        print(f"moving content_file {content_file}")
        shutil.move(content_file, dst)

    for content_file in copy_content_file_list:
        dst = f"{content_path}/{content_file}"
        print(f"copying content_file {content_file}")
        if os.path.isdir(content_file):
            shutil.copytree(content_file, dst)
        else:
            shutil.copy(content_file, dst)

    torrent_file_path = f"{content_path}.torrent"

    print("creating new torrent file")
    t = torf.Torrent(
        path=content_path,
        trackers=trackers,
        creation_date=None,
        created_by=None,
        randomize_infohash=False,
    )
    t.generate()

    btih = t.infohash
    print("btih", btih)
    assert len(btih) == 40

    magnet_link = str(t.magnet())

    print("magnet", magnet_link)

    if not os.path.exists(torrent_file_path):
        print(f"writing {torrent_file_path}")
        t.write(torrent_file_path)



if __name__ == "__main__":

    sys.exit(main() or 0)
