"""One-command season update: scrape -> headshots -> roster -> face casting -> texture replacements -> memory card.

    python scripts/update_season.py --season 2026_2027 [--card PATH] [--skip-scrape] [--rematch-faces]

Manual prerequisites (see docs/SeasonUpdateWorkflow.md): when the league's team set changed, edit TEAM_MAP in
scrape_proa_roster.py, data/proa_teams.csv, data/team_slots.csv, data/proa_arenas.csv and run fetch_team_logos.py once for
the new clubs. Without --card the card is left alone (writing needs PCSX2 closed).
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PY = sys.executable


def run(*args):
    cmd = [PY, str(ROOT / "scripts" / args[0]), *args[1:]]
    print("\n>>", args[0], *args[1:], flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def pcsx2_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq pcsx2-qt.exe"], capture_output=True, text=True).stdout
    return "pcsx2" in out.lower()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", default="2026_2027")
    ap.add_argument("--card", help="memory card to write the roster to (PCSX2 must be closed)")
    ap.add_argument("--skip-scrape", action="store_true", help="reuse proa_scraped.xlsx as is")
    ap.add_argument("--refresh", action="store_true", help="re-fetch scraped pages instead of using the cache")
    ap.add_argument("--rematch-faces", action="store_true", help="redo all automatic face picks (manual overrides are kept)")
    a = ap.parse_args()
    if a.card and pcsx2_running():
        sys.exit("PCSX2 is running - close it first (it holds the memory card), then re-run.")

    if not a.skip_scrape:
        run("scrape_proa_roster.py", "--season", a.season, *(["--refresh"] if a.refresh else []))
    run("crop_headshots.py", "--season", a.season)
    run("build_roster.py")  # writes player_map.csv, which the face steps read
    run("face_embed.py")
    run("face_match.py", *(["--rematch"] if a.rematch_faces else []))
    run("build_roster.py", *(["--card", a.card] if a.card else []))
    run("gen_replacements.py")
    run("gen_logo_replacements.py")
    print("\nDone. Review data/roster_build/report.md and docs/_face_sheets/, press F10 in PCSX2 to reload textures.")
    if not a.card:
        print("Card not written (no --card given).")


if __name__ == "__main__":
    main()
