"""Assign every ProA player an existing NBA player model (pid) with the most similar face.

Candidates are the face textures of all NBA player models (data/face_match/faces, from face_load_scan.py --faces).
Cost = -ArcFace cosine similarity + W_SKIN * |skin lightness difference| (ProA photos calibrated to the texture scale)
+ usage penalty (a pid reused across teams costs more each time, up to MAX_USES). Players of one ProA team always get
distinct pids (Hungarian per team).
Output: data/face_match/proa_pid_map.csv - the single, editable source of truth (also the cache):
  pid = automatic match (written by this script), override_pid = manual pick (never written by this script;
  build_roster.py uses override_pid if set, else pid). Players already in the file keep their pid on later runs
  (new/changed seasons only match the new players); --rematch redoes the automatic matches, keeping overrides.
Contact sheets go to docs/_face_sheets/ (scratch, git-ignored).
Usage: python scripts/face_match.py [--rematch] [--w-skin 1.0] [--reuse 0.08] [--max-uses 1]
"""
import argparse
import csv
import hashlib
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from face_embed import FACES, proa_portrait, tex_face  # noqa: E402
from gen_replacements import pid_keys  # noqa: E402

OUT = ROOT / "data/face_match"
SHEETS = ROOT / "docs/_face_sheets"
CROP = (75, 20, 415, 427)


def load():
    E, S = np.load(OUT / "embeddings.npz"), np.load(OUT / "skin_lab.npz")
    names = {}
    for r in csv.DictReader(open(ROOT / "data/nba_defaults/players_unknown.csv", encoding="utf-8")):
        if r["team_slot"] and int(r["team_slot"]) < 39:
            names.setdefault(int.from_bytes(bytes.fromhex(r["hex"])[4:6], "little"), f"{r['first']} {r['last']}")
    pids = sorted(int(k[4:]) for k in E.files if k.startswith("tex:") and int(k[4:]) in names)
    # lineup portraits are keyed by pid: a pid whose portrait texture is shared with other pids (generic placeholders) cannot
    # get an individual headshot
    pk = pid_keys()
    owners = {}
    for p, ks in pk.items():
        for k in ks:
            owners.setdefault(k, set()).add(p)
    pids = [p for p in pids if pk.get(p) and all(len(owners[k]) == 1 for k in pk[p])]
    seen, uniq = set(), []
    for p in pids:  # several pids share an identical face texture (e.g. classic-team duplicates): keep one
        h = hashlib.md5((FACES / f"{p}_face.png").read_bytes()).hexdigest()
        if h not in seen:
            seen.add(h)
            uniq.append(p)
    pids = uniq
    ne = np.array([E[f"tex:{p}"] for p in pids])
    nl = np.array([S[f"tex:{p}"][0] for p in pids])
    players = [r for r in csv.DictReader(open(ROOT / "data/roster_build/player_map.csv", encoding="utf-8"))
               if f"proa:{r['proa_id']}" in E.files]
    pe = np.array([E[f"proa:{r['proa_id']}"] for r in players])
    pl = np.array([S[f"proa:{r['proa_id']}"][0] for r in players])
    # the ProA photos are lit differently from the game textures: align the 5th/95th lightness percentiles
    (a0, a1), (b0, b1) = np.percentile(pl, [5, 95]), np.percentile(nl, [5, 95])
    pl = b0 + (pl - a0) * (b1 - b0) / (a1 - a0)
    return pids, names, ne, nl / 100, players, pe, pl / 100, E


def sheet(team, rows, names):
    W = 132
    img = Image.new("RGB", (W * 4 + 260, W * len(rows)), "white")
    d = ImageDraw.Draw(img)
    for i, (r, picks, tag) in enumerate(rows):
        pr = proa_portrait(r["proa_id"]).crop(CROP).resize((W - 4, W - 4))
        img.paste(pr, (2, i * W + 2))
        for j, (pid, sc) in enumerate(picks):
            img.paste(tex_face(pid).resize((W - 4, W - 4), Image.LANCZOS), (W * (j + 1) + 2, i * W + 2))
            d.rectangle((W * (j + 1) + 2, i * W + 2, W * (j + 1) + W - 3, i * W + 24), fill="white")
            d.text((W * (j + 1) + 4, i * W + 4), f"{names[pid]} ({pid})\n{sc:.2f}" + (f" <== {tag}" if j == 0 else ""), fill="red")
        d.text((W * 4 + 8, i * W + 8), f"{r['first']} {r['last']}\n(was {r['orig_first']} {r['orig_last']})\n"
               f"slot {r['slot']} ovr {r['ovr']}", fill="black")
    try:
        img.save(SHEETS / f"{team}.png")
    except OSError:  # file open in a viewer
        print("could not write sheet", team)


MAP = OUT / "proa_pid_map.csv"
FIELDS = ["proa_id", "team_slot", "record", "first", "last", "pid", "nba_name", "sim", "skin_pen", "override_pid", "override_name"]


def read_map():
    if not MAP.exists():
        return {}
    return {r["proa_id"]: r for r in csv.DictReader(open(MAP, encoding="utf-8-sig"))}


def ival(s):
    s = (s or "").strip()
    return int(s) if s else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--w-skin", type=float, default=1.0)
    ap.add_argument("--reuse", type=float, default=0.08)
    ap.add_argument("--max-uses", type=int, default=1, help="1 = every pid at most once (needed: the lineup portrait is keyed by pid)")
    ap.add_argument("--rematch", action="store_true", help="ignore cached matches and match everybody again (override_pid is kept)")
    a = ap.parse_args()
    pids, names, ne, nl, players, pe, pl, E = load()
    col = {p: c for c, p in enumerate(pids)}
    sim = pe @ ne.T
    cost0 = -sim + a.w_skin * np.abs(pl[:, None] - nl[None, :])
    prev = read_map()
    cache = {} if a.rematch else prev

    def manual(i):
        p = ival(prev.get(players[i]["proa_id"], {}).get("override_pid"))
        if p is not None and p not in names:
            print(f"WARNING: override_pid {p} of {players[i]['first']} {players[i]['last']} is not a known NBA pid, ignored")
            return None
        return p

    cached = {i for i, r in enumerate(players) if ival(cache.get(r["proa_id"], {}).get("pid")) is not None
              and ival(cache[r["proa_id"]]["pid"]) in names}
    final = {i: manual(i) or ival(cache[players[i]["proa_id"]]["pid"]) for i in cached}  # effective pid per cached player
    uses = np.zeros(len(pids), int)
    for p in final.values():
        if p in col:
            uses[col[p]] += 1
    for i in range(len(players)):  # manual picks of players that are matched anew still occupy their pid
        if i not in cached and manual(i) in col:
            uses[col[manual(i)]] += 1
    teams = {}
    for i, r in enumerate(players):
        teams.setdefault((int(r["team_slot"]), r["sheet"]), []).append(i)
    SHEETS.mkdir(parents=True, exist_ok=True)
    result = {i: (ival(cache[players[i]["proa_id"]]["pid"]), cache[players[i]["proa_id"]]["sim"], cache[players[i]["proa_id"]]["skin_pen"])
              for i in cached}
    for (ts, tname), idx in sorted(teams.items()):
        todo = [i for i in idx if i not in cached]
        pen = a.reuse * uses ** 1.5 + np.where(uses >= a.max_uses, 10, 0)
        taken = {final[i] for i in idx if i in cached} | {manual(i) for i in idx if manual(i)}
        taken_mask = np.array([100.0 if p in taken else 0.0 for p in pids])
        if todo:
            ri, ci = linear_sum_assignment(cost0[todo] + pen[None, :] + taken_mask[None, :])
            for k, c in zip(ri, ci):
                i = todo[k]
                uses[c] += 1
                result[i] = (pids[c], f"{sim[i, c]:.3f}", f"{a.w_skin * abs(pl[i] - nl[c]):.3f}")
                final[i] = pids[c]
        rows = []
        for i in idx:
            m = manual(i)
            eff = m or result[i][0]
            if m and m != result[i][0]:
                final[i] = m
            ev = np.array(E[f"tex:{eff}"])
            row_cost = cost0[i] + pen + taken_mask
            others = [o for o in np.argsort(row_cost) if pids[o] != eff][:2]
            picks = [(eff, float(pe[i] @ ev))] + [(pids[o], sim[i, o]) for o in others]
            rows.append((players[i], picks, "override" if m else "pick"))
        sheet(f"{ts:02d}_{tname}", rows, names)
    with open(MAP, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for i, (pid, s, sp) in sorted(result.items()):
            r = players[i]
            m = manual(i)
            w.writerow([r["proa_id"], r["team_slot"], r["record"], r["first"], r["last"], pid, names[pid], s, sp,
                        m or "", names[m] if m else ""])
    sims = np.array([float(v[1]) for v in result.values()])
    n_new = len(result) - len(cached)
    print(f"{len(result)} players ({len(cached)} cached, {n_new} newly matched); sim mean {sims.mean():.3f} min {sims.min():.3f}; "
          f"distinct pids {len({final[i] for i in result})}; overrides {sum(1 for i in result if manual(i))}")
