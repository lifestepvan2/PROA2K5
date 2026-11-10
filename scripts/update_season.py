"""One-command season update: scrape -> headshots -> roster -> face casting -> texture replacements -> memory card.

    python scripts/update_season.py --season 2026_2027 [--card PATH] [--skip-scrape] [--rematch-faces]

Manual prerequisites (see docs/SeasonUpdateWorkflow.md): when the league's team set changed, edit TEAM_MAP in
scrape_proa_roster.py, data/proa_teams.csv (including arenas), data/team_slots.csv and run fetch_team_logos.py once for
the new clubs. Without --card the card is left alone (writing needs PCSX2 closed).
Optional --iso-source PRISTINE --iso-out NEW adds one verified lettering/court/year/skin ISO build.
Export/edit the team_palettes workspace first; nonzero Skin Tone overrides require both ISO options.
"""
import argparse
import subprocess
import sys
from pathlib import Path
import skin_tones

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
    ap.add_argument("--skip-scrape", action="store_true", help="reuse proa_scraped.xlsx, applying persistent overrides first")
    ap.add_argument("--refresh", action="store_true", help="re-fetch scraped pages instead of using the cache")
    ap.add_argument("--rematch-faces", action="store_true", help="redo all automatic face picks (manual overrides are kept)")
    ap.add_argument("--iso-source", help="verified pristine Europe ISO (required for nonzero Skin Tone)")
    ap.add_argument("--iso-out", help="new output ISO path; existing/mounted outputs are refused")
    ap.add_argument("--team-palettes", "--lettering-workspace", dest="team_palettes",
                    help="shared team palette workspace (default: texture_workspace/team_palettes)")
    a = ap.parse_args()
    parts = a.season.split("_")
    if (len(parts) != 2 or not all(len(p) == 4 and p.isdecimal() for p in parts)
            or int(parts[1]) != int(parts[0]) + 1):
        ap.error("--season must be consecutive YYYY_YYYY years")
    if bool(a.iso_source) != bool(a.iso_out):
        ap.error("--iso-source and --iso-out must be supplied together")
    if a.card and pcsx2_running():
        sys.exit("PCSX2 is running - close it first (it holds the memory card), then re-run.")

    iso_args = []
    if a.iso_source:
        workspace = a.team_palettes or str(ROOT / "texture_workspace" / "team_palettes")
        iso_args = ["--iso-source", a.iso_source, "--iso-out", a.iso_out, "--workspace", workspace,
                    "--stats-year", a.season.split("_")[0]]
        run("lettering_workspace.py", "check", *iso_args)
    if not a.skip_scrape:
        run("scrape_proa_roster.py", "--season", a.season, *(["--refresh"] if a.refresh else []))
    else:
        run("player_database.py")
    if not a.iso_source and skin_tones.workbook_requests(ROOT / "proa_scraped.xlsx"):
        sys.exit("Nonzero Skin Tone requires --iso-source and --iso-out; no roster or card has been built.")
    run("crop_headshots.py", "--season", a.season)
    roster_args = ["--season", a.season]
    if a.team_palettes:
        roster_args.extend(["--team-palettes", a.team_palettes])
    run("build_roster.py", *roster_args, "--prepare-faces")  # provisional map; no manual leg changes yet
    run("face_embed.py")
    run("face_match.py", *(["--rematch"] if a.rematch_faces else []),
        *(["--iso-source", a.iso_source] if a.iso_source else []))
    run("build_roster.py", *roster_args)
    run("gen_replacements.py")
    run("gen_skin_replacements.py")
    run("gen_logo_replacements.py")
    if a.iso_source:
        run("lettering_workspace.py", "build", *iso_args, "--skin-plan", str(skin_tones.PLAN))
    if a.card:
        # Do not publish a roster to the card until every requested ISO patch has succeeded.
        run("build_roster.py", *roster_args, "--card", a.card)
    print("\nDone. Review data/roster_build/report.md and docs/_face_sheets/, press F10 in PCSX2 to reload textures.")
    if a.iso_source:
        print(f"Combined ISO written to {a.iso_out}. Boot it fresh; F10 does not reload ISO lettering/courts/skin assets.")
    if not a.card:
        print("Card not written (no --card given).")


if __name__ == "__main__":
    main()
