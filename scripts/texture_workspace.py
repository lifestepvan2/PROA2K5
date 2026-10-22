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
import collections
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
import gen_skin_replacements as skins
import texcluster
import uniform_lods
from texlib import REPL_DIR, ROOT, dump_files, family, load_rgba
from uniform_lods import sid

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
    out.update({k: "light-reserve skin" for k in skins.managed_keys()})
    return out


def load_labels():
    """data/texture_labels/labels.csv (key,label,group,sub,...): team label prefix and optional group/sub override per dump key."""
    p = ROOT / "data/texture_labels/labels.csv"
    return {r["key"]: r for r in csv.DictReader(open(p, encoding="utf-8"))} if p.exists() else {}


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
    return mark_uniform_roles(out)


def mark_uniform_roles(rows):
    """Uniform LOD mapping (scripts/uniform_lods.py): label the MASTER, its duplicates and the auto-generated LODs."""
    mp = uniform_lods.load_mapping()
    if not mp:
        return rows
    by_key = {r["key"]: r for r in rows}
    base = {r["key"]: r["label"] for r in rows}
    for r in rows:
        m = mp.get(r["key"])
        if not m:
            continue
        tag = sid(m["master"])
        r["group"] = "uniforms"
        if m["role"] == "master":
            r["sub"], r["label"] = ("cloth_256x256" if m["size"] == "256x256" else "512x256"), safe(f"MASTER_{base[r['key']]}")
        elif m["role"] == "copy":
            r["sub"] = "cloth_256x256_duplicates" if m["size"] == "256x256" else "512x256_duplicates"
            r["label"] = safe(f"copy-of-MASTER-{tag}_{base.get(m['master'], '')}")
        else:
            r["sub"], r["label"] = f"auto_lods_{m['size']}", safe(f"AUTO-LOD-of-MASTER-{tag}_{r['w']}x{r['h']}")
    return rows


def rel_path(row):
    parts = [row["group"]] + ([row["sub"]] if row["sub"] else [])
    return Path(*parts) / f"{row['label']}__{token(row['key'])}.png"


def scan(ws):
    """token -> newest file in the working folder."""
    found = {}
    for p in ws.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS and "visual_sort" not in p.parts:  # visual_sort holds sorting copies only
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
    uniform_map = uniform_lods.load_mapping()  # these are renamed/regrouped even when edited (MASTER / duplicate / auto LOD)
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
            if p == ws / old[t]["relpath"] and p != ws / want and (sha1(p) == osha or r["key"] in uniform_map):
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


def lod_from(img, size):
    """Mip-style downscale of an RGBA image (alpha-weighted so transparent texels do not bleed)."""
    return img.convert("RGBa").resize(size, Image.BOX).convert("RGBA")


def sync_uniform_lods(ws, mp, manifest, found, files, managed, state, mode, dry):
    """Duplicates and LODs of a uniform inherit from the MASTER 512x256 (mapping: data/uniform_lods/mapping.csv)."""
    ed = {}  # key -> edited working file
    for m in manifest.values():
        p = found.get(m["token"])
        if p is not None and sha1(p) != m["sha1"]:
            ed[m["key"]] = p
    masters = collections.defaultdict(list)
    for k, r in mp.items():
        masters[r["master"]].append(k)
    n_write = n_revert = 0
    for mk, members in sorted(masters.items()):
        if mk in managed or mk not in files:
            continue
        copies = [k for k in members if mp[k]["role"] == "copy"]
        src = ed.get(mk)
        if src is None:
            alt = sorted((ed[k] for k in copies if k in ed), key=lambda p: -p.stat().st_mtime)
            src = alt[0] if alt else None
            if src:
                print(f"note: master {sid(mk)} unchanged but duplicate {src.name} edited - using it as the source "
                      f"(edit the MASTER file to avoid this)")
        targets = [k for k in members if k != mk]
        if src is None:
            for k in [mk] + targets:
                if str(state.get(k, "")).startswith("auto:"):
                    n_revert += 1
                    print("revert (auto)", k)
                    if not dry:
                        (REPL_DIR / f"{k}.png").unlink(missing_ok=True)
                        del state[k]
            continue
        want = f"auto:{sha1(src)}:{mode}"
        img = None
        for k in ([mk] if src != ed.get(mk) else []) + targets:
            if k in managed:
                continue
            target = REPL_DIR / f"{k}.png"
            if state.get(k) == want and target.exists():
                continue
            n_write += 1
            print(f"write (auto {mp[k]['role']}{' ' + mp[k]['size'] if mp[k]['role'] == 'lod' else ''})", k)
            if dry:
                continue
            img = img or convert(src, files[mk], mode)
            out = img
            if mp[k]["role"] == "lod":
                with Image.open(files[k]) as o:
                    out = lod_from(img, o.size)
            REPL_DIR.mkdir(parents=True, exist_ok=True)
            out.save(target)
            state[k] = want
    return n_write, n_revert


def sync(ws, mode, dry):
    manifest, found = read_manifest(ws), scan(ws)
    if not manifest:
        raise SystemExit("no manifest - run export first")
    files, managed = dump_files(), managed_keys()
    mp = uniform_lods.load_mapping()
    state_f = ws / "_state.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {}
    written = reverted = skipped = ignored = 0
    for t, m in manifest.items():
        p, key = found.get(t), m["key"]
        if p is None:
            continue
        sha = sha1(p)
        target = REPL_DIR / f"{key}.png"
        role = mp.get(key, {}).get("role")
        if role in ("copy", "lod"):
            continue  # generated from the master below; edits of the copy itself are applied only if the master is unedited
        if role == "master" and str(state.get(key, "")).startswith("auto:") and sha == m["sha1"]:
            continue
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
    if mp:
        for t, m in manifest.items():
            p = found.get(t)
            if p is not None and mp.get(m["key"], {}).get("role") == "lod" and sha1(p) != m["sha1"]:
                ignored += 1
        w, r = sync_uniform_lods(ws, mp, manifest, found, files, managed, state, mode, dry)
        written, reverted = written + w, reverted + r
    if not dry:
        state_f.write_text(json.dumps(state, indent=1))
    msg = f"sync: {written} written, {reverted} reverted, {skipped} skipped"
    if ignored:
        msg += f", {ignored} hand-edited auto LODs ignored (they are generated from the MASTER)"
    print(msg + ". Press F10 in PCSX2 to reload.")


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
