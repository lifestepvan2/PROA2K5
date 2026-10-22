"""Filename-based grouping of the uniform textures: which LOD / duplicate inherits from which MASTER.

Role files live flat in texture_workspace/uniforms/ and are named

    ROLE__LABEL__RES__ID.png        e.g. MASTER__PistonsShortsHome__512x256__12345678.png
                                         COPY__PistonsShortsHome__512x256__456123ce.png
                                         LOD__PistonsShortsHome__32x16__8765432a.png

  ROLE   MASTER (edit this one) | COPY (same size, generated from the MASTER) | LOD (smaller, resized from the MASTER)
  LABEL  groups MASTER + COPYs + LODs. Characters [A-Za-z0-9-] only. The generator (create_baseline_jersey.py) additionally
         reads <Team><Item><Variant> from it:  Team = NBA / in-game name (Pistons, 76ers, ...)
         Item = Jersey | Shorts | WUtorso | WUsleeves | WUlegs,  Variant = Home | Away | Alt (optional counter) or a number.
         Numbered variants are generated in the home style, Alt is skipped. Other labels (Legends1, Unsorted3, ...) work for
         the inheritance but are ignored by the generator.
  RES    informational (checked against the real size, a mismatch is only warned about)
  ID     8 hex characters - the ONLY thing that decides which in-game texture is replaced (never edit it)

Several MASTERs with one label are a warning and that group is skipped (nothing is generated for it) until it is fixed.

    python scripts/uniform_labels.py check                  warnings + writes data/uniform_lods/labels_snapshot.csv
    python scripts/uniform_labels.py list [text]            groups (optionally only labels containing text)
    python scripts/uniform_labels.py adopt                  name freshly dumped uniform textures: matches them against the
                                                            existing groups (LOD / COPY of that label) or opens Unsorted<n>
    python scripts/uniform_labels.py link FILE MASTERFILE   make FILE a COPY / LOD of MASTERFILE's group (any file name / ID)
    python scripts/uniform_labels.py promote FILE           make FILE the MASTER of its group (the old MASTER becomes a COPY)
    python scripts/uniform_labels.py relabel OLD NEW        rename a whole group
    python scripts/uniform_labels.py restore [--dry-run]    rename the files back to the names in the tracked snapshot
"""
import argparse
import collections
import csv
import re
import shutil
import sys
from pathlib import Path

from uniform_lods import OUT, TOKEN, WS, skipped

EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp"}
SNAP = OUT / "labels_snapshot.csv"
NAME = re.compile(r"^(MASTER|COPY|LOD)__([A-Za-z0-9-]+)__(\d+x\d+)__([0-9a-f]{8})$")
LABEL = re.compile(r"^(?P<team>[A-Za-z0-9-]+?)(?P<item>Jersey|Shorts|WUtorso|WUsleeves|WUlegs)"
                   r"(?P<variant>(?:Home|Away|Alt)\d*|\d+)$")
SKIP_DIRS = {"templates", "backups", "visual_sort"}  # plus every folder starting with "_"
UNIFORM_FAMILIES = {"00002253", "00002254", "00002213", "00001e13", "000019d3", "00001593", "00001153", "00000d13"}  # hi-res, cloth, LODs


def parse_label(label):
    """{team, item, variant, side} for <Team><Item><Variant> labels, else None (side: Home | Away | Alt)."""
    m = LABEL.match(label)
    if not m:
        return None
    v = m["variant"]
    side = next((s for s in ("Home", "Away", "Alt") if v.startswith(s)), "Home")  # numbered variants = home style
    return dict(team=m["team"], item=m["item"], variant=v, side=side)


def uni_dir(ws):
    return Path(ws) / "uniforms"


def scan(ws=WS):
    """(token -> entry for every ROLE__LABEL__RES__ID file under uniforms/, problems). Newest file wins on duplicate IDs."""
    base, out, problems = uni_dir(ws), {}, []
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in EXTS:
            continue
        rel = p.relative_to(base).parts[:-1]
        if any(x in SKIP_DIRS for x in rel):
            continue
        m = NAME.match(p.stem)
        if not m:
            if re.match(r"(MASTER|COPY|LOD)(__|_|-)", p.stem):
                problems.append(f"{p.name}: not of the form ROLE__LABEL__RES__ID - ignored")
            continue
        e = dict(path=p, role=m[1], label=m[2], res=m[3], token=m[4])
        old = out.get(e["token"])
        if old:
            keep, drop = (e, old) if p.stat().st_mtime > old["path"].stat().st_mtime else (old, e)
            problems.append(f"two files with ID {e['token']}: using {keep['path'].name}, ignoring {drop['path'].name}")
            e = keep
        out[e["token"]] = e
    return out, problems


def role_files(ws=WS):
    return scan(ws)[0]


def token_rows(ws=WS):
    mf = Path(ws) / "_manifest.csv"
    return {r["token"]: r for r in csv.DictReader(open(mf, encoding="utf-8"))} if mf.exists() else {}


def by_label(roles):
    g = collections.defaultdict(list)
    for e in roles.values():
        g[e["label"]].append(e)
    return g


def analyse_groups(ws=WS):
    """(mapping, problems). mapping: key -> dict(role, master, size, label) in the shape the old mapping.csv had."""
    roles, problems = scan(ws)
    rows = token_rows(ws)
    mp = {}
    for label, es in sorted(by_label(roles).items()):
        for e in es:
            r = rows.get(e["token"])
            if r is None:
                problems.append(f"{e['path'].name}: ID {e['token']} is not in the manifest - ignored")
            elif e["res"] != f"{r['w']}x{r['h']}":
                problems.append(f"{e['path'].name}: RES says {e['res']} but the texture is {r['w']}x{r['h']}")
        es = [e for e in es if e["token"] in rows]
        masters = [e for e in es if e["role"] == "MASTER"]
        if len(masters) != 1:
            problems.append(f"{label}: {'no MASTER' if not masters else str(len(masters)) + ' MASTERs'}"
                            f" - group skipped ({', '.join(e['token'] for e in masters) or 'its COPY/LOD files'})")
            continue
        m = masters[0]
        mr = rows[m["token"]]
        mw, mh = int(mr["w"]), int(mr["h"])
        mp[mr["key"]] = dict(key=mr["key"], role="master", master=mr["key"], size=f"{mw}x{mh}", label=label)
        for e in es:
            if e is m:
                continue
            r = rows[e["token"]]
            w, h = int(r["w"]), int(r["h"])
            if e["role"] == "COPY" and (w, h) != (mw, mh):
                problems.append(f"{e['path'].name}: COPY is {w}x{h} but the MASTER is {mw}x{mh} - ignored (rename it LOD?)")
            elif e["role"] == "LOD" and (w >= mw or h >= mh):
                problems.append(f"{e['path'].name}: LOD {w}x{h} is not smaller than the MASTER {mw}x{mh} - ignored")
            else:
                mp[r["key"]] = dict(key=r["key"], role=e["role"].lower(), master=mr["key"], size=f"{w}x{h}", label=label)
    return mp, problems


def load_mapping(ws=WS):
    return analyse_groups(ws)[0]


def write_snapshot(ws=WS):
    roles, rows = role_files(ws), token_rows(ws)
    SNAP.parent.mkdir(parents=True, exist_ok=True)
    with open(SNAP, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["token", "key", "role", "label", "res"])
        for t, e in sorted(roles.items(), key=lambda kv: (kv[1]["label"], kv[1]["role"], kv[0])):
            w.writerow([t, rows.get(t, {}).get("key", ""), e["role"], e["label"], e["res"]])
    return len(roles)


def report(ws=WS, verbose=False):
    """Warnings + snapshot; returns the problem list."""
    mp, problems = analyse_groups(ws)
    n = write_snapshot(ws)
    groups = sum(r["role"] == "master" for r in mp.values())
    print(f"uniform labels: {n} role files, {groups} working groups, {len(problems)} warnings"
          f"{'' if verbose or not problems else ' (python scripts/uniform_labels.py check)'}")
    if verbose:
        for p in problems:
            print("  warning:", p)
    return problems


def workspace_index(ws):
    """token -> newest workspace file carrying it (one directory walk)."""
    idx = {}
    for p in Path(ws).rglob("*"):
        if not p.is_file() or p.suffix.lower() not in EXTS or "backups" in p.parts or "templates" in p.parts:
            continue
        if skipped(p.relative_to(ws).parts[:-1]):
            continue
        m = TOKEN.search(p.stem + " ")
        if m and (m[1] not in idx or p.stat().st_mtime > idx[m[1]].stat().st_mtime):
            idx[m[1]] = p
    return idx


def find_file(ws, ref):
    """ID / file name / path of any workspace file -> (token, Path)."""
    ref = str(ref)
    m = TOKEN.search(Path(ref).stem + " ") or re.fullmatch(r"([0-9a-f]{8})", ref.strip())
    if not m:
        raise SystemExit(f"'{ref}' contains no 8-hex ID")
    t = m.group(1)
    hits = [p for p in Path(ws).rglob("*") if p.is_file() and p.suffix.lower() in EXTS and f"__{t}" in p.stem
            and not skipped(p.relative_to(ws).parts[:-1]) and "backups" not in p.parts and "templates" not in p.parts]
    if not hits:
        raise SystemExit(f"no workspace file with ID {t}")
    return t, max(hits, key=lambda p: p.stat().st_mtime)


def role_name(role, label, res, token, ext=".png"):
    return f"{role}__{label}__{res}__{token}{ext}"


def move(src, dest):
    if src == dest:
        return
    if dest.exists():
        raise SystemExit(f"cannot rename {src.name}: {dest.name} already exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dest)


def res_of(ws, t):
    r = token_rows(ws).get(t)
    if not r:
        raise SystemExit(f"ID {t} is not in the manifest - run texture_workspace.py export")
    return f"{r['w']}x{r['h']}"


def cmd_link(ws, ref, master_ref):
    t, p = find_file(ws, ref)
    mt, _ = find_file(ws, master_ref)
    roles = role_files(ws)
    m = roles.get(mt)
    if not m:
        raise SystemExit(f"{master_ref} is not a role file")
    res = res_of(ws, t)
    role = "COPY" if res == m["res"] else "LOD"
    move(p, uni_dir(ws) / role_name(role, m["label"], res, t, p.suffix.lower()))
    print(f"{t} is now a {role} of {m['label']}")


def cmd_promote(ws, ref):
    t, p = find_file(ws, ref)
    e = role_files(ws).get(t)
    if not e:
        raise SystemExit("not a role file - use `link` first")
    for o in by_label(role_files(ws))[e["label"]]:
        if o["role"] == "MASTER" and o["token"] != t:
            if o["res"] != e["res"]:
                raise SystemExit(f"the MASTER {o['path'].name} has another size ({o['res']}) than {e['res']}")
            move(o["path"], o["path"].with_name(role_name("COPY", o["label"], o["res"], o["token"], o["path"].suffix)))
    move(p, p.with_name(role_name("MASTER", e["label"], e["res"], t, p.suffix.lower())))
    print(f"{t} is now the MASTER of {e['label']}")


def cmd_relabel(ws, old, new):
    if not re.fullmatch(r"[A-Za-z0-9-]+", new):
        raise SystemExit("label: only letters, digits and '-' (no '_')")
    es = by_label(role_files(ws)).get(old)
    if not es:
        raise SystemExit(f"no group '{old}'")
    for e in es:
        move(e["path"], e["path"].with_name(role_name(e["role"], new, e["res"], e["token"], e["path"].suffix)))
    print(f"{len(es)} files: {old} -> {new}")


def cmd_list(ws, text=""):
    rows = token_rows(ws)
    for label, es in sorted(by_label(role_files(ws)).items()):
        if text.lower() not in label.lower():
            continue
        ms = [e for e in es if e["role"] == "MASTER"]
        lods = collections.Counter(e["res"] for e in es if e["role"] == "LOD")
        print(f"{label:34s} MASTER {', '.join(e['token'] + ' ' + e['res'] for e in ms) or '-':22s}"
              f" COPY {sum(e['role'] == 'COPY' for e in es)}  LOD {dict(sorted(lods.items())) or '-'}"
              f"{'' if parse_label(label) else '  (not read by the generator)'}")
    if not rows:
        print("no manifest")


def cmd_restore(ws, dry):
    roles = role_files(ws)
    n = 0
    for r in csv.DictReader(open(SNAP, encoding="utf-8")):
        want = role_name(r["role"], r["label"], r["res"], r["token"])
        try:
            t, p = find_file(ws, r["token"])
        except SystemExit:
            print("missing:", want)
            continue
        if p.name != want:
            n += 1
            print("rename", p.name, "->", want)
            if not dry:
                move(p, uni_dir(ws) / want)
    print(f"restore: {n} files renamed")


def next_unsorted(roles):
    used = [int(m[1]) for e in roles.values() if (m := re.fullmatch(r"Unsorted(\d+)", e["label"]))]
    return max(used or [0]) + 1


def adopt(ws=WS, dry=False):
    """Names freshly dumped uniform textures: LOD / COPY of the group they match, else MASTER of a new Unsorted<n> group."""
    import numpy as np

    import uniform_lods as ul
    from texlib import family, load_rgba

    rows = token_rows(ws)
    key_tok = {r["key"]: t for t, r in rows.items()}
    roles = role_files(ws)
    known = {rows[t]["key"]: e for t, e in roles.items() if t in rows}
    files, harr, glist, lods = ul.analyse()
    counter = next_unsorted(roles)
    plan = []  # (token, role, label)

    def label_has_master(label):
        return any(e["role"] == "MASTER" for e in roles.values() if e["label"] == label) or \
            any(p[1] == "MASTER" and p[2] == label for p in plan)

    for gi, g in enumerate(glist):
        members = [g["master"]] + [k for k in g["members"] if k != g["master"]]
        gl = [l for l in lods if l["ok"] and l["group"] == gi]
        fresh_hi = [k for k in members if k not in known and k in key_tok]
        fresh_lod = [l["key"] for l in gl if l["key"] not in known and l["key"] in key_tok]
        if not fresh_hi and not fresh_lod:
            continue
        cnt = collections.Counter(known[k]["label"] for k in members + [l["key"] for l in gl] if k in known)
        if cnt:
            label = cnt.most_common(1)[0][0]
        else:
            label, counter = f"Unsorted{counter}", counter + 1
        for k in fresh_hi:
            plan.append((key_tok[k], "COPY" if label_has_master(label) else "MASTER", label))
        plan += [(key_tok[k], "LOD", label) for k in fresh_lod]
    for l in lods:
        if not l["ok"] and l["key"] not in known and l["key"] in key_tok:
            plan.append((key_tok[l["key"]], "LOD", "Unmatched"))

    index = workspace_index(ws)

    def in_uniforms(key):
        p = index.get(key_tok[key])
        return p is not None and p.relative_to(ws).parts[0] == "uniforms"

    # 256x256 of the cloth family are also arena / skin textures: only those the labels placed in uniforms/ count as cloth
    cloth = [(k, load_rgba(files[k])[..., :3].astype(np.float32)) for k in files
             if family(k) == "00002213" and k in key_tok and (rows[key_tok[k]]["w"], rows[key_tok[k]]["h"]) == ("256", "256")
             and (k in known or in_uniforms(k))]
    refs = [(known[k]["label"], a) for k, a in cloth if k in known]
    for k, a in cloth:
        if k in known:
            continue
        hit = next((lab for lab, b in refs if np.abs(a - b).mean() <= 3.0), None)
        if hit:
            plan.append((key_tok[k], "COPY" if label_has_master(hit) else "MASTER", hit))
        else:
            hit, counter = f"Unsorted{counter}", counter + 1
            plan.append((key_tok[k], "MASTER", hit))
        refs.append((hit, a))

    for t, role, label in plan:
        p = index[t]
        name = role_name(role, label, res_of(ws, t), t, p.suffix.lower())
        print(f"  {'would name' if dry else 'naming'} {p.name} -> {name}")
        if not dry:
            move(p, uni_dir(ws) / name)
    print(f"adopt: {len(plan)} uniform textures named" + (" (dry run)" if dry else ""))
    if plan and not dry:
        report(ws)
    return len(plan)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "list", "adopt", "link", "promote", "relabel", "restore"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--ws", type=Path, default=WS)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    need = dict(link=2, promote=1, relabel=2)
    if len(a.args) < need.get(a.cmd, 0):
        raise SystemExit(f"{a.cmd}: expects {need[a.cmd]} argument(s)")
    if a.cmd == "check":
        report(a.ws, verbose=True)
    elif a.cmd == "list":
        cmd_list(a.ws, " ".join(a.args))
    elif a.cmd == "adopt":
        adopt(a.ws, a.dry_run)
    elif a.cmd == "link":
        cmd_link(a.ws, *a.args[:2])
        report(a.ws)
    elif a.cmd == "promote":
        cmd_promote(a.ws, a.args[0])
        report(a.ws)
    elif a.cmd == "relabel":
        cmd_relabel(a.ws, *a.args[:2])
        report(a.ws)
    elif a.cmd == "restore":
        cmd_restore(a.ws, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
