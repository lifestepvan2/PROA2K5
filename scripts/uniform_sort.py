"""Folder-based sorting interface for the uniform LOD mapping (replaces typing keys into manual.csv).

    python scripts/uniform_sort.py populate   fill texture_workspace/uniforms/visual_sort with COPIES of all uniform textures:
                                              one folder per currently mapped group (g_<master token>: the MASTER_ hi-res file,
                                              its hi-res duplicates and its LODs, original file names kept) under unknown/,
                                              everything unmatched in unsorted/. Files already in the tree are never touched or
                                              duplicated, so re-running only adds what is new (e.g. after new dumps).
    python scripts/uniform_sort.py apply      read the folders back: write data/uniform_lods/sorted.csv and regenerate
                                              mapping.csv (apply --check = report only, write nothing)

Sorting rules (the folder is the group - it may sit at any depth, e.g. Sonics/Home/Jersey/g_xxxx or loose in Sonics/Home):
  * a 512x256 file is a hi-res texture; the one named MASTER_* is the master, the other 512x256 files are its duplicates
  * every smaller 2:1 file (128x64, 64x32, 32x16, 16x8) in the same folder is a low LOD of that master
  * to change the master rename another hi-res file to MASTER_... (remove the prefix from the old one if you like)
  * files in a folder called "unsorted" (or in a folder with no 512x256 file) are not mapped at all
  * cloth (the 256x256 warm-up top / trouser textures): a g_<token> folder under <Team>/cloth/ with a MASTER_ and its identical
    copies, same rules but no LODs; populate creates these folders itself (files directly in cloth/ stay unmapped)
  * the copies here are only for sorting - editing them does nothing; edit the real files in texture_workspace/uniforms/512x256
Afterwards: texture_workspace.py export, then texture_workspace.py sync (derives all duplicates / LODs from their masters).
"""
import argparse
import csv
import re
import shutil

from uniform_lods import OUT, TOKEN, WS, load_mapping, save, tok

SORT = WS / "uniforms" / "visual_sort"
HI_SIZE = (512, 256)
CLOTH_SIZE = (256, 256)  # warm-up top / trouser cloth: master + identical copies only, no LODs were ever dumped
CLOTH_DUP_NCC = 0.995
UNSORTED = "unsorted"
PREFIX = re.compile(r"^(MASTER_|MASTER-)")


def manifest():
    """token -> dict(key, w, h, cloth) for the 'uniforms' group."""
    mf = WS / "_manifest.csv"
    if not mf.exists():
        raise SystemExit("no texture workspace manifest - run texture_workspace.py export first")
    return {r["token"]: dict(key=r["key"], w=int(r["w"]), h=int(r["h"]), cloth="cloth_256x256" in r["relpath"])
            for r in csv.DictReader(open(mf, encoding="utf-8")) if r["group"] == "uniforms"}


def token_of(p):
    m = TOKEN.search(p.stem + " ")
    return m.group(1) if m else None


def sort_files():
    """token -> path of the files currently in the sorting tree (first one wins)."""
    out = {}
    if SORT.exists():
        for p in sorted(SORT.rglob("*.png")):
            t = token_of(p)
            if t and t not in out:
                out[t] = p
    return out


def workspace_files(tokens):
    """token -> newest real workspace file (outside the sorting tree)."""
    found = {}
    for p in WS.rglob("*.png"):
        if "visual_sort" in p.parts:
            continue
        t = token_of(p)
        if t in tokens and (t not in found or p.stat().st_mtime > found[t].stat().st_mtime):
            found[t] = p
    return found


def populate():
    man = manifest()
    mapping = load_mapping()
    if not mapping:
        raise SystemExit("no mapping.csv yet - run uniform_lods.py match + save first")
    real = workspace_files(man)
    have = sort_files()
    folder = {t: p.parent for t, p in have.items()}

    def copy(t, dest):
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(real[t], dest / real[t].name)
        folder[t] = dest

    added = {"groups": 0, "mapped": 0, "unsorted": 0}
    order = sorted(man, key=lambda t: mapping.get(man[t]["key"], {}).get("role") != "master")
    for t in order:
        if t in have or t not in real or man[t]["cloth"]:
            continue
        key = man[t]["key"]
        row = mapping.get(key)
        if row is None:
            copy(t, SORT / UNSORTED)
            added["unsorted"] += 1
            continue
        mt = tok(row["master"])
        if mt not in folder and mt in real:
            copy(mt, SORT / "unknown" / f"g_{mt}")
            added["groups"] += 1
        if t not in folder and mt in folder:
            copy(t, folder[mt])
        added["mapped"] += 1
    print(f"populated {SORT}: {added['groups']} new group folders, {added['mapped']} mapped files, "
          f"{added['unsorted']} files in {UNSORTED}/ (existing files untouched)")
    populate_cloth(man, real)


def populate_cloth(man, real):
    """Warm-up top / trouser cloth (uniforms/cloth_256x256): copies into <Team>/cloth/g_<token>/, one folder per set of
    pixel-identical textures (MASTER_ + copies). Team = the label prefix of the file name; unknown -> unknown/cloth."""
    import numpy as np
    from PIL import Image

    cloth = {t: real[t] for t in man if man[t]["cloth"] and t in real}
    have = sort_files()
    for t, p in list(have.items()):
        if t in cloth and p.parent.name == "cloth":  # flat copies of the first layout (label_textures.py sort)
            p.unlink()
            del have[t]
    load = lambda p: np.asarray(Image.open(p).convert("RGBA"), dtype=np.float32).ravel()

    def ncc(a, b):
        a, b = a - a.mean(), b - b.mean()
        d = float(np.sqrt((a * a).sum() * (b * b).sum()))
        return float((a * b).sum()) / d if d else 0.0

    reps = {}  # group folder -> pixels of one member
    for t, p in have.items():
        if t in cloth and p.parent not in reps:
            reps[p.parent] = load(cloth[t])

    labels = {r["token"]: r["label"] for r in csv.DictReader(open(WS.parent / "data/texture_labels/labels.csv", encoding="utf-8"))}

    def team_of(t):
        team = labels.get(t, "unknown").split("_")[0]
        return "unknown" if team in ("unknown", "various") or "+" in team else team

    new = groups = 0
    for t in sorted((t for t in cloth if t not in have), key=lambda t: (team_of(t) == "unknown", t)):
        px = load(cloth[t])
        team = team_of(t)
        # identical-looking textures of different teams differ in colour only, so duplicates are looked for within a team
        d = next((d for d, r in reps.items() if d.parent.parent.name == team and r.shape == px.shape
                  and ncc(r, px) >= CLOTH_DUP_NCC), None)
        name = PREFIX.sub("", cloth[t].name)
        if d is None:
            d = SORT / team / "cloth" / f"g_{t}"
            reps[d] = px
            name, groups = "MASTER_" + name, groups + 1
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cloth[t], d / name)
        new += 1
    print(f"cloth: {new} files copied, {groups} new group folders (under <Team>/cloth/)")


def decide():
    """Read the tree -> (rows for sorted.csv, messages, renames)."""
    man = manifest()
    prev = load_mapping()
    files = sort_files()
    msgs, rows, renames = [], [], []
    groups = {}
    for t, p in files.items():
        if t not in man:
            msgs.append(f"ignored (not a uniform texture): {p.relative_to(SORT)}")
            continue
        groups.setdefault(p.parent, []).append((t, p))
    for d, members in sorted(groups.items()):
        rel = d.relative_to(SORT).as_posix() or "."
        info = [(t, p, man[t]["key"], (man[t]["w"], man[t]["h"])) for t, p in members]
        cloth = "cloth" in d.relative_to(SORT).parts
        hi = CLOTH_SIZE if cloth else HI_SIZE
        if d.name.lower() == UNSORTED or d.name == "cloth":  # cloth needs a g_<token> folder per set of identical files
            rows += [(k, "none", "", f"{s[0]}x{s[1]}") for _, _, k, s in info]
            continue
        hires = [i for i in info if i[3] == hi]
        if not hires:
            msgs.append(f"{rel}: no {hi[0]}x{hi[1]} file in the folder -> its {len(info)} files stay unmapped")
            rows += [(k, "none", "", f"{s[0]}x{s[1]}") for _, _, k, s in info]
            continue
        was_master = lambda i: prev.get(i[2], {}).get("role") == "master"
        named = [i for i in hires if PREFIX.match(i[1].name)]
        if len(named) == 1:
            master = named[0]
        elif len(named) > 1:
            fresh = [i for i in named if not was_master(i)]
            master = fresh[0] if len(fresh) == 1 else sorted(named, key=lambda i: i[1].name)[0]
            if len(fresh) != 1:
                msgs.append(f"{rel}: {len(named)} files are named MASTER_ - using {master[1].name}")
        else:
            old = [i for i in hires if was_master(i)]
            master = old[0] if old else sorted(hires, key=lambda i: i[1].name)[0]
            msgs.append(f"{rel}: no MASTER_ file - using {master[1].name}")
        for t, p, k, s in info:
            size = f"{s[0]}x{s[1]}"
            if k == master[2]:
                rows.append((k, "master", k, size))
            elif s == hi:
                rows.append((k, "copy", master[2], size))
            elif not cloth and s[0] == 2 * s[1] and s[0] < HI_SIZE[0]:
                rows.append((k, "lod", master[2], size))
            else:
                msgs.append(f"{rel}: {p.name} is {size}, not a 2:1 uniform LOD -> left unmapped")
                rows.append((k, "none", "", size))
        for t, p, k, s in info:
            is_m = k == master[2]
            has = bool(PREFIX.match(p.name))
            if is_m and not has:
                renames.append((p, p.with_name("MASTER_" + p.name)))
            elif has and not is_m:
                renames.append((p, p.with_name(PREFIX.sub("", p.name))))
    return rows, msgs, renames


def apply(check=False):
    rows, msgs, renames = decide()
    for m in msgs:
        print("  " + m)
    prev = load_mapping()
    new = {k: (r, m) for k, r, m, _ in rows if r != "none"}
    changed = [k for k, (r, m) in new.items() if (prev.get(k, {}).get("role"), prev.get(k, {}).get("master")) != (r, m)]
    removed = [k for k, r, m, _ in rows if r == "none" and k in prev]
    print(f"folder sort: {len(new)} mapped files ({sum(r == 'master' for r, _ in new.values())} groups), "
          f"{len(changed)} changed, {len(removed)} unmapped vs the current mapping.csv")
    if check:
        return
    with open(OUT / "sorted.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "role", "master", "size"])
        w.writerows(rows)
    save()
    for a, b in renames:
        if not b.exists():
            a.rename(b)
    if renames:
        print(f"renamed {len(renames)} sorting copies so only the master carries MASTER_")
    print("next: python scripts/texture_workspace.py export ; python scripts/texture_workspace.py sync")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["populate", "apply"])
    ap.add_argument("--check", action="store_true", help="apply: report only")
    a = ap.parse_args()
    populate() if a.cmd == "populate" else apply(a.check)
