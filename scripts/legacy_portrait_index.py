"""Read-only historical portrait and icon key inventory for migration audits."""
import csv
from pathlib import Path

from texlib import proa_slots

ROOT = Path(__file__).parent.parent


def icon_rows():
    """(key, ProA team index) of the team icons that belong to NBA slots occupied by ProA teams."""
    slots = proa_slots()
    return [(r["key"], slots[int(r["nba_slot"])]) for r in csv.DictReader(open(ROOT / "data/texture_map/team_icons.csv", encoding="utf-8"))
            if int(r["nba_slot"]) in slots]




def pid_keys():
    """{pid: [lineup portrait keys]}. The portrait follows the player model: it is the one of the NBA record(s) that
    originally had that pid (players_unknown.csv), not the one of the record the pid is now written to."""
    rec_key = {int(r["record"]): r["key"] for r in csv.DictReader(open(ROOT / "data/texture_map/record_faces.csv"))}
    out = {}
    for r in csv.DictReader(open(ROOT / "data/nba_defaults/players_unknown.csv", encoding="utf-8")):
        k = rec_key.get(int(r["record"]))
        pid = int.from_bytes(bytes.fromhex(r["hex"])[4:6], "little")
        if k and k not in out.setdefault(pid, []):
            out[pid].append(k)
    return out


def face_keys():
    """[(player_map row, [portrait keys])] for the current roster build, best overall first. A pid used by several players
    can show only one portrait: the first (best) player keeps it, the others are listed in the returned conflicts."""
    keys = pid_keys()
    pm = sorted(csv.DictReader(open(ROOT / "data/roster_build/player_map.csv", encoding="utf-8")), key=lambda r: -float(r["ovr"]))
    rows, owner, conflicts = [], {}, []
    for r in pm:
        pid = int(r["pid"])
        if pid in owner:
            conflicts.append((r, owner[pid]))
            continue
        owner[pid] = r
        rows.append((r, keys[pid]))
    return rows, conflicts


def managed_keys():
    """Keys historically managed by the portrait and icon pipeline."""
    return {k for _, ks in face_keys()[0] for k in ks} | {k for k, _ in icon_rows()}
