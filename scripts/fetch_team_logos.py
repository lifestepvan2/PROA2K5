"""Fetch the club logos from the Pro A website into nba2k_editor/assets/<38 + team index>.png (the logo asset gen_replacements
and the logo/jersey generators use). The site only serves ~100 px logos; they are upscaled as a stopgap - replace the asset
with a high-res logo by hand where one is available.

    python scripts/fetch_team_logos.py --sheets Ulm Essen Heidelberg [--season 2026_2027]
"""
import argparse
import csv
import io
import sys
from pathlib import Path

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from scrape_proa_roster import TEAM_MAP  # noqa: E402

ROOT = Path(__file__).parent.parent
LOGO_URL = "https://api.2basketballbundesliga.de/pics2/{season}/lo/{team_id}"
LOGO_ID0 = 38
MIN_SIDE = 800


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", nargs="+", required=True, help="team sheet names (data/proa_teams.csv)")
    ap.add_argument("--season", default="2026_2027")
    a = ap.parse_args()
    order = {r["sheet"]: i for i, r in enumerate(csv.DictReader(open(ROOT / "data/proa_teams.csv", encoding="utf-8")))}
    ids = {sheet: tid for tid, (_, sheet) in TEAM_MAP.items()}
    for sheet in a.sheets:
        resp = requests.get(LOGO_URL.format(season=a.season, team_id=ids[sheet]), timeout=15,
                            headers={"User-Agent": "Mozilla/5.0 (compatible; ProADataScraper/1.0)"})
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        f = max(1, MIN_SIDE // max(img.size))
        img = img.resize((img.width * f, img.height * f), Image.LANCZOS)
        dst = ROOT / "nba2k_editor/assets" / f"{LOGO_ID0 + order[sheet]}.png"
        img.save(dst)
        print(f"{sheet}: {dst.name} ({img.width}x{img.height})")


if __name__ == "__main__":
    main()
