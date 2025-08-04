#!/usr/bin/env python3

base_url = "https://annas-archive.org"
torrents_json_url = f"{base_url}/dyn/torrents.json"
cache_file = "torrents.json"
url_prefix = f"{base_url}/dyn/small_file/"
url_prefix_len = len(url_prefix)

torrents_archive_path = "torrents.tar.xz"
version_file_path = "version.txt"

r"""
xz gives the best compression

```py
import subprocess; lines = subprocess.check_output("du -sh --block-size=1 --apparent torrents* | sort -n", shell=True, text=True)
for line in lines.strip().split("\n"): line = line.strip(); size, name = line.split(); print(f"{int(size) / 2189462129 * 100:7.3f}  {size:10s}  {name}")
```

```
 90.759  1987139180  torrents.tar.xz
 91.670  2007089775  torrents.7z
 97.063  2125157902  torrents.tar.zst
 99.599  2180688144  torrents.zip
100.000  2189462129  torrents.tar.gz
240.208  5259273641  torrents
240.945  5275392000  torrents.tar
```
"""

import os
import re
import time
import json
import shlex
import shutil
import asyncio
import subprocess
from pathlib import Path

# pip install packaging aiohttp
import packaging.version
import aiohttp

def get_tar_version():
    try:
        # Run 'tar --version' with LANG=C to ensure consistent output
        result = subprocess.run(
            ["tar", "--version"],
            capture_output=True,
            text=True,
            check=True,
            env={
                "PATH": os.environ["PATH"],
                "LANG": "C",
            }
        )
        # Extract version from the first line
        first_line = result.stdout.split('\n')[0]
        match = re.search(r'tar \(GNU tar\) (\d+\.\d+)', first_line)
        if match:
            return match.group(1)
        else:
            raise ValueError("Could not parse tar version from output")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error running tar command: {e.stderr}") from e
    except Exception as e:
        raise RuntimeError(f"Error getting tar version: {str(e)}") from e

def check_min_version(current_version, min_version="1.28"):
    try:
        return packaging.version.parse(current_version) >= packaging.version.parse(min_version)
    except Exception as e:
        raise ValueError(f"Version comparison failed: {str(e)}") from e

def format_date(date_int):
    date_str = str(date_int)
    assert len(date_str) == 8, f"invalid date_str {date_str}"
    return "-".join([
        date_str[0:4], # year
        date_str[4:6], # month
        date_str[6:8], # day
    ])

def parse_date(date_str):
    assert len(date_str) == 10, f"invalid date_str {date_str}" # "2024-03-07"
    return int(date_str.replace("-", "")) # 20240307

async def main():

    # check dependencies
    for bin in ["tar", "pixz"]:
        assert shutil.which(bin), f"please install {bin}"

    # check tar version
    min_tar_version = "1.28"
    try:
        tar_version = get_tar_version()
        # print(f"Found tar version: {tar_version}")
        if check_min_version(tar_version, min_tar_version):
            # print(f"ok: tar version meets minimum requirement {min_tar_version}")
            # return 0
            pass
        else:
            print(f"error: tar version {tar_version} is below minimum requirement {min_tar_version}")
            return 1
    except Exception as e:
        print(f"Error: {str(e)}")
        return 1

    # print("ok"); return # debug

    # Check and update cache file if needed
    num_removed_files = 0
    cache_path = Path(cache_file)
    if cache_path.exists():
        cache_age = time.time() - cache_path.stat().st_ctime
        if cache_age > 60 * 60 * 24:  # 24 hours
            print(f"removing old {cache_file}")
            cache_path.unlink()
            num_removed_files += 1

    if not cache_path.exists():
        async with aiohttp.ClientSession() as session:
            async with session.get(torrents_json_url) as response:
                assert response.status == 200, f"bad response.status {response.status}"
                with open(cache_file, 'wb') as f:
                    while True:
                        chunk = await response.content.read(1024)
                        if not chunk:
                            break
                        f.write(chunk)

    # no. this was needed for "wget --recursive"
    if 0:
        # Create directories and symlink (similar to original bash script)
        Path("torrents").mkdir(exist_ok=True)
        Path("annas-archive.org/dyn/small_file").mkdir(parents=True, exist_ok=True)
        symlink_path = Path("annas-archive.org/dyn/small_file/torrents")
        if not symlink_path.exists():
            symlink_target = Path("torrents").relative_to(symlink_path.parent, walk_up=True)
            try:
                symlink_path.symlink_to(symlink_target, target_is_directory=True)
            except OSError as e:
                print(f"error: failed to create symlink {symlink_path}: {e}")
                return

    # Process torrents.json and prepare download URLs
    with open(cache_file) as f:
        torrents = json.load(f)

    download_urls = []
    last_torrent_date_int = 0
    for torrent in torrents:
        url = torrent['url']
        size = torrent['torrent_size']
        obsolete = torrent['obsolete']
        embargo = torrent['embargo']

        if not url.startswith(url_prefix):
            print(f"ignoring url {url}", file=sys.stderr)
            continue

        if obsolete or embargo:
            path = Path(url[url_prefix_len:])
            if path.exists():
                print(f"removing {path}", file=sys.stderr)
                path.unlink()
            continue

        path = Path(url[url_prefix_len:])

        # ignore annas-torrents torrents
        # example:
        # torrents/managed_by_aa/annas-torrents-2025-07-14.torrent/annas-torrents-2025-07-14.torrent
        if str(path).startswith("torrents/managed_by_aa/annas-torrents-"):
            continue

        torrent_date_int = parse_date(torrent['added_to_torrents_list_at'])

        if torrent_date_int > last_torrent_date_int:
            last_torrent_date_int = torrent_date_int

        if path.exists():
            actual_size = path.stat().st_size
            if actual_size != size:
                print(f"removing {path} (size mismatch)", file=sys.stderr)
                path.unlink()
            continue

        download_urls.append(url)

    # Download all files reusing the same TCP connection
    if download_urls:
        async with aiohttp.ClientSession() as session:
            for url in download_urls:
                path = Path(url[url_prefix_len:])
                path.parent.mkdir(parents=True, exist_ok=True)

                # print(f"fetching {url}")
                print(f"fetching {path}")
                async with session.get(url) as response:
                    with open(path, 'wb') as f:
                        while True:
                            chunk = await response.content.read(1024)
                            if not chunk:
                                break
                            f.write(chunk)

    last_torrent_date = format_date(last_torrent_date_int)

    if os.path.exists(version_file_path):
        with open(version_file_path) as f:
            version = f.read().strip()
    else:
        version = ""

    if version == last_torrent_date:
        print(f"already up to date: version {last_torrent_date}")
        return
    else:
        print(f"updating version {last_torrent_date} in {version_file_path}")
        with open(version_file_path, "w") as f:
            f.write(last_torrent_date + "\n")

    if len(download_urls) == 0 and num_removed_files == 0:
        print(f"already up to date: no files were added or removed")
        return

    # create a reproducible tar archive
    # https://reproducible-builds.org/docs/archives/#full-example
    # https://stackoverflow.com/questions/32997526/how-to-create-a-tar-file-that-omits-timestamps-for-its-contents
    # https://unix.stackexchange.com/questions/438329/tar-produces-different-files-each-time
    temp_torrents_tar_path = f"torrents.{time.time()}.tar"
    args = [
        "tar",
        "--sort=name",
        "--mtime=UTC 1970-01-01",
        "--owner=0",
        "--group=0",
        "--numeric-owner",
        "--pax-option=exthdr.name=%d/PaxHeaders/%f,delete=atime,delete=ctime",
        "-c",
        "-f", temp_torrents_tar_path,
        # archive contents
        "torrents",
        "torrents.json",
    ]
    print(">", shlex.join(args))
    t1 = time.time()
    subprocess.run(args)
    t2 = time.time()
    print(f"done in {t2 - t1:.1f} seconds")

    # use pixz to compress the tar archive
    args = [
        "pixz",
        "-1", # level 1: lowest compression
        "-k", # keep input file
        temp_torrents_tar_path,
        torrents_archive_path,
    ]
    print(">", shlex.join(args))
    t1 = time.time()
    subprocess.run(args)
    t2 = time.time()
    print(f"done in {t2 - t1:.1f} seconds")

    # by default, pixz keeps the input file
    if 0:
        if os.path.exists(temp_torrents_tar_path):
            os.unlink(temp_torrents_tar_path)
    else:
        print(f"keeping tempfile {temp_torrents_tar_path}")

    print(f"done {torrents_archive_path}")

if __name__ == "__main__":
    import sys
    asyncio.run(main())
