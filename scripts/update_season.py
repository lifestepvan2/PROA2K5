"""ISO-first season update: scrape -> headshots -> roster -> face casting -> replacements -> combined ISO.

    python scripts/update_season.py --season 2026_2027 --iso-source CLEAN --iso-out NEW [--card PATH]
    python scripts/update_season.py --iso-source CLEAN --card-only --card PATH
    python scripts/update_season.py --iso-source CLEAN --build-only

Manual prerequisites (see docs/SeasonUpdateWorkflow.md): when the league's team set changed, edit TEAM_MAP in
scrape_proa_roster.py, data/proa_teams.csv (including arenas), data/team_slots.csv and run fetch_team_logos.py once for
the new clubs. Without --card the card is left alone (writing needs PCSX2 closed).
The default roster is embedded alongside lettering/court/year/skin patches in one verified new ISO.
Export/edit texture_workspace_ISO first. Portrait/legacy skin replacements remain external.
Card-only/build-only modes are explicit alternatives; nonzero Skin Tone requires an ISO output.
"""
import argparse
import subprocess
import sys
from pathlib import Path
import skin_tones
import team_palettes
import texture_iso_workspace

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
    ap.add_argument("--iso-source", required=True, help="verified pristine Europe ISO; also supplies the roster baseline")
    ap.add_argument("--iso-out", help="new output ISO path; existing/mounted outputs are refused")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--card-only", action="store_true", help="export the roster to --card without building an ISO")
    mode.add_argument("--build-only", action="store_true", help="build roster/replacement artifacts without publishing an ISO or card")
    ap.add_argument("--team-palettes", "--lettering-workspace", dest="team_palettes",
                    help="ISO team palette workspace (default: texture_workspace_ISO/team_palettes)")
    ap.add_argument("--texture-workspace", default=str(texture_iso_workspace.DEFAULT_WS),
                    help="native ISO logo masters (default: texture_workspace_ISO)")
    ap.add_argument("--legacy-logo-replacements", action="store_true",
                    help="also generate legacy PCSX2 logo PNGs when building an ISO")
    ap.add_argument("--repack-archive", action="store_true",
                    help="experimental native archive sector pooling; requires --iso-out")
    a = ap.parse_args()
    parts = a.season.split("_")
    if (len(parts) != 2 or not all(len(p) == 4 and p.isdecimal() for p in parts)
            or int(parts[1]) != int(parts[0]) + 1):
        ap.error("--season must be consecutive YYYY_YYYY years")
    if a.card_only or a.build_only:
        if a.iso_out:
            ap.error("--iso-out cannot be combined with --card-only or --build-only")
        if a.card_only and not a.card:
            ap.error("--card-only requires --card")
        if a.build_only and a.card:
            ap.error("--build-only cannot write --card")
    elif not a.iso_out:
        ap.error("--iso-out is required; use --card-only or --build-only for an explicit alternative")
    if a.repack_archive and not a.iso_out:
        ap.error("--repack-archive requires --iso-out")
    if a.card and pcsx2_running():
        sys.exit("PCSX2 is running - close it first (it holds the memory card), then re-run.")

    iso_args = []
    workspace = a.team_palettes or str(Path(a.texture_workspace) / "team_palettes")
    if a.iso_out:
        iso_args = ["--iso-source", a.iso_source, "--iso-out", a.iso_out, "--workspace", workspace,
                    "--stats-year", a.season.split("_")[0], "--texture-workspace", a.texture_workspace]
        if a.repack_archive:
            iso_args.append("--repack-archive")
        run("season_iso.py", "check", *iso_args)
    else:
        # Verify the same baseline before scrape/workbook side effects, without requiring visual ISO controls.
        from roster_iso import baseline, read_source
        with Path(a.iso_source).open("rb") as stream:
            baseline(read_source(stream))
    if not a.skip_scrape:
        run("scrape_proa_roster.py", "--season", a.season, *(["--refresh"] if a.refresh else []))
    else:
        run("player_database.py")
    if not a.iso_out and skin_tones.workbook_requests(ROOT / "proa_scraped.xlsx"):
        sys.exit("Nonzero Skin Tone requires --iso-source and --iso-out; no roster or card has been built.")
    run("crop_headshots.py", "--season", a.season)
    roster_args = ["--season", a.season, "--iso-source", a.iso_source]
    if a.team_palettes or a.iso_out:
        roster_args.extend(["--team-palettes", workspace])
    run("build_roster.py", *roster_args, "--prepare-faces")  # provisional map; no manual leg changes yet
    run("face_embed.py")
    run("face_match.py", *(["--rematch"] if a.rematch_faces else []),
        *(["--iso-source", a.iso_source] if a.iso_source else []),
        *(["--repack-archive"] if a.repack_archive else []))
    run("build_roster.py", *roster_args)
    run("gen_replacements.py")
    run("gen_skin_replacements.py")
    if not a.iso_out or a.legacy_logo_replacements:
        run("gen_logo_replacements.py")
    if a.iso_out:
        run("season_iso.py", "build", *iso_args, "--skin-plan", str(skin_tones.PLAN),
            "--roster", str(ROOT / "data" / "roster_build" / "payload_proa.bin"))
    if a.card:
        # Do not publish a roster to the card until every requested ISO patch has succeeded.
        run("card_patch.py", "--bin", str(ROOT / "data" / "roster_build" / "payload_proa.bin"), "--card", a.card)
    print("\nDone. Review data/roster_build/report.md and docs/_face_sheets/, press F10 in PCSX2 to reload textures.")
    if a.iso_out:
        print(f"Portable roster/logo ISO written to {a.iso_out}. Boot fresh without loading an old roster or savestate; "
              "F10 does not reload embedded assets. Disable old logo replacements to inspect the ISO result.")
    if not a.card:
        print("Card not written (no --card given).")


if __name__ == "__main__":
    main()
