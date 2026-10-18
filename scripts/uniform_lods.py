"""Uniform texture LODs: the 16x8 / 32x16 / 64x32 / 128x64 uniform textures are low-res LODs of the 512x256 originals,
and some 512x256 originals exist several times (visually identical duplicates; one of them is the MASTER).

    python scripts/uniform_lods.py match   match LODs / duplicates from the ORIGINAL dumps, write data/uniform_lods/candidates.csv
                                           and contact sheets (docs/_tmp/uniform_lods/*.png) for visual confirmation
    python scripts/uniform_lods.py save    freeze the confirmed result as data/uniform_lods/mapping.csv
                                           (honours data/uniform_lods/exclude.txt: one key or 6-char id per line, and
                                           data/uniform_lods/manual.csv: columns lod,master - add LODs/duplicates by hand;
                                           each cell may be a workspace file name, its 8-char __token, a 6-char id or a full key)
                                           and lists the still unmatched LODs in data/uniform_lods/unmatched.csv

mapping.csv columns: key, role (master | copy | lod), master (key of the master), size, score
`texture_workspace.py sync` regenerates every `copy` and `lod` from its master's replacement.
"""
import argparse
import collections
import csv
import hashlib
import re

import numpy as np
from PIL import Image, ImageDraw

from texlib import ROOT, dump_files, family, load_rgba

HI = ("00002253", "00002254")
LOD_FAMILY = {"00000d13": (16, 8), "00001153": (32, 16), "00001593": (64, 32), "000019d3": (128, 64)}
THRESH = {(128, 64): 0.90, (64, 32): 0.85, (32, 16): 0.80, (16, 8): 0.75}
DUP_NCC = 0.995
CHAIN_NCC = 0.93
OUT = ROOT / "data/uniform_lods"
SHEETS = ROOT / "docs/_tmp/uniform_lods"
WS = ROOT / "texture_workspace"
TOKEN = re.compile(r"__([0-9a-f]{8})(?:\W|$)")


def small(arr, size):
    """RGB of an RGBA array (alpha 0..128) composited on mid grey, box-downscaled to size."""
    a = np.clip(arr[..., 3:4].astype(np.float32) / 128.0, 0, 1)
    rgb = arr[..., :3].astype(np.float32) * a + 128 * (1 - a)
    im = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    if im.size != size:
        im = im.resize(size, Image.BOX)
    return np.asarray(im).astype(np.float32).ravel()


def ncc_rows(X):
    X = X - X.mean(1, keepdims=True)
    return X / np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-6)


def disp(arr):
    a = np.clip(arr[..., 3:4].astype(np.float32) / 128, 0, 1)
    rgb = arr[..., :3].astype(np.float32) * a + 90 * (1 - a)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


def sid(key):
    return key.split("-")[0][:6]


def workspace_state():
    """(key -> mtime of working-folder files the user changed, set of keys in the 'uniforms' group)."""
    mf = WS / "_manifest.csv"
    if not mf.exists():
        raise SystemExit("no texture workspace manifest - run texture_workspace.py export first")
    found = {}
    for p in WS.rglob("*.png"):
        m = TOKEN.search(p.stem + " ")
        if m and (m.group(1) not in found or p.stat().st_mtime > found[m.group(1)].stat().st_mtime):
            found[m.group(1)] = p
    edited, uni = {}, set()
    for r in csv.DictReader(open(mf, encoding="utf-8")):
        if r["group"] == "uniforms":
            uni.add(r["key"])
        p = found.get(r["token"])
        if p and hashlib.sha1(p.read_bytes()).hexdigest() != r["sha1"]:
            edited[r["key"]] = p.stat().st_mtime
    return edited, uni


def load_mapping(path=None):
    """key -> dict(role, master, size, score). Empty when no mapping has been saved yet."""
    path = path or OUT / "mapping.csv"
    if not path.exists():
        return {}
    return {r["key"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def analyse():
    files = dump_files()
    edited, uni = workspace_state()
    hk = sorted(k for k in files if family(k) in HI)
    harr = {k: load_rgba(files[k]) for k in hk}
    F = ncc_rows(np.stack([small(harr[k], (128, 64)) for k in hk]))
    C = F @ F.T
    par = list(range(len(hk)))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for i in range(len(hk)):
        for j in range(i + 1, len(hk)):
            if C[i, j] > DUP_NCC:
                par[find(i)] = find(j)
    groups = collections.defaultdict(list)
    for i in range(len(hk)):
        groups[find(i)].append(hk[i])
    glist = []
    for mem in groups.values():
        mem = sorted(mem)
        ed = sorted((k for k in mem if k in edited), key=lambda k: -edited[k])
        glist.append(dict(master=ed[0] if ed else mem[0], members=mem))
    glist.sort(key=lambda g: g["master"])
    lods = []
    prev = []  # accepted LODs of the next larger size
    for fam, size in sorted(LOD_FAMILY.items(), key=lambda kv: -kv[1][0]):
        keys = sorted(k for k in files if family(k) == fam and k in uni)
        if not keys:
            continue
        L = ncc_rows(np.stack([small(load_rgba(files[k]), size) for k in keys]))
        G = ncc_rows(np.stack([small(harr[g["master"]], size) for g in glist]))
        S = G @ L.T  # group x lod
        P = None
        if prev:  # the LOD is also a mip of the next larger LOD: strong evidence, independent of the hi-res
            P = L @ ncc_rows(np.stack([small(load_rgba(files[p["key"]]), size) for p in prev])).T
        cur = []
        for j, k in enumerate(keys):
            order = np.argsort(-S[:, j])
            score, margin = float(S[order[0], j]), float(S[order[0], j] - S[order[1], j])
            group, via, ok = int(order[0]), "hi", score >= THRESH[size] or (score >= THRESH[size] - 0.07 and margin >= 0.1)
            if size[0] < 128:  # without a parent LOD only a very close hi-res match is trustworthy at these sizes
                ok = score >= 0.9
            if P is not None and P[j].max() >= CHAIN_NCC:
                pj = int(P[j].argmax())
                group, via, ok = prev[pj]["group"], f"lod {sid(prev[pj]['key'])}", True
            cur.append(dict(key=k, size=f"{size[0]}x{size[1]}", group=group, score=score, second=score - margin, ok=ok, via=via,
                            direct_group=int(order[0])))
        lods += cur
        prev = [l for l in cur if l["ok"]]
    return files, harr, glist, lods


def sheet(rows, path, title, cols=8, tile=(160, 80)):
    """rows: list of (header, [(image, caption)...]); a row wraps after `cols` tiles."""
    tw, th = tile
    cap = 14
    lines = sum(max(1, -(-len(t) // cols)) for _, t in rows)
    W = 150 + cols * (tw + 6)
    H = 24 + lines * (th + cap + 6) + len(rows) * 4
    sh = Image.new("RGB", (W, H), (30, 30, 30))
    d = ImageDraw.Draw(sh)
    d.text((4, 4), title, fill=(255, 255, 255))
    y = 24
    for head, tiles in rows:
        d.text((4, y + 2), head, fill=(255, 220, 0))
        for n, (im, caption) in enumerate(tiles):
            x, yy = 150 + (n % cols) * (tw + 6), y + (n // cols) * (th + cap + 6)
            sh.paste(im.resize(tile, Image.NEAREST if im.width < 64 else Image.LANCZOS), (x, yy + cap))
            d.text((x, yy + 1), caption, fill=(200, 255, 200))
        y += max(1, -(-len(tiles) // cols)) * (th + cap + 6) + 4
    sh.save(path)


def match():
    files, harr, glist, lods = analyse()
    OUT.mkdir(parents=True, exist_ok=True)
    SHEETS.mkdir(parents=True, exist_ok=True)
    for old in SHEETS.glob("*.png"):
        old.unlink()
    by_group = collections.defaultdict(list)
    for l in lods:
        if l["ok"]:
            by_group[l["group"]].append(l)
    print(f"hi-res originals: {sum(len(g['members']) for g in glist)} in {len(glist)} visual groups "
          f"({sum(len(g['members']) > 1 for g in glist)} with duplicates)")
    for size in THRESH:
        s = f"{size[0]}x{size[1]}"
        sel = [l for l in lods if l["size"] == s]
        print(f"  {s}: {sum(l['ok'] for l in sel)}/{len(sel)} matched (score >= {THRESH[size]})")

    rows = []
    for g in glist:
        if len(g["members"]) > 1:
            order = [g["master"]] + [k for k in g["members"] if k != g["master"]]
            rows.append((f"group {sid(g['master'])}",
                         [(disp(harr[k]), f"{'MASTER' if k == g['master'] else 'copy  '} {sid(k)}") for k in order]))
    for i in range(0, len(rows), 12):
        sheet(rows[i:i + 12], SHEETS / f"dups_{i // 12 + 1:02d}.png", "512x256 duplicates (first tile = MASTER)", cols=4, tile=(256, 128))

    rows = []
    for gi, g in enumerate(glist):
        ls = sorted(by_group.get(gi, []), key=lambda l: (-int(l["size"].split("x")[0]), l["key"]))
        if ls:
            tiles = [(disp(harr[g["master"]]), f"HI {sid(g['master'])}")]
            tiles += [(disp(load_rgba(files[l["key"]])),
                       f"{l['size']} {sid(l['key'])} {l['score']:.2f}{'?' if l['direct_group'] != l['group'] else ''}") for l in ls]
            rows.append((f"group {sid(g['master'])} ({len(g['members'])} hi)", tiles))
    for i in range(0, len(rows), 9):
        sheet(rows[i:i + 9], SHEETS / f"lods_{i // 9 + 1:02d}.png", "hi-res master | matched LODs (size id score)")

    rows = []
    for l in sorted((l for l in lods if not l["ok"]), key=lambda l: (l["size"], -l["score"])):
        g = glist[l["group"]]
        rows.append((f"{l['size']} {sid(l['key'])}", [(disp(load_rgba(files[l["key"]])), f"LOD {l['score']:.2f}"),
                                                       (disp(harr[g["master"]]), f"best HI {sid(g['master'])}")]))
    for i in range(0, len(rows), 14):
        sheet(rows[i:i + 14], SHEETS / f"unmatched_{i // 14 + 1:02d}.png", "UNMATCHED LODs (no hi-res original found)", cols=2)

    with open(OUT / "candidates.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "role", "master", "size", "score", "second", "accepted", "via"])
        for g in glist:
            for k in g["members"]:
                w.writerow([k, "master" if k == g["master"] else "copy", g["master"], "512x256", "", "", 1, ""])
        for l in lods:
            w.writerow([l["key"], "lod", glist[l["group"]]["master"], l["size"], f"{l['score']:.4f}", f"{l['second']:.4f}", int(l["ok"]), l["via"]])
    print(f"sheets: {SHEETS}")


def tok(key):
    return hashlib.sha1(key.encode()).hexdigest()[:8]


def save():
    cand = list(csv.DictReader(open(OUT / "candidates.csv", encoding="utf-8")))
    excl_f = OUT / "exclude.txt"
    excl = set(excl_f.read_text().split()) if excl_f.exists() else set()
    rows = {r["key"]: r for r in cand if r["accepted"] == "1" and r["key"] not in excl and sid(r["key"]) not in excl}
    files = dump_files()

    def resolve(ref):
        """workspace file name / 8-char token / 6-char id / full key -> dump key"""
        ref = ref.strip()
        m = TOKEN.search(ref + " ")
        ref = m.group(1) if m else ref
        hit = [k for k in files if ref == k or ref == tok(k) or ref == sid(k)]
        if len(hit) != 1:
            raise SystemExit(f"manual.csv: '{ref}' matches {len(hit)} textures")
        return hit[0]

    manual_f = OUT / "manual.csv"
    if not manual_f.exists():
        manual_f.write_text("lod,master\n", encoding="utf-8")
    n_manual = 0
    for r in csv.DictReader(open(manual_f, encoding="utf-8")):
        if not r["lod"].strip() or r["lod"].lstrip().startswith("#"):
            continue
        lk, mk = resolve(r["lod"]), resolve(r["master"])
        mk = rows[mk]["master"] if mk in rows and rows[mk]["role"] != "master" else mk
        if mk not in rows or rows[mk]["role"] != "master":
            raise SystemExit(f"manual.csv: {r['master']} is not a 512x256 uniform master")
        with Image.open(files[lk]) as im:
            size = f"{im.width}x{im.height}"
        rows[lk] = dict(key=lk, role="copy" if size == "512x256" else "lod", master=mk, size=size, score="manual")
        n_manual += 1
    with open(OUT / "mapping.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "role", "master", "size", "score"])
        for r in rows.values():
            w.writerow([r["key"], r["role"], r["master"], r["size"], r["score"]])
    # LODs still unmatched, with the workspace file names to use in manual.csv
    ws_file = {}
    if (WS / "_manifest.csv").exists():
        ws_file = {r["key"]: r["relpath"] for r in csv.DictReader(open(WS / "_manifest.csv", encoding="utf-8"))}
    with open(OUT / "unmatched.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["token", "size", "workspace_file", "best_master_token", "best_master_file", "score"])
        for r in cand:
            if r["role"] == "lod" and r["key"] not in rows:
                w.writerow([tok(r["key"]), r["size"], ws_file.get(r["key"], ""), tok(r["master"]), ws_file.get(r["master"], ""), r["score"]])
    print(f"saved {OUT / 'mapping.csv'}: {dict(collections.Counter(r['role'] for r in rows.values()))} "
          f"({n_manual} manual, left out {len(cand) - len(rows) + n_manual}); unmatched list: {OUT / 'unmatched.csv'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["match", "save"])
    {"match": match, "save": save}[ap.parse_args().cmd]()
