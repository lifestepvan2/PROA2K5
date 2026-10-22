"""Visual matching engine for the uniform textures: the 16x8 ... 256x128 uniform textures are low-res LODs of the 512x256
originals, and some originals exist several times (visually identical duplicates).

Library only. The grouping itself lives in the file names (scripts/uniform_labels.py); `analyse()` is what
`uniform_labels.py adopt` uses to find the group a freshly dumped texture belongs to.
"""
import collections
import csv
import hashlib
import re

import numpy as np
from PIL import Image

from texlib import ROOT, dump_files, family, load_rgba

HI = ("00002253", "00002254")
LOD_FAMILY = {"00001e13": (256, 128), "00000d13": (16, 8), "00001153": (32, 16), "00001593": (64, 32), "000019d3": (128, 64)}
THRESH = {(256, 128): 0.93, (128, 64): 0.90, (64, 32): 0.85, (32, 16): 0.80, (16, 8): 0.75}
DUP_NCC = 0.995
CHAIN_NCC = 0.93
OUT = ROOT / "data/uniform_lods"
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


def sid(key):
    return key.split("-")[0][:6]


def skipped(dirs):
    """Workspace folders the scans ignore: top-level _retired_* style folders and the old visual_sort sorting copies."""
    return "visual_sort" in dirs or bool(dirs) and dirs[0].startswith("_")


def workspace_state():
    """(key -> mtime of working-folder files the user changed, set of keys in the 'uniforms' group)."""
    mf = WS / "_manifest.csv"
    if not mf.exists():
        raise SystemExit("no texture workspace manifest - run texture_workspace.py export first")
    found = {}
    for p in WS.rglob("*.png"):
        if skipped(p.relative_to(WS).parts[:-1]):
            continue
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


def load_mapping():
    """key -> dict(role, master, size, label), derived from the ROLE__LABEL__RES__ID file names."""
    import uniform_labels
    return uniform_labels.load_mapping(WS)


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
    prev_master = {r["master"] for r in load_mapping().values() if r["role"] == "master"}
    glist = []
    for mem in groups.values():
        mem = sorted(mem)
        ed = sorted((k for k in mem if k in edited), key=lambda k: -edited[k])
        kept = [k for k in mem if k in prev_master]  # keep earlier master choices stable when new duplicates get dumped
        glist.append(dict(master=ed[0] if ed else kept[0] if kept else mem[0], members=mem))
    glist.sort(key=lambda g: g["master"])
    # the middle hash of a dump key is shared by all mip levels of a texture: exact evidence for LOD -> group
    mid_groups = collections.defaultdict(set)
    for gi, g in enumerate(glist):
        for k in g["members"]:
            mid_groups[k.split("-")[1]].add(gi)
    lods = []
    prev = []  # accepted LODs of the next larger size
    for fam, size in sorted(LOD_FAMILY.items(), key=lambda kv: -kv[1][0]):
        # 256x128 (family 1e13) is classified as 'uniform_parts' in the workspace until it is mapped
        keys = sorted(k for k in files if family(k) == fam and (k in uni or fam == "00001e13"))
        keys = [k for k in keys if load_rgba(files[k]).shape[:2] == (size[1], size[0])]
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
            hg = mid_groups.get(k.split("-")[1], set())
            if len(hg) == 1:
                group, via, ok = next(iter(hg)), "hash", True
            cur.append(dict(key=k, size=f"{size[0]}x{size[1]}", group=group, score=score, second=score - margin, ok=ok, via=via,
                            direct_group=int(order[0])))
        if fam == "00001e13":  # not every 256x128 dump is a uniform mip: keep only the matched ones
            cur = [l for l in cur if l["ok"]]
        lods += cur
        prev = [l for l in cur if l["ok"]]
    return files, harr, glist, lods


def tok(key):
    return hashlib.sha1(key.encode()).hexdigest()[:8]
