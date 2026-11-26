"""Read-only helpers for inspecting and migrating historical texture artwork."""
import csv
import hashlib
import json
import re
from pathlib import Path

from PIL import Image

import legacy_logo_index as logos
import legacy_portrait_index as faces
import legacy_skin_index as skins
import texcluster
import uniform_labels
from texlib import ROOT, dump_files, family
from uniform_lods import skipped

DEFAULT_WS = ROOT / "texture_workspace"
EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp"}
TOKEN = re.compile(r"__([0-9a-f]{8})(?:\W|$)")

# family -> group for families that are homogeneous
FAMILY_GROUPS = {
    "00001994": "loading_video_tiles", "00002a9b": "crowd_and_referee_sprites",
    "00000d93": "jersey_name_plates", "000011d3": "jersey_name_plates", "00001613": "jersey_name_plates",
    "000015d3": "jersey_name_plates", "00002253": "uniforms", "00002254": "uniforms",
    "00001e13": "uniform_parts", "00001e14": "uniform_parts", "00001e53": "uniform_parts",
    "00001553": "team_icons_small", "00001554": "team_icons_small",
}
SIZE_SUBFOLDER = {"jersey_numbers", "uniforms", "uniform_parts", "jersey_name_plates", "ui_fragments", "other_logos",
                  "head_and_body_skin"}


def token(key):
    return hashlib.sha1(key.encode()).hexdigest()[:8]


def safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")


def sha1(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def managed_keys():
    out = {k: "faces/icons" for k in faces.managed_keys()}
    out.update({k: "team logo" for k in logos.managed_keys()})
    out.update({k: "light-reserve skin" for k in skins.managed_keys()})
    return out


def load_labels():
    """data/texture_labels/labels.csv (key,label,group,sub,...): team label prefix and optional group/sub override per dump key."""
    p = ROOT / "data/texture_labels/labels.csv"
    return {r["key"]: r for r in csv.DictReader(open(p, encoding="utf-8"))} if p.exists() else {}


def catalog(files=None, ws=None):
    """One dict per dump: key, family, w, h, group, sub, label. Known maps first, then family rules, then clusters."""
    files = files or dump_files()
    ws = ws or DEFAULT_WS
    names = {}
    for r in csv.DictReader(open(ROOT / "data/nba_defaults/players_unknown.csv", encoding="utf-8")):
        names[int(r["record"])] = (r["team"], f"{r['first']}_{r['last']}")
    face_of = {}
    for r in csv.DictReader(open(ROOT / "data/texture_map/record_faces.csv")):
        face_of.setdefault(r["key"], int(r["record"]))
    logo_of, sign_of = {}, {}
    for r in logos.logo_matches():
        if r["key"] not in logo_of or float(r["score"]) > float(logo_of[r["key"]]["score"]):
            logo_of[r["key"]] = r
    for r in csv.DictReader(open(logos.SRC, encoding="utf-8")):
        if r["mode"] == "B" and float(r["score"]) >= 0.8:
            sign_of[r["key"]] = r["team"]
    model = json.loads(texcluster.MODEL.read_text())
    cnames = json.loads(texcluster.NAMES.read_text())
    labels = load_labels()
    out = []
    for key, path in sorted(files.items()):
        fam = family(key)
        with Image.open(path) as im:
            w, h = im.size
        group, sub, label = None, "", None
        if key in face_of:
            team, nm = names.get(face_of[key], ("unknown", f"record{face_of[key]}"))
            group, sub, label = "player_faces", team, nm
        elif fam in ("00001dd3", "00001dd4"):
            group, sub, label = "player_faces", "_unmapped", "face"
        elif key in logo_of:
            team = logo_of[key]["team"]
            group, sub, label = "team_logos", team, f"{team}_logo"
        elif fam in FAMILY_GROUPS:
            group = FAMILY_GROUPS[fam]
        elif fam in model:
            group = cnames[fam][texcluster.classify(texcluster.feature(path), fam, model)]
        else:
            group = "ui_fragments"
        lab = labels.get(key, {})
        if lab.get("group"):
            group, sub = lab["group"], lab.get("sub", "")
        if group in SIZE_SUBFOLDER and not (lab.get("group") and lab.get("sub")):
            sub = f"{w}x{h}"
        label = label or f"{group}_{w}x{h}"
        if lab.get("label"):
            label = f"{lab['label']}_{label}"
        if key in sign_of and not lab.get("label"):
            label += f"_has-{sign_of[key]}-logo"
        out.append(dict(key=key, family=fam, w=w, h=h, group=group, sub=sub, label=safe(label)))
    return mark_uniform_roles(out, ws)


def mark_uniform_roles(rows, ws):
    """Uniform role files keep their identity, with clearly labelled teams grouped into subfolders."""
    mp = uniform_labels.load_mapping(ws)
    for r in rows:
        m = mp.get(r["key"])
        if m:
            r["group"], r["sub"] = "uniforms", uniform_labels.team_folder(m["label"]) or ""
            r["label"] = f"{m['role'].upper()}__{m['label']}__{m['size']}"
    return rows


def rel_path(row):
    parts = [row["group"]] + ([row["sub"]] if row["sub"] else [])
    return Path(*parts) / f"{row['label']}__{token(row['key'])}.png"


def scan(ws):
    """token -> newest file in the working folder."""
    found = {}
    for p in ws.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS and not skipped(p.relative_to(ws).parts[:-1]):
            m = TOKEN.search(p.stem + " ")
            if m:
                previous = found.get(m.group(1))
                if previous is not None:
                    keep, drop = (p, previous) if p.stat().st_mtime > previous.stat().st_mtime else (previous, p)
                    print(f"warning: duplicate workspace ID {m.group(1)}: using {keep}, ignoring {drop}")
                    found[m.group(1)] = keep
                else:
                    found[m.group(1)] = p
    return found


def read_manifest(ws):
    mf = ws / "_manifest.csv"
    if not mf.exists():
        return {}
    with mf.open(encoding="utf-8", newline="") as file:
        return {r["token"]: r for r in csv.DictReader(file)}
