"""Round trip between a versioned roster payload (data/roster.bin) and the PCSX2 memory card.

    python scripts/card_patch.py                  # data/roster.bin -> card (CRC32 into EXTRA, ECC, backup, verify)
    python scripts/card_patch.py --pull           # card -> data/roster.bin (starting point for hex editing)
    python scripts/card_patch.py --from-build     # data/roster_build/payload_proa.bin (build_roster.py) -> data/roster.bin
    python scripts/card_patch.py --diff           # what differs between data/roster.bin and the card's payload
    options: --bin FILE  --card FILE  --dry  --no-backup  --force (skip the "PCSX2 is running" check)

Workflow: keep data/roster.bin in git, edit it with a hex editor for experiments, run this script with PCSX2 closed, start the game
from the card. `git diff --stat` / `--diff` show what an experiment changed. The size is fixed (0xB1040); the card file is rewritten
in place, so only edits that keep the size are possible. Layout: docs/roster_payload_format.md.
"""
import argparse
import shutil
import struct
import subprocess
import sys
import zlib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from mc_inspect import Card  # noqa: E402
from mc_write import find_entry, verify_card, write_file  # noqa: E402

CARD_DIR = "/BESLES-53022Roster1/"
PAYLOAD_PATH, EXTRA_PATH = CARD_DIR + "BESLES-53022Roster1", CARD_DIR + "EXTRA"
PAYLOAD_SIZE = 0xB1040
DEFAULT_CARD = r"C:\Users\Sebastian\Documents\PCSX2\memcards\Mcd001.ps2"
DEFAULT_BIN = ROOT / "data" / "roster.bin"
BUILD_BIN = ROOT / "data" / "roster_build" / "payload_proa.bin"
BACKUP_DIR = ROOT / "data" / "roster_test"
PLAYER_BASE, PLAYER_STRIDE, PLAYER_COUNT = 0x64F4, 0x94, 0x318
TEAM_BASE, TEAM_STRIDE, TEAM_COUNT = 0x11F0, 0x124, 54
POOL_MIN = 0x675DC


def read_card_file(card_path, file_path):
    card = Card(card_path)
    e = find_entry(card, file_path)
    return card.read_chain(e["cluster"], e["length"])


def crc_bytes(data):
    return struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF)


def pcsx2_running():
    out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    return "pcsx2" in out


def region(off):
    if PLAYER_BASE <= off < PLAYER_BASE + PLAYER_STRIDE * PLAYER_COUNT:
        i, f = divmod(off - PLAYER_BASE, PLAYER_STRIDE)
        return f"player record {i} +0x{f:X}"
    if TEAM_BASE <= off < TEAM_BASE + TEAM_STRIDE * TEAM_COUNT:
        i, f = divmod(off - TEAM_BASE, TEAM_STRIDE)
        return f"team record {i} +0x{f:X}"
    return "string pool" if off >= POOL_MIN else "other"


def print_diff(a, b, label_a, label_b, limit=200):
    ranges, i, n = [], 0, min(len(a), len(b))
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            ranges.append((i, j))
            i = j
        else:
            i += 1
    print(f"{len(ranges)} differing range(s) between {label_a} and {label_b}"
          f"{'' if len(a) == len(b) else f' (sizes {len(a)} vs {len(b)})'}")
    for s, e in ranges[:limit]:
        print(f"  0x{s:06X}-0x{e - 1:06X} ({e - s:>4} B)  {region(s)}  {a[s:min(e, s + 8)].hex()} -> {b[s:min(e, s + 8)].hex()}")
    if len(ranges) > limit:
        print(f"  ... {len(ranges) - limit} more")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bin", default=str(DEFAULT_BIN), help="roster payload file (default: data/roster.bin)")
    ap.add_argument("--card", default=DEFAULT_CARD)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--pull", action="store_true", help="card -> roster.bin")
    mode.add_argument("--from-build", action="store_true", help="build_roster.py output -> roster.bin")
    mode.add_argument("--diff", action="store_true", help="compare roster.bin with the card's payload")
    ap.add_argument("--dry", action="store_true", help="check everything, write nothing")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--force", action="store_true", help="do not refuse to write while PCSX2 is running")
    a = ap.parse_args()
    binf = Path(a.bin)

    if a.from_build:
        data = BUILD_BIN.read_bytes()
        assert len(data) == PAYLOAD_SIZE, f"{BUILD_BIN}: {len(data)} bytes"
        if not a.dry:
            binf.write_bytes(data)
        print(f"{BUILD_BIN} -> {binf} (CRC32 {crc_bytes(data)[::-1].hex()})")
        return

    if a.pull or a.diff:
        data = read_card_file(a.card, PAYLOAD_PATH)
        if a.diff:
            print_diff(binf.read_bytes(), data, binf.name, "card")
            return
        if not a.dry:
            binf.write_bytes(data)
        print(f"card -> {binf} ({len(data)} bytes, CRC32 {crc_bytes(data)[::-1].hex()})")
        return

    data = binf.read_bytes()
    if len(data) != PAYLOAD_SIZE:
        sys.exit(f"ERROR: {binf} is {len(data)} bytes, expected {PAYLOAD_SIZE} (0x{PAYLOAD_SIZE:X}); the card file is rewritten in place")
    if not a.dry and not a.force and pcsx2_running():
        sys.exit("ERROR: PCSX2 is running (it would overwrite the card on exit); close it or use --force")
    crc = crc_bytes(data)
    ok0, bad0 = verify_card(a.card)
    if a.dry:
        print(f"dry run: would write {binf} (CRC32 {crc[::-1].hex()}) to {a.card}; card ECC now {ok0} ok / {bad0} bad")
        return
    if not a.no_backup:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup = BACKUP_DIR / f"Mcd001.{datetime.now():%Y%m%d_%H%M%S}.ps2"
        shutil.copy2(a.card, backup)
        print("backup:", backup)
    write_file(a.card, PAYLOAD_PATH, data)
    write_file(a.card, EXTRA_PATH, crc)
    ok, bad = verify_card(a.card)
    back = read_card_file(a.card, PAYLOAD_PATH)
    assert back == data and read_card_file(a.card, EXTRA_PATH) == crc, "read-back mismatch"
    print(f"written {binf} -> {a.card}: CRC32 {crc[::-1].hex()}, ECC {ok} ok / {bad} bad (was {bad0} bad), read-back identical")


if __name__ == "__main__":
    main()
