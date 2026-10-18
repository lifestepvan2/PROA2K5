"""Write a UTF-16 string into PS2 RAM in place. Usage: python scripts/ram_write_str.py <addr_hex> <max_chars> <text>"""
import sys

from fast_scan import read_ps2_ram, write_ps2_ram

addr, cap, text = int(sys.argv[1], 16), int(sys.argv[2]), sys.argv[3]
assert len(text) <= cap, f"{len(text)} chars > capacity {cap}"
data = (text + "\0" * (cap + 1 - len(text))).encode("utf-16-le")
write_ps2_ram(addr, data)
print(read_ps2_ram()[addr:addr + len(data)].decode("utf-16-le").rstrip("\0"))
