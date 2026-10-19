"""Write the PCSX2 texture replacements of the light reserve (see skin_brighten.py).

  - face + neck of every reserved pid that a ProA player wears are recoloured to that player's skin lightness (the
    `skin_target` column of data/face_match/proa_pid_map.csv),
  - the arm texture of the reserved class gets the pixels of the light class' arm (only when a reserved pid is in use).
Replacement alpha is taken over from the dumps (PS2 alpha, 0..128).
Usage: python scripts/gen_skin_replacements.py [--out DIR] [--list]
"""
import argparse
import collections
import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import skin_brighten as sb  # noqa: E402
from texlib import REPL_DIR, dump_files, prune  # noqa: E402

ROOT = Path(__file__).parent.parent
MAP = ROOT / "data/face_match/proa_pid_map.csv"


def used_reserved():
    """[(player row, pid, skin target)] of the ProA players wearing a recolourable reserved face (override_pid wins)."""
    usable = sb.usable_pids()
    out = []
    for r in csv.DictReader(open(MAP, encoding="utf-8-sig")):
        pid = int(r["override_pid"] or r["pid"])
        if pid in usable:
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


def save(rgb, key, files, out):
    alpha = np.asarray(Image.open(files[key]).convert("RGBA"))[..., 3:]
    Image.fromarray(np.concatenate([rgb, alpha], axis=-1), "RGBA").save(out / f"{key}.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=REPL_DIR)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    keys, files, wanted = sb.read_keys(), dump_files(), plan()
    if args.list:
        for k, v in wanted.items():
            print(k, v)
        return
    args.out.mkdir(parents=True, exist_ok=True)
    written = []
    for r, pid, tgt in used_reserved():
        face = np.asarray(Image.open(sb.FACES / f"{pid}_face.png").convert("RGB"))
        neck = np.asarray(Image.open(sb.FACES / f"{pid}_neck.png").convert("RGB"))
        nf, nn = sb.recolour(face, neck, tgt)
        for part, rgb in (("face", nf), ("neck", nn)):
            for k in keys[pid][f"{part}_key"].split(";"):
                save(rgb, k, files, args.out)
                written.append(k)
    if any(v[0] == "arm" for v in wanted.values()):
        light = np.asarray(Image.open(files[light_arm_key()]).convert("RGB"))
        for k, v in wanted.items():
            if v[0] == "arm":
                save(light, k, files, args.out)
                written.append(k)
    n = sum(1 for v in wanted.values() if v[0] == "face")
    print(f"{n} recoloured faces (+necks), {sum(1 for v in wanted.values() if v[0] == 'arm')} arm texture(s) written to {args.out}")
    print(prune("skin", args.out, written), "stale files removed")


if __name__ == "__main__":
    main()
