"""Patch every UTF-16LE occurrence of a string in PS2 RAM.

Usage: python scripts/patch_names.py OLD NEW [OLD NEW ...]
NEW may be shorter than OLD (null padded); longer is rejected.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fast_scan import read_ps2_ram, write_ps2_ram


def find_all(ram: bytes, needle: bytes):
    pos = 0
    while True:
        i = ram.find(needle, pos)
        if i < 0:
            return
        yield i
        pos = i + 1


def patch(old: str, new: str, ram: bytes | None = None, whole_word: bool = True):
    ram = ram or read_ps2_ram()
    if len(new) > len(old):
        raise ValueError(f"{new!r} longer than {old!r}")
    o = old.encode("utf-16-le")
    n = new.encode("utf-16-le").ljust(len(o), b"\x00")
    done = []
    for i in find_all(ram, o):
        # whole-word: next char must be a terminator/non-letter, previous char not a letter
        nxt = ram[i + len(o): i + len(o) + 2]
        prv = ram[i - 2: i] if i >= 2 else b"\x00\x00"
        if whole_word:
            if nxt[1:2] == b"\x00" and nxt[:1].isalpha():
                continue
            if prv[1:2] == b"\x00" and prv[:1].isalpha():
                continue
        write_ps2_ram(i, n)
        done.append(hex(i))
    return done


if __name__ == "__main__":
    args = sys.argv[1:]
    ram = read_ps2_ram()
    for a, b in zip(args[::2], args[1::2]):
        print(a, "->", b, patch(a, b, ram))
