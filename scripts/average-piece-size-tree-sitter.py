#!/usr/bin/env python3

"""
=== Results ===
processed 17674 torrents in 742.266 seconds
Weighted average piece size: 151627891.04 bytes
Average file size (multi-file torrents with ≥100 files): 22400413.27 bytes
"""

# FIXME tree-sitter-bencode fails to parse long strings (longer than 40KB)
# https://github.com/tree-sitter/tree-sitter/issues/4857

"""
Fast .torrent header scanner using tree-sitter-bencode.

Features:
- If needed, runs `tree-sitter generate` and `tree-sitter build` inside
  lib/tree-sitter-bencode/ to produce lib/tree-sitter-bencode/bencode.so
- Robustly loads the compiled grammar across multiple py-tree-sitter/tree-sitter
  Python binding versions (tries several load strategies)
- Parses .torrent files with tree-sitter so we never fully decode the huge
  "pieces" blob; extracts only `info -> piece length`, `info -> length` or
  `info -> files[*].length` and file counts.
- Prints weighted average piece size (weighted by torrent total content size)
  and average file size for multi-file torrents with >= 100 files.

Usage:
    python torrent_tree_sitter_fast_parser.py /path/to/torrents

Note: this script assumes the grammar's shared object lives at
`lib/tree-sitter-bencode/bencode.so` and that the exported language name is
`bencode` (the usual name for that grammar). If you built the grammar with a
different name, pass that name to `load_tree_sitter_language`.
"""

import os
import re
import sys
import time
from ctypes import c_void_p, CDLL, PYFUNCTYPE, pythonapi, py_object, c_char_p
import subprocess
# from pathlib import Path
from typing import Optional, Tuple

import tree_sitter
# from tree_sitter import Language, Parser

# https://github.com/Samasaur1/tree-sitter-bencode
BENCODE_LIB = "lib/tree-sitter-bencode/bencode.so"
BENCODE_SRC_DIR = "lib/tree-sitter-bencode"
# BENCODE_NAME = "bencode"

def build_tree_sitter_language(lib_path: str, source_path: str):
    if os.path.exists(lib_path):
        return
    if not os.path.exists(source_path):
        raise FileNotFoundError(source_path)
    args = ["tree-sitter", "generate", "--abi", str(tree_sitter.LANGUAGE_VERSION)]
    subprocess.run(args, cwd=source_path, check=True)
    # args = ["tree-sitter", "build"]
    args = ["tree-sitter", "build", "--debug"]
    subprocess.run(args, cwd=source_path, check=True)
    if not os.path.exists(lib_path):
        raise RuntimeError(f"failed to build {lib_path}")

def load_tree_sitter_language(lib_path: str, name: str = None):
    "load a tree-sitter language from its parser.so file"
    if name is None:
        name = os.path.basename(lib_path)
        name = re.sub(r"\.(so|dylib|dll)$", "", name)
    # note: there is no tree_sitter.__version__
    # https://github.com/tree-sitter/py-tree-sitter/issues/413
    # but maybe we can use tree_sitter.LANGUAGE_VERSION
    # to switch these branches without try/except blocks
    excs = []
    # Strategy A: the "traditional" constructor Language(lib_path, name)
    # if ? <= tree_sitter.LANGUAGE_VERSION <= ?:
    try:
        lang = tree_sitter.Language(lib_path, name)
        # print("load_tree_sitter_language: strategy A")
        return lang
    except Exception as exc:
        excs.append(exc)
    # Strategy B: some packaged languages expose a module like 'tree_sitter_<name>'
    # that exposes a function language() which returns a pointer/handle we can
    # pass to Language(...)
    # if ? <= tree_sitter.LANGUAGE_VERSION <= ?:
    try:
        module_name = f"tree_sitter_{name}"
        lang_mod = __import__(module_name)
        if hasattr(lang_mod, "language"):
            ptr = lang_mod.language()
            # In newer py-tree-sitter, Language(ptr) expects the raw pointer
            lang = tree_sitter.Language(ptr)
            # print("load_tree_sitter_language: strategy B")
            return lang
    except Exception as exc:
        excs.append(exc)
    # Strategy C: load the .so with ctypes and call the exported symbol
    # tree_sitter_<name>() to obtain a TSLanguage* pointer, then pass it into
    # Language(ptr).
    # if ? <= tree_sitter.LANGUAGE_VERSION:
    try:
        cdll = CDLL(os.path.abspath(lib_path))
        func_name = f"tree_sitter_{name}"
        if not hasattr(cdll, func_name):
            # sometimes grammar authors compile with an alternate exported name
            alt = func_name + "_language"
            if hasattr(cdll, alt):
                func_name = alt
        func = getattr(cdll, func_name)
        func.restype = c_void_p
        ptr = func()
        PyCapsule_New = PYFUNCTYPE(py_object, c_void_p, c_char_p, c_void_p)(("PyCapsule_New", pythonapi))
        ptr = PyCapsule_New(ptr, b"tree_sitter.Language", None)
        lang = tree_sitter.Language(ptr)
        # print("load_tree_sitter_language: strategy C")
        return lang
    except Exception as exc:
        excs.append(exc)
    raise RuntimeError(f"Failed to load tree-sitter language from {lib_path}: {excs}")

def create_tree_sitter_parser(language):
    excs = []
    try:
        parser = tree_sitter.Parser(language)
        return parser
    except Exception as exc:
        excs.append(exc)
    try:
        parser = tree_sitter.Parser()
        parser.set_language(language)
        return parser
    except Exception as exc:
        excs.append(exc)
    raise RuntimeError(f"Failed to create tree-sitter parser from {language}: {excs}")

# ---------------------------------------------------------------------------
# Bencode node helpers (use source slices so we never materialize large blobs)
# ---------------------------------------------------------------------------

def decode_bencode_number(node, source: bytes) -> int:
    # node contains something like b'i123e'
    raw = source[node.start_byte:node.end_byte]
    # strip leading 'i' and trailing 'e'
    return int(raw[1:-1])


def decode_bencode_string(node, source: bytes) -> bytes:
    # node contains something like b'4:spam' (length:data)
    raw = source[node.start_byte:node.end_byte]
    # print(f"raw {raw[:100]}")
    sep = raw.find(b":")
    if sep == -1:
        # unexpected format — return full raw as a fallback
        return raw
    length = int(raw[:sep])
    data = raw[sep + 1 : sep + 1 + length]
    return data

# https://github.com/tree-sitter/py-tree-sitter/blob/master/examples/walk_tree.py
from tree_sitter import Language, Parser, Tree, Node
def print_tree(tree: Tree, source: bytes) -> None:
    cursor = tree.walk()
    visited_children = False
    depth = 0
    while True:
        if not visited_children:
            # yield cursor.node
            node = cursor.node
            node_source = source[node.start_byte:min(node.end_byte, (node.start_byte + 100))]
            print((depth * "  ") + node.type + ": " + repr(node_source))
            if cursor.goto_first_child():
                depth += 1
            else:
                visited_children = True
        elif cursor.goto_next_sibling():
            visited_children = False
        elif cursor.goto_parent():
            depth -= 1
        else:
            break


# node_names = map(lambda node: node.type, traverse_tree(tree))



# ---------------------------------------------------------------------------
# Parse header (extract piece_length, total_size, file_count) using tree-sitter
# ---------------------------------------------------------------------------

def parse_torrent_header_bytes(source: bytes, parser) -> Tuple[Optional[int], int, int]:
    """Return (piece_length, total_size, file_count).

    This version understands the AST produced by the grammar you pasted: a
    `dictionary` node contains alternating `string` and value nodes as
    *named_children* (i.e. key, value, key, value...). We therefore iterate
    the named_children in pairs instead of looking for a `pair` node.
    """
    # print(f"source {source[:100]}")
    sys.stdout.flush()
    tree = parser.parse(source)
    sys.stdout.flush()
    # print(f"tree {tree}")
    root = tree.root_node

    # print_tree(tree, source); sys.exit() # debug

    if 1:
        # locate the top-level dictionary node (works whether root is source_file
        # or the dictionary itself)
        top = None
        if root.type == "source_file":
            for c in root.named_children:
                if c.type == "dictionary":
                    top = c
                    break
            if top is None and len(root.named_children) > 0:
                top = root.named_children[0]
        elif root.type == "dictionary":
            top = root
        else:
            for c in root.named_children:
                if c.type == "dictionary":
                    top = c
                    break
    else:
        top = root

    def iter_pairs(dict_node):
        """Yield (key_node, value_node) pairs for a dictionary node.

        The grammar produces alternating named children (string, value), so we
        step two at a time.
        """
        # print(f"iter_pairs: dict_node={dict_node}")
        children = dict_node.named_children
        i = 0
        while i + 1 < len(children):
            yield children[i], children[i + 1]
            i += 2

    piece_length = None
    total_size = 0
    file_count = 0

    if top is None:
        # print("top is None")
        return piece_length, total_size, file_count

    # Find the top-level 'info' entry and inspect its dictionary
    for key_node, val_node in iter_pairs(top):
        # print(f"key_node {key_node}")
        try:
            key_bytes = decode_bencode_string(key_node, source)
        except Exception:
            continue

        # announce announce-list info
        # print(f"key_bytes {key_bytes} val_node.type={val_node.type}")

        if key_bytes == b"info":
            info_node = val_node
            if info_node.type != "dictionary":
                break

            # Walk pairs inside the info dict
            for ik_node, iv_node in iter_pairs(info_node):
                try:
                    ik = decode_bencode_string(ik_node, source)
                except Exception:
                    continue

                # print(f"ik {ik}: iv_node.type={iv_node.type}")

                if ik == b"piece length":
                    if iv_node.type == "int":
                        try:
                            piece_length = decode_bencode_number(iv_node, source)
                        except Exception:
                            pass

                elif ik == b"length":
                    if iv_node.type == "int":
                        try:
                            length = decode_bencode_number(iv_node, source)
                            total_size += length
                            file_count += 1
                        except Exception:
                            pass

                elif ik == b"pieces" and iv_node.type == "string":
                    s = decode_bencode_string(iv_node, source)
                    # print(f"s {s}")

                elif ik == b"files":
                    # 'files' is a list of file dictionaries
                    if iv_node.type == "list":
                        for item in iv_node.named_children:
                            if item.type != "dictionary":
                                continue
                            # each file dict has pairs; find the 'length' pair
                            for fk_node, fv_node in iter_pairs(item):
                                try:
                                    fk = decode_bencode_string(fk_node, source)
                                except Exception:
                                    continue
                                if fk == b"length" and fv_node.type == "int":
                                    try:
                                        total_size += decode_bencode_number(fv_node, source)
                                        file_count += 1
                                        # break # next file
                                    except Exception:
                                        pass
            # once we've processed 'info', we can stop
            # break

        # if val_node.type == "ERROR":
        #     raise Exception("fixme")

    return piece_length, total_size, file_count

# ---------------------------------------------------------------------------
# Main scanning loop
# ---------------------------------------------------------------------------

def find_torrent_files(directory: str):
    # yield "torrents/external/libgen_rs_non_fic/r_3585000.torrent"; return
    for root, _, files in os.walk(directory):
        for f in files:
            if f.endswith(".torrent"):
                yield os.path.join(root, f)

def main():
    directory = "torrents"

    build_tree_sitter_language(BENCODE_LIB, BENCODE_SRC_DIR)
    lang = load_tree_sitter_language(BENCODE_LIB)
    parser = create_tree_sitter_parser(lang)

    total_size = 0
    weighted_piece_sum = 0
    multi_file_total_size = 0
    multi_file_total_count = 0
    num_torrents = 0

    t1 = time.time()

    for i, torrent_path in enumerate(find_torrent_files(directory), start=1):
        # print(f"torrent_path {torrent_path}")
        # https://annas-archive.org/dyn/small_file/torrents/managed_by_aa/isbndb/isbndb_2022_09.torrent
        num_torrents += 1
        try:
            with open(torrent_path, "rb") as fh:
                src = fh.read()

            """
            # debug
            src = b"d4:infod6:lengthi4372041675e4:name23:isbndb_2022_09.jsonl.gz12:piece lengthi2097152e6:pieces10:" + (b"\x00" * 10) + b"ee"
            src = b"d4:infod6:pieces10:" + (b"\x00" * 10) + b"ee"
            src = b"d4:infod6:pieces10000:" + (b"\x00" * 10_000) + b"ee"
            src = b"d4:infod6:pieces50000:" + (b"\x00" * 50_000) + b"ee"
            src = b"d4:infod6:pieces100000:" + (b"\x00" * 100_000) + b"ee" # FIXME why does this work
            src = b"d4:infod6:pieces1000000:" + (b"\x00" * 1_000_000) + b"ee" # FIXME why does this work
            src = b"d4:infod6:pieces10000000:" + (b"\x00" * 10_000_000) + b"ee" # FIXME why does this work
            src = b"d4:infod7:somekeyl" + ((b"200:" + (b"\x00" * 200)) * 50) + b"e6:pieces100000:" + (b"\x00" * 100_000) + b"ee" # FIXME why does this work
            """
            import random
            src = b"d4:infod6:pieces100000:" + random.randbytes(100_000) + b"ee" # this breaks

            piece_size, content_size, file_count = parse_torrent_header_bytes(src, parser)

            # break # debug

            if piece_size and content_size > 0:
                weighted_piece_sum += piece_size * content_size
                total_size += content_size

            if file_count >= 100 and content_size > 0:
                multi_file_total_size += content_size
                multi_file_total_count += file_count

            print(f"[{i}] {torrent_path} -> piece={piece_size} size={content_size} files={file_count}")
        except Exception as e:
            print(f"[{i}] Error parsing {torrent_path}: {e}")

    t2 = time.time()
    dt = t2 - t1

    print("\n=== Results ===")
    print(f"processed {num_torrents} torrents in {dt} seconds")
    if total_size > 0:
        weighted_avg_piece_size = weighted_piece_sum / total_size
        print(f"Weighted average piece size: {weighted_avg_piece_size:.2f} bytes")
    else:
        print("No valid torrent files found for weighted piece calculation.")

    if multi_file_total_count > 0:
        avg_file_size = multi_file_total_size / multi_file_total_count
        print(f"Average file size (multi-file torrents with ≥100 files): {avg_file_size:.2f} bytes")
    else:
        print("No multi-file torrents with at least 100 files found.")


if __name__ == "__main__":
    main()
