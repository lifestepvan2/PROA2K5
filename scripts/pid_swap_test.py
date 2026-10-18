"""Test: does overwriting a record's pid (u16 at +4/+6) make the game load a different player model (.iff)?
Usage: python scripts/pid_swap_test.py HOME_REC:NEWPID AWAY_REC:NEWPID ...  (needs the Team Select savestate in slot 2)
"""
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import face_load_scan as F  # noqa: E402
import live_players  # noqa: E402
from fast_scan import read_ps2_ram, write_ps2_ram  # noqa: E402

swaps = [tuple(int(x) for x in a.split(":")) for a in sys.argv[1:]]
home = list(range(150, 162))
away = list(range(162, 174))
F.press("f3", 8)
ram = read_ps2_ram()
orig = {}
for rec, pid in swaps:
    a = F.PLAYER_BASE + rec * F.PLAYER_STRIDE
    orig[rec] = F.pid_of(ram, rec)
    write_ps2_ram(a + 4, struct.pack("<HH", pid, pid))
F.set_roster(F.HOME_TEAM, home)
F.set_roster(F.AWAY_TEAM, away)
F.press("start", 4)
F.press("cross", 1)
time.sleep(90)
ram = read_ps2_ram()
got = {(p, s): t for p, s, a, t in live_players.live_players(ram)}
print("orig pids", orig)
print("loaded", sorted(got))
for rec, pid in swaps:
    print(rec, "new pid", pid, "loaded:", any(p == pid for p, _ in got), "| old pid still loaded:", any(p == orig[rec] for p, _ in got))
