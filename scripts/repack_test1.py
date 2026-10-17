"""Repack test E1: relocate/lengthen two strings in the roster payload and write the card.

K. Thomas (76ers): last 'Thomas' -> 'Thomasberger', first 'Kenny' -> 'Zebediah'.
New strings go to a zero gap before the string pool; only the two relative
pointers (value = target - field_offset + 1) change. Size stays identical, CRC32 is updated.
Usage: python scripts/repack_test1.py [CARD]
"""
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from mc_write import write_file

SRC = ROOT / "data/roster_test/payload_current.bin"
CARD = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"C:\Users\Sebastian\Documents\PCSX2\memcards\Mcd001.ps2")
CARD_DIR = "/BESLES-53022Roster1/"

d = bytearray(SRC.read_bytes())
GAP = 0x67000
assert d[GAP:GAP + 0x100] == bytes(0x100)


def utf16(s):
    return s.encode("utf-16-le") + b"\0\0"


def set_ptr(field_off, target):
    struct.pack_into("<I", d, field_off, target - field_off + 1)


def current_target(field_off):
    return field_off + struct.unpack_from("<I", d, field_off)[0] - 1


def read_str(off):
    e = off
    while d[e:e + 2] != b"\0\0":
        e += 2
    return d[off:e].decode("utf-16-le")


LAST_PTR, FIRST_PTR = 0x66BC, 0x66C0
assert read_str(current_target(LAST_PTR)) == "Thomas"
assert read_str(current_target(FIRST_PTR)) == "Kenny"

pos = GAP
for field, text in ((LAST_PTR, "Thomasberger"), (FIRST_PTR, "Zebediah")):
    b = utf16(text)
    d[pos:pos + len(b)] = b
    set_ptr(field, pos)
    pos += (len(b) + 3) & ~3

(ROOT / "data/roster_test/payload_repack1.bin").write_bytes(d)
crc = struct.pack("<I", zlib.crc32(bytes(d)) & 0xFFFFFFFF)
(ROOT / "data/roster_test/extra_repack1.bin").write_bytes(crc)
print("crc", crc.hex(), "size", len(d))

write_file(CARD, CARD_DIR + "BESLES-53022Roster1", bytes(d))
write_file(CARD, CARD_DIR + "EXTRA", crc)
print("written to", CARD)
