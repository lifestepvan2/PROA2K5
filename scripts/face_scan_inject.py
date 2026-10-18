"""Scan player faces by record index without browsing: write arbitrary player records into the two
teams' starter pointers (live RAM, via PINE) and screenshot the Start Game screen (10 faces per scan).

Prerequisite: PCSX2 running (-batch) with savestate slot 1 taken at Team Select (left slot 15, right slot 9).
Each scan: F3, wait, patch starters of team 15 (row 0) and team 9 (row 1), pad right, Cross, wait, capture.
Output: docs/_faces/b<first_record>.png and data/texture_map/face_scan_batches.csv (batch -> records).
Usage: python scripts/face_scan_inject.py START STOP   (record range, STOP exclusive)
"""
import csv
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fast_scan import write_ps2_ram  # noqa: E402

PAYLOAD = 0xA95B80
PLAYER_BASE, PLAYER_STRIDE = PAYLOAD + 0x64F4, 0x94
TEAM_BASE, TEAM_STRIDE, T_STARTERS = PAYLOAD + 0x11F0, 0x124, 0x90
LEFT_TEAM, RIGHT_TEAM = 15, 9
OUT = ROOT / "docs/_faces"
TMP = "docs/_scan.png"


def press(b, wait=1.0):
    subprocess.run([sys.executable, str(ROOT / "scripts/pcsx2_controller.py"), b], capture_output=True)
    time.sleep(wait)


def set_starters(team, records):
    ptrs = [PLAYER_BASE + r * PLAYER_STRIDE for r in records]
    write_ps2_ram(TEAM_BASE + team * TEAM_STRIDE + T_STARTERS, struct.pack("<5I", *ptrs))


def scan(records):
    """records: 10 record indices (row 0 = left team, row 1 = right team)."""
    press("f3", 9)
    set_starters(LEFT_TEAM, records[:5])
    set_starters(RIGHT_TEAM, records[5:])
    press("right")
    press("cross", 20)
    subprocess.run([sys.executable, str(ROOT / "scripts/pcsx2_capture.py"), "--out", TMP], capture_output=True)
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / TMP, OUT / f"b{records[0]}.png")


if __name__ == "__main__":
    start, stop = int(sys.argv[1]), int(sys.argv[2])
    log = ROOT / "data/texture_map/face_scan_batches.csv"
    new = not log.exists()
    with open(log, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["file"] + [f"r{i}" for i in range(10)])
        for r in range(start, stop, 10):
            recs = [min(r + i, 791) for i in range(10)]
            scan(recs)
            w.writerow([f"b{r}.png"] + recs)
            f.flush()
            print("scanned", r, flush=True)
