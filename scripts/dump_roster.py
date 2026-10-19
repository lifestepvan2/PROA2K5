"""Build a throw-away roster whose starting fives are the NBA player models that PCSX2 has not dumped yet.

PCSX2 dumps a texture the first time it is drawn, so every pid whose face/neck/arm key is missing in
data/texture_map/pid_skin_keys.csv has to be on court once. The starters (first five records) of each of the 18 teams are
given the missing pids through a temporary pid map, so 9 games (two teams each) cover up to 90 pids. The normal roster
(data/roster_build) is not touched; the payload goes to data/roster_dump and can be written with --card (PCSX2 closed!).
Afterwards: skin_brighten.py scan, embed, face_match.py --rematch, build_roster.py --card (real roster again).
Usage: python scripts/dump_roster.py [--card MCD] [--missing-only face|any]
"""
import argparse
import csv
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data/roster_dump"


def missing_pids(any_part=True):
    rows = list(csv.DictReader(open(ROOT / "data/texture_map/pid_skin_keys.csv", encoding="utf-8")))
    keys = ("face_key", "neck_key", "arm_key") if any_part else ("face_key",)
    return [int(r["pid"]) for r in rows if not all(r[k] for k in keys)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", help="write the dump roster into this memory card (PCSX2 closed!)")
    ap.add_argument("--face-only", action="store_true", help="only pids without a face dump (ignore neck/arm)")
    a = ap.parse_args()

    todo = missing_pids(not a.face_only)
    players = list(csv.DictReader(open(ROOT / "data/roster_build/player_map.csv", encoding="utf-8")))
    starters = [p for p in players if p["starter"] == "True"]
    if len(todo) > len(starters):
        print(f"warning: {len(todo) - len(starters)} pids do not fit into the starting fives; run again after this round")
    todo_iter = iter(todo)

    OUT.mkdir(exist_ok=True)
    pid_rows = list(csv.DictReader(open(ROOT / "data/face_match/proa_pid_map.csv", encoding="utf-8-sig")))
    by_id = {r["proa_id"]: r for r in pid_rows}
    assigned = {}
    for p in starters:
        pid = next(todo_iter, None)
        if pid is None:
            break
        by_id[p["proa_id"]]["override_pid"] = str(pid)
        assigned[p["proa_id"]] = pid
    tmp_map = OUT / "pid_map_dump.csv"
    with open(tmp_map, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(pid_rows[0].keys()))
        w.writeheader()
        w.writerows(pid_rows)
    shutil.copy(ROOT / "data/accessories.csv", OUT / "accessories_copy.csv")

    cmd = [sys.executable, str(ROOT / "scripts/build_roster.py"), "--pids", str(tmp_map), "--out", str(OUT),
           "--accessories", str(OUT / "accessories_copy.csv")]
    if a.card:
        cmd += ["--card", a.card]
    subprocess.run(cmd, check=True)

    # matchups: teams paired in slot order, listing the dumped pids per side
    built = list(csv.DictReader(open(OUT / "player_map.csv", encoding="utf-8")))
    teams = {int(r["slot"]): r for r in csv.DictReader(open(OUT / "team_map.csv", encoding="utf-8"))}
    slots = sorted(teams)
    lines = ["# Texture dump matchups", "",
             f"{len(todo)} pids still lack a face/neck/arm dump; {len(assigned)} are on court in the first five of each team.", "",
             "| Game | Team A | Team B | Pids on court |", "|---|---|---|---|"]
    for g, (s1, s2) in enumerate(zip(slots[0::2], slots[1::2]), 1):
        pids = [f"{p['pid']}" for p in built if int(p["team_slot"]) in (s1, s2) and p["starter"] == "True" and p["proa_id"] in assigned]
        name = lambda s: f"{teams[s]['city']} {teams[s]['nick']} (slot {s})"
        lines.append(f"| {g} | {name(s1)} | {name(s2)} | {len(pids)}: {', '.join(pids)} |")
    (OUT / "matchups.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
