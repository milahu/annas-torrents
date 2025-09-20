#!/usr/bin/env python3

import os
import time

from torf import Torrent

def find_torrent_files(directory):
    """Recursively yield .torrent files from a directory."""
    for root, _, files in os.walk(directory):
        for f in files:
            if f.endswith(".torrent"):
                yield os.path.join(root, f)

def main():
    directory = "torrents"
    total_size = 0
    weighted_piece_sum = 0
    num_torrents = 0

    # For multi-file torrents
    multi_file_total_size = 0
    multi_file_total_count = 0

    t1 = time.time()

    for torrent_path in find_torrent_files(directory):
        print()
        print(f"torrent_path {torrent_path}")
        num_torrents += 1
        try:
            print("Torrent.read")
            t = Torrent.read(torrent_path)
            print("t.piece_size")
            piece_size = t.piece_size
            print("t.size")
            content_size = t.size
            # t.files is extremely slow on torrents with many files
            print("t.files")
            file_count = len(t.files) if t.files else 0

            if content_size > 0:
                weighted_piece_sum += piece_size * content_size
                total_size += content_size

            # If multi-file with at least 100 files, include in avg file size calc
            if file_count >= 100 and content_size > 0:
                multi_file_total_size += content_size
                multi_file_total_count += file_count

            print(f"Parsed: {torrent_path} | Piece size: {piece_size} | "
                  f"Content size: {content_size} | Files: {file_count}")

        except Exception as e:
            print(f"Error parsing {torrent_path}: {e}")

    t2 = time.time()
    dt = t2 - t1

    print("\n=== Results ===")
    print(f"processed {num_torrents} in {dt} seconds")
    if total_size > 0:
        weighted_avg_piece_size = weighted_piece_sum / total_size
        print(f"Weighted average piece size: {weighted_avg_piece_size:.2f} bytes")
    else:
        print("No valid torrent files found.")

    if multi_file_total_count > 0:
        avg_file_size = multi_file_total_size / multi_file_total_count
        print(f"Average file size (multi-file torrents with ≥100 files): {avg_file_size:.2f} bytes")
    else:
        print("No multi-file torrents with at least 100 files found.")

if __name__ == "__main__":
    main()
