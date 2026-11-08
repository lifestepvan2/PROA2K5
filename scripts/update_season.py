"""One-command season update: scrape -> headshots -> roster -> face casting -> texture replacements -> memory card.

    python scripts/update_season.py --season 2026_2027 [--card PATH] [--skip-scrape] [--rematch-faces]

Manual prerequisites (see docs/SeasonUpdateWorkflow.md): when the league's team set changed, edit TEAM_MAP in
scrape_proa_roster.py, data/proa_teams.csv (including arenas), data/team_slots.csv and run fetch_team_logos.py once for
the new clubs. Without --card the card is left alone (writing needs PCSX2 closed).
Optional --iso-source PRISTINE --iso-out NEW adds verified lettering ISO generation.
Export/edit the lettering workspace first; roster-only runs never require an ISO.
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
    ap.add_argument("--iso-source", help="verified pristine Europe ISO (opt-in lettering stage)")
    ap.add_argument("--iso-out", help="new output ISO path; existing/mounted outputs are refused")
    ap.add_argument("--lettering-workspace", help="editable lettering workspace (default: texture_workspace/lettering)")
    a = ap.parse_args()
    if bool(a.iso_source) != bool(a.iso_out):
        ap.error("--iso-source and --iso-out must be supplied together")
    if a.lettering_workspace and not a.iso_source:
        ap.error("--lettering-workspace requires --iso-source and --iso-out")
    if a.card and pcsx2_running():
        sys.exit("PCSX2 is running - close it first (it holds the memory card), then re-run.")

    iso_args = []
    if a.iso_source:
        workspace = a.lettering_workspace or str(ROOT / "texture_workspace" / "lettering")
        iso_args = ["--iso-source", a.iso_source, "--iso-out", a.iso_out, "--workspace", workspace]
        run("lettering_workspace.py", "check", *iso_args)
    if not a.skip_scrape:
        run("scrape_proa_roster.py", "--season", a.season, *(["--refresh"] if a.refresh else []))
    run("crop_headshots.py", "--season", a.season)
    run("build_roster.py")  # writes player_map.csv, which the face steps read
    run("face_embed.py")
    run("face_match.py", *(["--rematch"] if a.rematch_faces else []))
    run("build_roster.py", *(["--card", a.card] if a.card else []))
    run("gen_replacements.py")
    run("gen_skin_replacements.py")
    run("gen_logo_replacements.py")
    if a.iso_source:
        run("lettering_workspace.py", "build", *iso_args)
    print("\nDone. Review data/roster_build/report.md and docs/_face_sheets/, press F10 in PCSX2 to reload textures.")
    if a.iso_source:
        print(f"Lettering ISO written to {a.iso_out}. Boot it fresh; F10 does not reload ISO lettering.")
    if not a.card:
        print("Card not written (no --card given).")


if __name__ == "__main__":
    main()
