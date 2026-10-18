"""Inventory of 'TXTR' texture objects in a PS2 RAM snapshot (name, geometry, pixel/palette pointers).

Layout found by matching a dumped head texture against RAM:
  obj = TXTR magic at +0x0C; +0x10 = name ptr (UTF-16), +0x14 = data header ptr
  data header: +0x18 = pixel ptr (PSMT8, linear rows), pixels followed by a 1 KB CSM1-swizzled palette.
"""
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

MAGIC = b"TXTR"


def wstr(ram, a, n=48):
    out = []
    for i in range(n):
        c = ram[a + 2 * i] | ram[a + 2 * i + 1] << 8
        if c == 0:
            break
        out.append(chr(c))
    return "".join(out)


def find_txtr(ram):
    res = []
    i = ram.find(MAGIC)
    while i >= 0:
        o = i - 0x0C
        if o >= 0 and i % 4 == 0:
            nptr, dptr = struct.unpack_from("<II", ram, i + 4)
            if 0 < nptr < len(ram) and 0 < dptr < len(ram):
                res.append((o, nptr, dptr))
        i = ram.find(MAGIC, i + 1)
    return res


if __name__ == "__main__":
    ram = open(sys.argv[1], "rb").read() if len(sys.argv) > 1 else None
    if ram is None:
        from fast_scan import read_ps2_ram
        ram = read_ps2_ram()
    objs = find_txtr(ram)
    print(len(objs), "TXTR objects")
    from collections import Counter
    c = Counter()
    for o, n, d in objs:
        c[wstr(ram, n)] += 1
    print(ascii(c.most_common(60)))
