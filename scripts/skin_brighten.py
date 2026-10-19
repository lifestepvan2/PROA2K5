"""Skin brightening for the ProA roster (the "light reserve").

The NBA face pool has far fewer light faces than the ProA roster has light players, and every face model (pid) may be used only
once (the lineup portrait is keyed by pid). So the models of one arm class are reserved and recoloured light:
  - arm textures are shared per skin class; the class with record tone byte 3 (about 63 pids) shares ONE arm texture. Its pixels
    are replaced by those of the light class (tone 5). Every user of that class gets it, hence the whole class is reserved.
  - legs follow the record byte +0x69, which build_roster.py sets to 5 for reserved pids.
  - face and neck of a reserved pid are recoloured per player to that player's skin lightness (gen_skin_replacements.py);
    only pids with a dumped face, a dumped neck that no other face shares and a dumped arm are usable.
Commands:
  python scripts/skin_brighten.py scan    pid -> dump keys of face/neck/arm + reserve flags -> data/texture_map/pid_skin_keys.csv
                                          (matches the RAM textures in data/face_match/faces against all dump folders by RGB)
  python scripts/skin_brighten.py embed   ArcFace embeddings of the recoloured reserved faces -> data/face_match/bright.npz
"""
import argparse
import collections
import csv
import hashlib
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from skimage import color

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from face_embed import TEX_CROP  # noqa: E402
from texlib import DUMP_DIRS  # noqa: E402

FACES = ROOT / "data/face_match/faces"
BRIGHT = ROOT / "data/face_match/bright.npz"
KEYS = ROOT / "data/texture_map/pid_skin_keys.csv"
FIELDS = ["pid", "tone", "reserved", "usable", "face_key", "neck_key", "arm_key"]
SIZES = {"face": (256, 256), "neck": (128, 64), "arm": (128, 128)}
RESERVED_TONE = 3  # record byte +0x69 of the reserved arm class
LIGHT_TONE = 5     # tone the reserved pids get (legs) and whose arm texture they receive
P_SKIN = 0x69
LIGHT_MIN, LIGHT_MAX = 1.2, 1.75  # lightness range (face_match scale, cheek L/100 on cv2's 0-255 scale) a brightened face can take
REF = 1.45                        # lightness the matcher assumes when it embeds a brightened face
SIGMA = (22, 10, 10)              # Lab distance scale of the skin mask


def lab_L(scale_value):
    """face_match lightness scale (cv2 L / 100) -> CIE L*."""
    return scale_value * 100 * 100 / 255


def skin_ab(L):
    """Typical a*, b* of an in-game face of lightness L* (linear fit over all 479 NBA face textures)."""
    return 0.1346 * L + 6.277, 0.1746 * L + 8.855


def target_lab(pl):
    L = lab_L(float(np.clip(pl, LIGHT_MIN, LIGHT_MAX)))
    return np.array([L, *skin_ab(L)])


def _md5(img):
    return hashlib.md5(np.asarray(img.convert("RGB")).tobytes()).hexdigest()


def _tones():
    out = {}
    for r in csv.DictReader(open(ROOT / "data/nba_defaults/players_unknown.csv", encoding="utf-8")):
        if r["team_slot"] and int(r["team_slot"]) < 39:
            b = bytes.fromhex(r["hex"])
            out.setdefault(int.from_bytes(b[4:6], "little"), b[P_SKIN])
    return out


def scan():
    idx = {p: collections.defaultdict(set) for p in SIZES}
    for d in DUMP_DIRS:
        for f in d.glob("*.png"):
            with Image.open(f) as im:
                for part, size in SIZES.items():
                    if im.size == size:
                        idx[part][_md5(im)].add(f.stem)
    tone, md5 = _tones(), {p: {} for p in SIZES}
    pids = sorted(int(f.name.split("_")[0]) for f in FACES.glob("*_face.png"))
    for pid in pids:
        for part in SIZES:
            f = FACES / f"{pid}_{part}.png"
            if f.exists():
                md5[part][pid] = _md5(Image.open(f))
    arm_class = collections.Counter(md5["arm"][p] for p in pids if tone.get(p) == RESERVED_TONE and p in md5["arm"]).most_common(1)[0][0]
    neck_faces = collections.defaultdict(set)  # a neck shared by several different faces cannot be recoloured per player
    for p in pids:
        if p in md5["neck"] and p in md5["face"]:
            neck_faces[md5["neck"][p]].add(md5["face"][p])
    rows = []
    for pid in pids:
        key = {part: ";".join(sorted(idx[part].get(md5[part].get(pid), ()))) for part in SIZES}
        reserved = md5["arm"].get(pid) == arm_class
        usable = reserved and all(key.values()) and len(neck_faces[md5["neck"][pid]]) == 1 and ";" not in key["face"]
        rows.append({"pid": pid, "tone": tone.get(pid, ""), "reserved": int(reserved), "usable": int(usable),
                     "face_key": key["face"], "neck_key": key["neck"], "arm_key": key["arm"]})
    with open(KEYS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    n = lambda k: sum(1 for r in rows if r[k])  # noqa: E731
    print(f"{len(rows)} pids; face key {n('face_key')}, neck key {n('neck_key')}, arm key {n('arm_key')}; "
          f"reserved {n('reserved')}, usable {n('usable')} -> {KEYS}")


def read_keys():
    if not KEYS.exists():
        return {}
    return {int(r["pid"]): r for r in csv.DictReader(open(KEYS, encoding="utf-8"))}


def reserved_pids():
    return {p for p, r in read_keys().items() if r["reserved"] == "1"}


def usable_pids():
    return {p for p, r in read_keys().items() if r["usable"] == "1"}


def _patch(lab, box):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    q = lab[y0 + int(.35 * h):y0 + int(.65 * h), x0 + int(.3 * w):x0 + int(.7 * w)]
    return np.median(q.reshape(-1, 3), axis=0)


def _shift(lab, src, delta):
    z = (lab - src) / np.array(SIGMA)
    w = np.clip(1.8 - np.sqrt((z ** 2).sum(-1)), 0, 1)  # 1 on skin, 0 on hair, brows, eyes
    w = cv2.GaussianBlur(w, (0, 0), 2.5)[..., None]    # smooth, or blotches appear where skin and shadow colours interleave
    out = lab + w * delta
    hi = out[..., 0] > 88
    out[..., 0] = np.where(hi, 88 + (out[..., 0] - 88) * 0.5, out[..., 0])
    return np.clip(color.lab2rgb(out), 0, 1)


def recolour(face_rgb, neck_rgb, pl):
    """Face (256x256) and neck (128x64) as uint8 RGB arrays shifted to the skin lightness `pl` (face_match scale).
    Both get the same Lab shift, applied only to skin-coloured pixels so that hair, brows, eyes and stubble stay dark."""
    fl = color.rgb2lab(np.asarray(face_rgb, float) / 255)
    src = _patch(fl, TEX_CROP)
    delta = target_lab(pl) - src
    face = _shift(fl, src, delta)
    nl = color.rgb2lab(np.asarray(neck_rgb, float) / 255)
    h, w = nl.shape[:2]
    neck = _shift(nl, _patch(nl, (0, 0, w, h)), delta)
    return (face * 255 + .5).astype(np.uint8), (neck * 255 + .5).astype(np.uint8)


def face_image(pid, pl):
    """Crop (TEX_CROP) of the face of `pid` as it looks once recoloured to lightness `pl`."""
    f = np.asarray(Image.open(FACES / f"{pid}_face.png").convert("RGB"))
    n = np.asarray(Image.open(FACES / f"{pid}_neck.png").convert("RGB"))
    return Image.fromarray(recolour(f, n, pl)[0]).crop(TEX_CROP)


def embed_all():
    from face_embed import embed
    out, miss = {}, []
    for pid in sorted(usable_pids()):
        res = embed(face_image(pid, REF), 3)
        if res is None:
            miss.append(pid)
        else:
            out[f"emb:{pid}"], out[f"lab:{pid}"] = res
    np.savez(BRIGHT, **out)
    print(len(out) // 2, "brightened faces embedded;", len(miss), "without a detected face:", miss)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["scan", "embed"])
    {"scan": scan, "embed": embed_all}[ap.parse_args().cmd]()
