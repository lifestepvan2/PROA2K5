"""Load arbitrary players into a live game and record which face/arm/neck textures the game attaches to each pid.

Prerequisite: PCSX2 running with a savestate in slot 2 taken at the Team Select screen (home = team slot 28,
away = team slot 16), with the 'player_id' stamp probe optional. Per batch this script loads slot 2, writes 12
roster pointers + 5 starters into both team structs, then presses START (Start Game) and CROSS (begin game). Once
the game has loaded, the player file objects 'p<ID>h/a.iff' are read back from RAM by live_players.
Usage: python scripts/face_load_scan.py [--all | --limit N]
"""
import csv
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fast_scan import read_ps2_ram, write_ps2_ram  # noqa: E402
import live_players  # noqa: E402

PAYLOAD = 0xA95B80
PLAYER_BASE, PLAYER_STRIDE = PAYLOAD + 0x64F4, 0x94
TEAM_BASE, TEAM_STRIDE, T_STARTERS = PAYLOAD + 0x11F0, 0x124, 0x90
HOME_TEAM, AWAY_TEAM = 28, 16
PID_CSV = ROOT / "data/texture_map/pid_textures.csv"


def press(b, wait=1.0):
    subprocess.run([sys.executable, str(ROOT / "scripts/pcsx2_controller.py"), b], capture_output=True)
    time.sleep(wait)


def set_roster(team, records):
    ptrs = [PLAYER_BASE + r * PLAYER_STRIDE for r in records]
    base = TEAM_BASE + team * TEAM_STRIDE
    write_ps2_ram(base, struct.pack("<12I", *ptrs))
    write_ps2_ram(base + T_STARTERS, struct.pack("<5I", *ptrs[:5]))


def pid_of(ram, rec):
    return struct.unpack_from("<H", ram, PLAYER_BASE + rec * PLAYER_STRIDE + 4)[0]


def load_batch(records, timeout=150, settle=60):
    """records: 24 record indices (12 home, 12 away). Returns {pid: {...}} read back from RAM."""
    press("f3", 8)
    # starters (first 5 of each roster) are the players on court at tip-off and are reliably drawn
    home = records[:5] + records[10:17]
    away = records[5:10] + records[17:24]
    set_roster(HOME_TEAM, home)
    set_roster(AWAY_TEAM, away)
    press("start", 4)
    press("cross", 1)
    ram = read_ps2_ram()
    want = {pid_of(ram, r) for r in records}
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(6)
        ram = read_ps2_ram()
        got = {p for p, *_ in live_players.live_players(ram)}
        if want <= got:
            time.sleep(settle)
            return live_players.collect(read_ps2_ram()), want, got
    return live_players.collect(ram), want, {p for p, *_ in live_players.live_players(ram)}


def todo_records(retry_incomplete=False):
    """One record per ProA player whose pid has no texture row yet (or, with retry_incomplete, no face/neck key)."""
    have = {}
    if PID_CSV.exists():
        have = {int(r["pid"]): r for r in csv.DictReader(open(PID_CSV))}
    ram = read_ps2_ram()
    out = []
    for r in csv.DictReader(open(ROOT / "data/roster_build/player_map.csv", encoding="utf-8")):
        rec = int(r["record"])
        row = have.get(pid_of(ram, rec))
        if row is None or (retry_incomplete and not (row["face"] and row["neck"])):
            out.append(rec)
    return out


if __name__ == "__main__":
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10 ** 9
    for n in range(limit):
        retry = "--retry" in sys.argv
        recs = todo_records(retry)
        if not recs:
            print("all ProA pids mapped")
            break
        batch = recs[:10 if retry else 24]
        batch += [r for r in range(150, 792) if r not in batch][:24 - len(batch)]
        found, want, got = load_batch(batch)
        total = live_players.merge_csv(found)
        print(f"batch {n}: {len(recs)} records left; wanted {len(want)}, loaded {len(want & got)}; {total} pids stored")
