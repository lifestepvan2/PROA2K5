"""Locate arena name strings in PS2 RAM. Usage: python scripts/arena_probe.py "Palace of Auburn Hills" [...]"""
import struct
import sys

from fast_scan import read_ps2_ram

ram = read_ps2_ram()
for text in sys.argv[1:]:
    for enc in ("utf-16-le", "ascii"):
        needle = text.encode(enc)
        pos, hits = 0, []
        while (i := ram.find(needle, pos)) != -1:
            hits.append(i)
            pos = i + 1
        print(f"[{text!r} {enc}] {len(hits)} hits")
        for i in hits:
            ctx = ram[max(0, i - 16):i + len(needle) + 16]
            print(f"  {i:#010x}  {ctx!r}")
            # absolute pointers to this string start
            ptr = struct.pack("<I", i)
            p, refs = 0, []
            while (j := ram.find(ptr, p)) != -1:
                if j % 4 == 0:
                    refs.append(j)
                p = j + 1
            print("    pointers:", [hex(r) for r in refs[:10]])
