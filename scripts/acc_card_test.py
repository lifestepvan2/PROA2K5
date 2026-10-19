"""Accessory card test: patch candidate accessory bytes into the Falcons starters of the built payload and write the card.

  python scripts/acc_card_test.py        # patch + write card (PCSX2 closed!)
Restore the real roster afterwards with: python scripts/build_roster.py --card <card>
"""
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_roster import CARD_DIR, DEFAULT_CARD, PLAYER_BASE, PLAYER_STRIDE  # noqa: E402
from mc_write import write_file  # noqa: E402

CLEAR = {0x61: 255, 0x62: 0, 0x64: 255, 0x65: 255, 0x66: 255, 0x67: 255,
         0x75: 0, 0x76: 0, 0x77: 0, 0x78: 0, 0x79: 0, 0x7A: 0, 0x7E: 0, 0x7F: 0}
# Falcons records in roster order (starters first); round 2: one candidate byte per player, everything else cleared
RECORDS = [267, 268, 269, 270, 272, 273, 274, 275, 276, 277, 279, 80]
TESTS = [{0x78: 11}, {0x79: 7}, {0x7A: 7}, {0x7E: 14}, {0x7F: 14}, {0x61: 6},
         {0x62: 5}, {0x62: 2, 0x67: 0}, {0x77: 6}, {0x75: 3, 0x76: 3}, {0x7F: 6}, {}]

data = bytearray((ROOT / "data/roster_build/payload_proa.bin").read_bytes())
for rec, mods in zip(RECORDS, TESTS):
    base = PLAYER_BASE + rec * PLAYER_STRIDE
    for off, val in {**CLEAR, **mods}.items():
        if data[base + off] != val:
            print(f"rec {rec} +0x{off:02x}: {data[base + off]} -> {val}")
        data[base + off] = val
card = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CARD
write_file(card, CARD_DIR + "BESLES-53022Roster1", bytes(data))
write_file(card, CARD_DIR + "EXTRA", struct.pack("<I", zlib.crc32(bytes(data)) & 0xFFFFFFFF))
print("written to", card)
