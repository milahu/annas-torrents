#!/usr/bin/env python3

base_url = "https://annas-archive.org"
torrents_json_url = f"{base_url}/dyn/torrents.json"
cache_file = "torrents.json"
url_prefix = f"{base_url}/dyn/small_file/"
url_prefix_len = len(url_prefix)

version_file_path = "version.txt"

import os
import re
import time
import json
import asyncio
from pathlib import Path

# pip install aiohttp
import aiohttp

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
            else:
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
        sys.exit(1)
    else:
        print(f"updating version {last_torrent_date} in {version_file_path}")
        with open(version_file_path, "w") as f:
            f.write(last_torrent_date + "\n")

    if len(download_urls) == 0 and num_removed_files == 0:
        print(f"already up to date: no files were added or removed")
        sys.exit(1)

    print("ok. next: run pack.py")


if __name__ == "__main__":
    import sys
    asyncio.run(main())
