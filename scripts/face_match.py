"""Assign every ProA player an existing NBA player model (pid) with the most similar face.

Candidates are the face textures of all NBA player models (data/face_match/faces, from face_load_scan.py --faces).
Cost = -ArcFace cosine similarity + W_SKIN * |skin lightness difference| (ProA photos calibrated to the texture scale)
+ usage penalty (a pid reused across teams costs more each time, up to MAX_USES). Players of one ProA team always get
distinct pids (Hungarian per team).
Output: data/face_match/proa_pid_map.csv and contact sheets in docs/_face_sheets/ (scratch, git-ignored).
Usage: python scripts/face_match.py [--w-skin 1.0] [--reuse 0.08] [--max-uses 4]
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
    return pids, names, ne, nl / 100, players, pe, pl / 100


def sheet(team, rows, names):
    W = 132
    img = Image.new("RGB", (W * 4 + 260, W * len(rows)), "white")
    d = ImageDraw.Draw(img)
    for i, (r, picks) in enumerate(rows):
        pr = proa_portrait(r["proa_id"]).crop(CROP).resize((W - 4, W - 4))
        img.paste(pr, (2, i * W + 2))
        for j, (pid, sc) in enumerate(picks):
            img.paste(tex_face(pid).resize((W - 4, W - 4), Image.LANCZOS), (W * (j + 1) + 2, i * W + 2))
            d.rectangle((W * (j + 1) + 2, i * W + 2, W * (j + 1) + W - 3, i * W + 24), fill="white")
            d.text((W * (j + 1) + 4, i * W + 4), f"{names[pid]} ({pid})\n{sc:.2f}" + (" <== pick" if j == 0 else ""), fill="red")
        d.text((W * 4 + 8, i * W + 8), f"{r['first']} {r['last']}\n(was {r['orig_first']} {r['orig_last']})\n"
               f"slot {r['slot']} ovr {r['ovr']}", fill="black")
    img.save(SHEETS / f"{team}.png")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--w-skin", type=float, default=1.0)
    ap.add_argument("--reuse", type=float, default=0.08)
    ap.add_argument("--max-uses", type=int, default=4)
    a = ap.parse_args()
    pids, names, ne, nl, players, pe, pl = load()
    sim = pe @ ne.T
    cost0 = -sim + a.w_skin * np.abs(pl[:, None] - nl[None, :])
    uses = np.zeros(len(pids), int)
    teams = {}
    for i, r in enumerate(players):
        teams.setdefault((int(r["team_slot"]), r["sheet"]), []).append(i)
    SHEETS.mkdir(parents=True, exist_ok=True)
    result = {}
    for (ts, tname), idx in sorted(teams.items()):
        pen = a.reuse * uses ** 1.5 + np.where(uses >= a.max_uses, 10, 0)
        cost = cost0[idx] + pen[None, :]
        ri, ci = linear_sum_assignment(cost)
        rows = []
        for k, c in zip(ri, ci):
            i = idx[k]
            uses[c] += 1
            picks = [(pids[c], sim[i, c])] + [(pids[o], sim[i, o]) for o in np.argsort(cost[k]) if o != c][:2]
            result[i] = (pids[c], sim[i, c], a.w_skin * abs(pl[i] - nl[c]))
            rows.append((players[i], picks))
        sheet(f"{ts:02d}_{tname}", rows, names)
    with open(OUT / "proa_pid_map.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["proa_id", "team_slot", "record", "first", "last", "pid", "nba_name", "sim", "skin_pen"])
        for i, (pid, s, sp) in sorted(result.items()):
            r = players[i]
            w.writerow([r["proa_id"], r["team_slot"], r["record"], r["first"], r["last"], pid, names[pid], f"{s:.3f}", f"{sp:.3f}"])
    sims = np.array([v[1] for v in result.values()])
    print(len(result), "players; sim mean", sims.mean().round(3), "min", sims.min().round(3),
          "; distinct pids", len({v[0] for v in result.values()}), "; max uses", uses.max())
