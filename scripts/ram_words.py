"""Dump u32 words of PS2 RAM. Usage: python scripts/ram_words.py <start_hex> <count> [stride_words_per_row]"""
import struct
import sys

from fast_scan import read_ps2_ram

start, count = int(sys.argv[1], 16), int(sys.argv[2])
per = int(sys.argv[3]) if len(sys.argv) > 3 else 6
ram = read_ps2_ram()
for r in range(0, count, per):
    a = start + r * 4
    w = struct.unpack_from(f"<{min(per, count - r)}I", ram, a)
    print(f"{a:#010x}: " + " ".join(f"{x:08x}" for x in w))
