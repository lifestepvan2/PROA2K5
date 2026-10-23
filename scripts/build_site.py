"""Build the static GitHub Pages site (site/) from the roster workbook.

    python scripts/build_site.py [--out site] [--xlsx proa_scraped.xlsx] [--check]

Inputs (all committed):
    proa_scraped.xlsx        roster, the 19 2K5 attributes (the single source of truth for ratings)
    data/proa_stats.json     pooled stats + team ids (written by scrape_proa_roster.py)
    data/overall_model.json  fitted in-game Overall model (fit_overall.py)
    assets/PS_out/<id>.png   portraits (resized to WebP here)
    site_src/                static frontend (index.html, app.js, style.css)

Overall is computed here with overall_model.predict_overall, so it works whatever cached values the xlsx holds.
--check compares it with the cached values of the workbook's Overall formula column, when there are any.
The GitHub workflow (.github/workflows/pages.yml) runs this on every change of the inputs.
"""
import argparse
import json
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from overall_data import ATTRS, default_extras  # noqa: E402
from overall_model import predict_overall  # noqa: E402
from rating_map_2k5 import read_attrs  # noqa: E402

POSITIONS = {"PG", "SG", "SF", "PF", "C"}
LOGO_URL = "https://api.2basketballbundesliga.de/pics2/{season}/lp/{team_id}"
PORTRAIT_PX = 192


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def read_workbook(path):
    """[(sheet name, [row dict])] for every team sheet; helper sheets start with '_'."""
    wb = openpyxl.load_workbook(path, data_only=True)
    out = []
    for ws in wb:
        if ws.title.startswith("_"):
            continue
        rows = list(ws.iter_rows(values_only=True))
        head = list(rows[0])
        out.append((ws.title, [dict(zip(head, r)) for r in rows[1:] if r[head.index("ProA ID")] is not None]))
    return out


def stat_block(st):
    if not st or not st.get("games"):
        return None
    seasons = []
    for s in st.get("seasons_used", []):
        m = re.match(r"(\d{4}):(\d+)G\*([\d.]+)", s)
        if m:
            seasons.append([int(m[1]), int(m[2]), float(m[3])])
    return {
        "g": st["games"], "mpg": st["minutes_avg_str"], "pts": st["points_avg"], "reb": st["rebounds_avg"],
        "oreb": st["rebounds_off_avg"], "dreb": st["rebounds_def_avg"], "ast": st["assists_avg"],
        "stl": st["steals_avg"], "blk": st["blocks_avg"], "tov": st["turnovers_avg"],
        "fg": st["fg_pct"], "fg3": st["fg3_pct"], "ft": st["ft_pct"], "seasons": seasons,
    }


def build_data(xlsx, stats_path, check=False):
    stats = json.loads(Path(stats_path).read_text(encoding="utf-8"))
    season = stats["season"]
    teams, players, problems, mismatches = [], [], [], 0
    for sheet, rows in read_workbook(xlsx):
        meta = stats["teams"].get(sheet, {})
        team = {"slug": slugify(sheet), "short": sheet, "name": meta.get("name", sheet),
                "logo": LOGO_URL.format(season=season, team_id=meta["id"]) if meta.get("id") else None, "players": []}
        for r in rows:
            pid = int(r["ProA ID"])
            pos = r["Position"]
            if pos not in POSITIONS:
                problems.append(f"{sheet}/{r['Last Name']}: position {pos!r}")
                continue
            attrs = read_attrs(r)
            h, w = float(r["Height"]), float(r["Weight"])
            ovr = max(0, min(99, round(predict_overall(pos, attrs, h, w, default_extras(attrs)))))
            if check and isinstance(r.get("Overall"), (int, float)) and int(r["Overall"]) != ovr:
                mismatches += 1
                print(f"  Overall differs: {r['First Name']} {r['Last Name']} sheet {r['Overall']} site {ovr}")
            players.append({
                "id": pid, "team": team["slug"], "first": r["First Name"], "last": r["Last Name"], "pos": pos,
                "pos2": r["Secondary Position"] if r["Secondary Position"] in POSITIONS else None,
                "no": r["Jersey Number"], "birth": [r["Birth Year"], r["Birth Month"], r["Birth Day"]],
                "h": h, "w": w, "ovr": ovr, "a": [attrs[k] for k in ATTRS],
                "s": stat_block(stats["players"].get(str(pid))),
            })
            team["players"].append(pid)
        teams.append(team)
    if problems:
        sys.exit("ERROR: " + "; ".join(problems))
    if not players or len({p["id"] for p in players}) != len(players):
        sys.exit("ERROR: no players or duplicate ProA IDs")
    bad = [p for p in players if not 0 < p["ovr"] <= 99]
    if bad:
        sys.exit(f"ERROR: Overall out of range: {[(p['last'], p['ovr']) for p in bad]}")
    if check:
        print(f"Overall check: {mismatches} differences from the workbook's cached values")
    return {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "season": season.replace("_", "/"),
            "attributes": ATTRS, "teams": teams, "players": players}


def build_portraits(players, out):
    from PIL import Image

    folder = out / "img" / "p"
    folder.mkdir(parents=True, exist_ok=True)
    missing = []
    for p in players:
        src = ROOT / "assets" / "PS_out" / f"{p['id']}.png"
        p["img"] = src.exists()
        if not src.exists():
            missing.append(p["id"])
            continue
        with Image.open(src) as im:
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            bg.alpha_composite(im)
            bg.convert("RGB").resize((PORTRAIT_PX, PORTRAIT_PX), Image.LANCZOS).save(folder / f"{p['id']}.webp", quality=82)
    return missing


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "site"))
    ap.add_argument("--xlsx", default=str(ROOT / "proa_scraped.xlsx"))
    ap.add_argument("--stats", default=str(ROOT / "data" / "proa_stats.json"))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site_src", out)
    data = build_data(args.xlsx, args.stats, args.check)
    missing = build_portraits(data["players"], out)
    (out / "data").mkdir(exist_ok=True)
    (out / "data" / "players.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    nostats = sum(1 for p in data["players"] if not p["s"])
    print(f"Site -> {out}: {len(data['teams'])} teams, {len(data['players'])} players, "
          f"{len(missing)} without portrait, {nostats} without stats")


if __name__ == "__main__":
    main()
