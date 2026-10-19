"""Build data/texture_labels/labels.csv (applied by texture_workspace.py export) from the live home-arena scan + visual labels.

    python scripts/label_textures.py build   add missing rows to labels.csv (existing rows are never touched - edit them freely)
    python scripts/label_textures.py sort    copy the cloth textures into texture_workspace/uniforms/visual_sort/<Team>/cloth/

Sources, in priority order:
  1. scan   data/texture_labels/home_scan_summary.csv (scripts/arena_scan.py report): which NBA home teams drew the texture.
            1 team -> that team, 2-4 -> "A+B", 5+ -> "various"
  2. visual data/texture_labels/visual_labels.csv (token,team,kind,group,sub,evidence): hand labels, used for the team of
            textures the scan never saw; `kind`/`group`/`sub` apply always (cloth templates -> uniforms/cloth_256x256)
Workflow: arena_scan.py scan/report -> texture_workspace.py export -> label_textures.py build -> texture_workspace.py export
"""
import csv
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "texture_workspace"
DIR = ROOT / "data" / "texture_labels"
LABELS = DIR / "labels.csv"
FIELDS = ["key", "token", "label", "group", "sub", "source", "evidence"]
TARGET_GROUPS = {"arena_props", "uniform_parts", "loading_video_tiles", "courts_and_floors"}
NICK = {"T'Wolves": "Timberwolves"}
TOKEN = re.compile(r"__([0-9a-f]{8})")


def read(p):
    return list(csv.DictReader(open(p, encoding="utf-8-sig")))


def scan_team(row):
    if not row:
        return None
    n, teams = int(row["n_home_teams"]), [NICK.get(t, t) for t in row["teams"].split("|")]
    return teams[0] if n == 1 else "+".join(sorted(teams)) if n <= 4 else "various"


def build():
    man = read(WS / "_manifest.csv")
    scan = {r["key"]: r for r in read(DIR / "home_scan_summary.csv")}
    visual = {r["token"]: r for r in read(DIR / "visual_labels.csv")}
    have = {r["key"]: r for r in read(LABELS)} if LABELS.exists() else {}
    out = list(have.values())
    added = conflicts = 0
    for m in man:
        v = visual.get(m["token"])
        if m["key"] in have or not (m["group"] in TARGET_GROUPS or v):
            continue
        v = v or {}
        team, src, ev = scan_team(scan.get(m["key"])), "scan", "home-arena scan"
        vt = v.get("team", "")
        if vt and team is None:
            team, src, ev = vt, "visual", v.get("evidence", "")
        elif vt and team != vt:
            conflicts += 1
            print(f"scan={team} visual={vt} -> keeping scan: {m['relpath']}")
        if not team and v.get("kind"):
            team, src, ev = "unknown", "visual", v.get("evidence", "")
        if not team:
            continue
        label = team + (f"_{v['kind']}" if v.get("kind") else "")
        out.append(dict(key=m["key"], token=m["token"], label=label, group=v.get("group", ""), sub=v.get("sub", ""),
                        source=src, evidence=ev))
        added += 1
    with open(LABELS, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(out)
    print(f"labels.csv: {added} new rows, {len(out)} total, {conflicts} conflicts")


def sort_cloth():
    """Copies (never moves) the cloth textures into visual_sort/<Team>/cloth/ - unknown / ambiguous teams go to unknown/cloth."""
    labels = {r["token"]: r for r in read(LABELS)}
    dest_root = WS / "uniforms" / "visual_sort"
    n = 0
    for p in (WS / "uniforms" / "cloth_256x256").glob("*.png"):
        m = TOKEN.search(p.name)
        lab = labels.get(m.group(1)) if m else None
        team = lab["label"].split("_")[0] if lab else "unknown"
        if team in ("various", "unknown") or "+" in team:
            team = "unknown"
        d = dest_root / team / "cloth"
        d.mkdir(parents=True, exist_ok=True)
        if not any(q.name.endswith(p.name.split("__")[1]) for q in d.glob("*.png")):
            shutil.copy2(p, d / p.name)
            n += 1
    print(f"copied {n} cloth textures into {dest_root}")


if __name__ == "__main__":
    {"build": build, "sort": sort_cloth}[sys.argv[1] if len(sys.argv) > 1 else "build"]()
