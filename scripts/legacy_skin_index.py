"""Read-only historical light-reserve key inventory for migration audits."""
import collections
import csv
from pathlib import Path

import skin_brighten as sb
from skin_tones import tone_value

ROOT = Path(__file__).parent.parent
MAP = ROOT / "data/face_match/proa_pid_map.csv"


def used_reserved():
    """[(player row, pid, skin target)] of the ProA players wearing a recolourable reserved face (override_pid wins)."""
    usable = sb.usable_pids()
    out = []
    for r in csv.DictReader(open(MAP, encoding="utf-8-sig")):
        pid = int(r["override_pid"] or r["pid"])
        if pid in usable and not tone_value(r):
            out.append((r, pid, float(r["skin_target"])))
    return out


def light_arm_key():
    """Dump key of the arm texture shared by the light class (the one most pids of the light tone use)."""
    c = collections.Counter(r["arm_key"] for r in sb.read_keys().values() if r["tone"] == str(sb.LIGHT_TONE) and r["arm_key"])
    return c.most_common(1)[0][0].split(";")[0]


def plan():
    """{key: ("face"|"neck", pid, target) or ("arm", None, None)} of all textures this generator writes."""
    keys, users = sb.read_keys(), used_reserved()
    out = {}
    for _, pid, tgt in users:
        for part in ("face", "neck"):
            for k in keys[pid][f"{part}_key"].split(";"):
                out[k] = (part, pid, tgt)
    if users:
        for k in {k for r in keys.values() if r["reserved"] == "1" for k in r["arm_key"].split(";") if k}:
            out[k] = ("arm", None, None)
    return out


def managed_keys():
    return set(plan()) if sb.KEYS.exists() and MAP.exists() else set()
