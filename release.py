#!/usr/bin/env python3

torrents_archive_dst_filename = "torrents.tar.xz"
torrents_archive_path_glob = "torrents.????-??-??.tar.xz"
torrents_archive_path_version_regex = r"torrents\.([0-9-]{10})\.tar\.xz"

version_filename = "version.txt"

copy_content_file_list = [
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
import glob

# from torf import Torrent
import torf



def parse_trackerlist(trackerlist):
  return re.findall(
    r"(?:^|\n)([a-z]{3,5}://\S+)",
    trackerlist,
    re.S
  )



def main():

    torrents_archive_path = (sorted(glob.glob(torrents_archive_path_glob) or [None]))[-1]
    if torrents_archive_path is None:
        print(f"error: not found input files with glob pattern {torrents_archive_path_glob}")
        sys.exit(1)

    print(f"torrents_archive_path {torrents_archive_path}")

    version = re.match(torrents_archive_path_version_regex, torrents_archive_path).group(1)
    print(f"version {version}")

    # content_path = f"release/{version}/annas-torrents"
    content_path = f"release/annas-torrents-{version}"
    # content_path = os.path.normpath(content_path)
    if os.path.exists(content_path):
        print(f"error: content_path exists: {content_path}")
        sys.exit(1)
    print("content_path", content_path)

    torrent_file_path = f"{content_path}.torrent"
    if os.path.exists(torrent_file_path):
        print(f"error: torrent_file_path exists: {torrent_file_path}")
        sys.exit(1)

    os.makedirs(content_path)

    for content_file in copy_content_file_list:
        assert os.path.exists(content_file), f"missing file: {content_file}"

    src = torrents_archive_path
    dst = f"{content_path}/{torrents_archive_dst_filename}"
    print(f"moving {src} to {dst}")
    shutil.move(src, dst)

    for content_file in copy_content_file_list:
        dst = f"{content_path}/{content_file}"
        print(f"copying content_file {content_file}")
        if os.path.isdir(content_file):
            shutil.copytree(content_file, dst)
        else:
            shutil.copy(content_file, dst)

    with open(f"{content_path}/{version_filename}", "w") as f:
        f.write(f"{version}\n")

    trackers = parse_trackerlist(trackerlist)

    print("trackers")
    for t in trackers:
        print(f"  {t}")

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
