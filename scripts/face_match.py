"""Assign every ProA player an existing NBA player model (pid) with the most similar face.

Candidates are the face textures of all NBA player models (data/face_match/faces, from face_load_scan.py --faces).
Cost = -ArcFace cosine similarity + W_SKIN * |skin lightness difference| (ProA photos mapped to the texture scale with the
fixed SKIN_CAL curve). Every pid is used at most once (the lineup portrait is keyed by pid); all new players are solved in ONE
league-wide Hungarian assignment, so scarce faces go to the players they fit best instead of to whichever team is matched first.
There are fewer light NBA faces than light ProA players, so the "light reserve" (skin_brighten.py) adds recolourable models:
reserved pids are scored by their brightened face (data/face_match/bright.npz), fit any light player and are no candidates
for the others (their arm texture becomes light). gen_skin_replacements.py writes the recoloured textures.
Output: data/face_match/proa_pid_map.csv - the single, editable source of truth (also the cache):
  pid = automatic match (written by this script), override_pid = manual pick (never written by this script;
  build_roster.py uses override_pid if set, else pid), skin_target = the player's skin lightness (texture scale; the recolour
  target of reserved pids). Players already in the file keep their pid on later runs (new/changed seasons only match the new
  players); --rematch redoes the automatic matches, keeping overrides.
Contact sheets go to docs/_face_sheets/ (scratch, git-ignored); reserved faces are shown recoloured.
Usage: python scripts/face_match.py [--rematch] [--w-skin 2.0]
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
import skin_brighten as sb  # noqa: E402
from face_embed import FACES, proa_portrait, tex_face  # noqa: E402
from gen_replacements import pid_keys  # noqa: E402

OUT = ROOT / "data/face_match"
SHEETS = ROOT / "docs/_face_sheets"
CROP = (75, 20, 415, 427)
# ProA headshot cheek lightness (CIELAB L, 0-255 scale) -> in-game face texture lightness. The photos are lit/exposed unevenly,
# but ordered correctly (checked on sorted contact sheets): <~105 dark, 105-150 mixed, >150 light. The textures run darker
# (their light faces span L 125-172), so the light end is compressed. A percentile alignment is wrong here: the league has far
# more light-skinned players than the NBA face pool has light faces.
SKIN_CAL = ([40, 100, 130, 160, 210], [40, 97, 125, 145, 170])


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
    # the light-arm class is reserved: its pids are usable only if their face/neck can be recoloured (skin_brighten.py scan)
    reserved, usable = sb.reserved_pids(), sb.usable_pids()
    pids = [p for p in pids if p not in reserved or p in usable]
    seen, uniq = set(), []
    for p in pids:  # several pids share an identical face texture (e.g. classic-team duplicates): keep one
        h = hashlib.md5((FACES / f"{p}_face.png").read_bytes()).hexdigest()
        if h not in seen:
            seen.add(h)
            uniq.append(p)
    pids = uniq
    ne = np.array([E[f"tex:{p}"] for p in pids])
    nl = np.array([S[f"tex:{p}"][0] for p in pids])
    bright = np.array([p in usable for p in pids])
    if bright.any():  # reserved pids are matched by their brightened face
        B = np.load(sb.BRIGHT)
        for c in np.flatnonzero(bright):
            ne[c], nl[c] = B[f"emb:{pids[c]}"], B[f"lab:{pids[c]}"][0]
    # players without a usable headshot (silhouette / no face found) get a neutral zero embedding: they take whatever pid is left
    players = list(csv.DictReader(open(ROOT / "data/roster_build/player_map.csv", encoding="utf-8")))
    have = np.array([f"proa:{r['proa_id']}" in E.files for r in players])
    pe = np.array([E[f"proa:{r['proa_id']}"] if h else np.zeros(ne.shape[1], ne.dtype) for r, h in zip(players, have)])
    pl = np.array([S[f"proa:{r['proa_id']}"][0] if h else np.nan for r, h in zip(players, have)])
    pl[~have] = np.median(pl[have])
    pl = np.interp(pl, *SKIN_CAL)
    return pids, names, ne, nl / 100, players, pe, pl / 100, E, bright


def skin_diff(pl, nl, bright):
    """|lightness difference| matrix (players x pids). A brightened face is recoloured to the player's own lightness, so any
    light player fits it for free; the others are ruled out strongly (the light arm class cannot be undone)."""
    d = np.abs(pl[:, None] - nl[None, :])
    d[:, bright] = (2 * np.maximum(0, sb.LIGHT_MIN - pl) + np.maximum(0, pl - sb.LIGHT_MAX))[:, None]
    return d


def sheet(team, rows, names, face=lambda pid, r: tex_face(pid)):
    W = 132
    img = Image.new("RGB", (W * 4 + 260, W * len(rows)), "white")
    d = ImageDraw.Draw(img)
    for i, (r, picks, tag) in enumerate(rows):
        pr = proa_portrait(r["proa_id"]).crop(CROP).resize((W - 4, W - 4))
        img.paste(pr, (2, i * W + 2))
        for j, (pid, sc) in enumerate(picks):
            img.paste(face(pid, r).resize((W - 4, W - 4), Image.LANCZOS), (W * (j + 1) + 2, i * W + 2))
            d.rectangle((W * (j + 1) + 2, i * W + 2, W * (j + 1) + W - 3, i * W + 24), fill="white")
            d.text((W * (j + 1) + 4, i * W + 4), f"{names[pid]} ({pid})\n{sc:.2f}" + (f" <== {tag}" if j == 0 else ""), fill="red")
        d.text((W * 4 + 8, i * W + 8), f"{r['first']} {r['last']}\n(was {r['orig_first']} {r['orig_last']})\n"
               f"slot {r['slot']} ovr {r['ovr']}", fill="black")
    try:
        img.save(SHEETS / f"{team}.png")
    except OSError:  # file open in a viewer
        print("could not write sheet", team)


MAP = OUT / "proa_pid_map.csv"
FIELDS = ["proa_id", "team_slot", "record", "first", "last", "pid", "nba_name", "sim", "skin_pen", "override_pid", "override_name",
          "skin_target"]


def read_map():
    if not MAP.exists():
        return {}
    return {r["proa_id"]: r for r in csv.DictReader(open(MAP, encoding="utf-8-sig"))}


def ival(s):
    s = (s or "").strip()
    return int(s) if s else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--w-skin", type=float, default=2.0, help="weight of the skin lightness difference (L/100) against the ArcFace similarity")
    ap.add_argument("--rematch", action="store_true", help="ignore cached matches and match everybody again (override_pid is kept)")
    a = ap.parse_args()
    pids, names, ne, nl, players, pe, pl, E, bright = load()
    col = {p: c for c, p in enumerate(pids)}
    sim = pe @ ne.T
    skin = skin_diff(pl, nl, bright)
    cost0 = -sim + a.w_skin * skin + 0.05 * bright[None, :]  # a small preference for natural faces over recoloured ones
    prev = read_map()
    cache = {} if a.rematch else prev
    reserved, usable = sb.reserved_pids(), sb.usable_pids()

    def manual(i):
        p = ival(prev.get(players[i]["proa_id"], {}).get("override_pid"))
        if p is not None and p not in names:
            print(f"WARNING: override_pid {p} of {players[i]['first']} {players[i]['last']} is not a known NBA pid, ignored")
            return None
        if p in reserved and p not in usable:
            print(f"WARNING: override_pid {p} of {players[i]['first']} {players[i]['last']} is in the light-arm reserve but cannot be recoloured")
        return p

    cached = {i for i, r in enumerate(players) if ival(cache.get(r["proa_id"], {}).get("pid")) is not None
              and ival(cache[r["proa_id"]]["pid"]) in names}
    final = {i: manual(i) or ival(cache[players[i]["proa_id"]]["pid"]) for i in cached}  # effective pid per cached player
    result = {i: (ival(cache[players[i]["proa_id"]]["pid"]), cache[players[i]["proa_id"]]["sim"], cache[players[i]["proa_id"]]["skin_pen"])
              for i in cached}
    taken = set(final.values()) | {manual(i) for i in range(len(players)) if manual(i)}
    todo = [i for i in range(len(players)) if i not in cached]
    free = [c for c, p in enumerate(pids) if p not in taken]
    if todo:
        if len(free) < len(todo):
            raise SystemExit(f"only {len(free)} free face models for {len(todo)} players")
        ri, ci = linear_sum_assignment(cost0[np.ix_(todo, free)])
        for k, c in zip(ri, ci):
            i, c = todo[k], free[c]
            result[i] = (pids[c], f"{sim[i, c]:.3f}", f"{a.w_skin * skin[i, c]:.3f}")
            final[i] = pids[c]
    for i in range(len(players)):
        if manual(i):
            final[i] = manual(i)
    used_mask = np.array([100.0 if p in set(final.values()) else 0.0 for p in pids])
    target = {r["proa_id"]: pl[i] for i, r in enumerate(players)}

    def face(pid, r):
        return sb.face_image(pid, target[r["proa_id"]]) if pid in usable else tex_face(pid)

    teams = {}
    for i, r in enumerate(players):
        teams.setdefault((int(r["team_slot"]), r["sheet"]), []).append(i)
    SHEETS.mkdir(parents=True, exist_ok=True)
    for old in SHEETS.glob("*.png"):  # sheets of teams from earlier rosters
        old.unlink()
    for (ts, tname), idx in sorted(teams.items()):
        rows = []
        for i in idx:
            m = manual(i)
            eff = final[i]
            ev = ne[col[eff]] if eff in col else np.array(E[f"tex:{eff}"])
            others = [o for o in np.argsort(cost0[i] + used_mask) if pids[o] != eff][:2]  # best still unused alternatives
            picks = [(eff, float(pe[i] @ ev))] + [(pids[o], sim[i, o]) for o in others]
            rows.append((players[i], picks, "override" if m else "pick"))
        sheet(f"{ts:02d}_{tname}", rows, names, face)
    with open(MAP, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for i, (pid, s, sp) in sorted(result.items()):
            r = players[i]
            m = manual(i)
            w.writerow([r["proa_id"], r["team_slot"], r["record"], r["first"], r["last"], pid, names[pid], s, sp,
                        m or "", names[m] if m else "", f"{pl[i]:.3f}"])
    sims = np.array([float(v[1]) for v in result.values()])
    n_new = len(result) - len(cached)
    d = np.array([skin[i, col[final[i]]] for i in result if final[i] in col])
    print(f"skin lightness |diff| (L/100) mean {d.mean():.3f}, >0.15: {(d > 0.15).sum()}, >0.25: {(d > 0.25).sum()}")
    print(f"{sum(1 for i in result if final[i] in usable)} players on recoloured (light-reserve) faces")
    print(f"{len(result)} players ({len(cached)} cached, {n_new} newly matched); sim mean {sims.mean():.3f} min {sims.min():.3f}; "
          f"distinct pids {len({final[i] for i in result})}; overrides {sum(1 for i in result if manual(i))}")
