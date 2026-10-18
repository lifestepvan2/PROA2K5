"""Manual texture replacement workspace: a mirror of the PCSX2 dump folder, grouped into named folders.

    python scripts/texture_workspace.py export [--ws DIR]   build / update the working folder from the dumps
    python scripts/texture_workspace.py sync   [--ws DIR]   copy edited files back to PCSX2's replacements\\ folder
    python scripts/texture_workspace.py sync --dry-run      only list what would change

Workflow: export -> overwrite files in the working folder with your own images (any size, any of png/jpg/bmp/tga/webp,
keep the "__xxxxxxxx" token in the file name; folders may be reorganised freely) -> sync -> press F10 in PCSX2.
Sync resizes to the original resolution. Restoring a file to its exported content (or exporting it again) reverts it.
Textures the pipeline replaces itself (ProA faces, team icons, team logo variants) are never exported and always win.
Alpha: files are exported with normal 0..255 alpha (PS2 0..128 is converted back on sync). Images without an alpha
channel keep the original's transparency.
"""
import argparse
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

import gen_logo_replacements as logos
import gen_replacements as faces
import texcluster
from texlib import REPL_DIR, ROOT, dump_files, family, load_rgba

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


def managed_keys():
    out = {k: "faces/icons" for k in faces.managed_keys()}
    out.update({k: "team logo" for k in logos.managed_keys()})
    return out


def catalog(files=None):
    """One dict per dump: key, family, w, h, group, sub, label. Known maps first, then family rules, then clusters."""
    files = files or dump_files()
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
        if group in SIZE_SUBFOLDER:
            sub = f"{w}x{h}"
        label = label or f"{group}_{w}x{h}"
        if key in sign_of:
            label += f"_has-{sign_of[key]}-logo"
        out.append(dict(key=key, family=fam, w=w, h=h, group=group, sub=sub, label=safe(label)))
    return out


def rel_path(row):
    parts = [row["group"]] + ([row["sub"]] if row["sub"] else [])
    return Path(*parts) / f"{row['label']}__{token(row['key'])}.png"


def scan(ws):
    """token -> newest file in the working folder."""
    found = {}
    for p in ws.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS:
            m = TOKEN.search(p.stem + " ")
            if m and (m.group(1) not in found or p.stat().st_mtime > found[m.group(1)].stat().st_mtime):
                found[m.group(1)] = p
    return found


def read_manifest(ws):
    mf = ws / "_manifest.csv"
    return {r["token"]: r for r in csv.DictReader(open(mf, encoding="utf-8"))} if mf.exists() else {}


def export(ws):
    ws.mkdir(parents=True, exist_ok=True)
    files = dump_files()
    managed = managed_keys()
    rows = [r for r in catalog(files)]
    toks = [token(r["key"]) for r in rows]
    assert len(set(toks)) == len(toks), "token collision"
    old, found = read_manifest(ws), scan(ws)
    new, added, moved, dropped, kept = {}, 0, 0, 0, 0
    for r in rows:
        t = token(r["key"])
        if r["key"] in managed:
            p = found.get(t)
            if p and t in old and sha1(p) == old[t]["sha1"]:
                p.unlink()
                dropped += 1
            continue
        want = rel_path(r)
        p = found.get(t)
        if p is not None and t in old:
            osha = old[t]["sha1"]
            if p == ws / old[t]["relpath"] and p != ws / want and sha1(p) == osha:
                (ws / want).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(p, ws / want)
                p, moved = ws / want, moved + 1
            new[t] = dict(old[t], relpath=str(p.relative_to(ws)), group=r["group"])
            kept += 1
            continue
        (ws / want).parent.mkdir(parents=True, exist_ok=True)
        a = load_rgba(files[r["key"]]).copy()
        a[..., 3] = np.minimum(255, np.round(a[..., 3].astype(np.float32) * 255 / 128)).astype(np.uint8)
        Image.fromarray(a, "RGBA").save(ws / want)
        new[t] = dict(token=t, key=r["key"], group=r["group"], relpath=str(want), w=r["w"], h=r["h"],
                      sha1=sha1(ws / want))
        added += 1
    with open(ws / "_manifest.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, ["token", "key", "group", "relpath", "w", "h", "sha1"])
        wr.writeheader()
        wr.writerows(new.values())
    print(f"export: {added} new, {kept} existing, {moved} regrouped, {dropped} removed (now pipeline-managed) -> {ws}")
    for g in sorted({v["group"] for v in new.values()}):
        print(f"  {g}: {sum(v['group'] == g for v in new.values())}")


def fit_resize(path, size, mode):
    """Returns (RGBA image at `size`, user image had an alpha channel)."""
    im = Image.open(path)
    has_alpha = im.mode in ("RGBA", "LA", "PA", "RGBa") or "transparency" in im.info
    im = im.convert("RGBA")
    if not has_alpha:
        im.putalpha(255)
    tw, th = size
    if mode == "stretch":
        return im.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA"), has_alpha
    s = (min if mode == "contain" else max)(tw / im.width, th / im.height)
    r = im.convert("RGBa").resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    r = r.convert("RGBA")
    pad = (255, 255, 255, 255) if not has_alpha else (0, 0, 0, 0)
    canvas = Image.new("RGBA", size, pad)
    canvas.alpha_composite(r.crop((max(0, (r.width - tw) // 2), max(0, (r.height - th) // 2),
                                   max(0, (r.width - tw) // 2) + min(tw, r.width),
                                   max(0, (r.height - th) // 2) + min(th, r.height))),
                           (max(0, (tw - r.width) // 2), max(0, (th - r.height) // 2)))
    return canvas, has_alpha


def convert(path, orig_path, mode):
    orig = load_rgba(orig_path)
    h, w = orig.shape[:2]
    im, has_alpha = fit_resize(path, (w, h), mode)
    arr = np.asarray(im).copy()
    arr[..., 3] = np.round(arr[..., 3].astype(np.float32) * 128 / 255) if has_alpha else orig[..., 3]
    return Image.fromarray(arr, "RGBA")


def sync(ws, mode, dry):
    manifest, found = read_manifest(ws), scan(ws)
    if not manifest:
        raise SystemExit("no manifest - run export first")
    files, managed = dump_files(), managed_keys()
    state_f = ws / "_state.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {}
    written = reverted = skipped = 0
    for t, m in manifest.items():
        p, key = found.get(t), m["key"]
        if p is None:
            continue
        sha = sha1(p)
        target = REPL_DIR / f"{key}.png"
        if sha == m["sha1"]:
            if key in state:
                reverted += 1
                print("revert", p.name)
                if not dry:
                    target.unlink(missing_ok=True)
                    del state[key]
            continue
        if key in managed:
            print(f"skip {p.name}: pipeline-managed ({managed[key]}) takes priority")
            skipped += 1
            continue
        if state.get(key) == sha and target.exists():
            continue
        written += 1
        print("write", p.name)
        if not dry:
            REPL_DIR.mkdir(parents=True, exist_ok=True)
            convert(p, files[key], mode).save(target)
            state[key] = sha
    if not dry:
        state_f.write_text(json.dumps(state, indent=1))
    print(f"sync: {written} written, {reverted} reverted, {skipped} skipped. Press F10 in PCSX2 to reload.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["export", "sync"])
    ap.add_argument("--ws", type=Path, default=DEFAULT_WS)
    ap.add_argument("--fit", choices=["stretch", "contain", "cover"], default="stretch",
                    help="how images with a different aspect ratio are fitted (default: stretch)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    export(a.ws) if a.cmd == "export" else sync(a.ws, a.fit, a.dry_run)


if __name__ == "__main__":
    main()
