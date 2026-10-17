"""Automated capture: cycle teams in Team Select, open Start Game, save a screenshot per team.

Prerequisite: PCSX2 maximised/foreground, a savestate (slot 1, F3) taken at Team Select with the ProA
roster loaded (left = slot 15, right = slot 9), and the dumps folder in use. Each iteration loads the
state, moves the pad to the right team slot, presses R1 (k > 0) or L1 (k < 0) |k| times and confirms.
Right-side team slot = 9 + k for k -9..8 (the cycle wraps through the NBA teams after that).
Output: docs/_scans/k<k>.png  -> match with build_texture_map.py
Usage: python scripts/texture_scan_run.py K [K2 ...]
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
SHOTS = ROOT / "docs/_scans"
TMP = "docs/_scan.png"


def press(*buttons, wait=0.8):
    for b in buttons:
        subprocess.run([sys.executable, str(ROOT / "scripts/pcsx2_controller.py"), b], capture_output=True)
        time.sleep(wait)


def scan(k):
    press("f3", wait=9)
    press("right")
    press(*(["r1"] * k if k >= 0 else ["l1"] * -k), wait=0.8)
    press("cross", wait=20)
    subprocess.run([sys.executable, str(ROOT / "scripts/pcsx2_capture.py"), "--out", TMP], capture_output=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / TMP, SHOTS / f"k{k}.png")
    print("saved", f"k{k}.png", flush=True)


if __name__ == "__main__":
    for k in map(int, sys.argv[1:]):
        scan(k)
