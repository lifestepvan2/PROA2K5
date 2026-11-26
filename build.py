"""Build a portable ProA ISO from the current workbook and native texture workspace."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

import portrait_iso
import season_iso
import skin_tones
import texture_iso_workspace

SOURCE = Path(r"C:\Tools\isos\ESPN NBA 2K5 (Europe).iso")
OUTPUT_DIR = Path(r"C:\Tools\isos")
SEASON = "2026_2027"
ROSTER = ROOT / "data" / "roster_build" / "payload_proa.bin"


def run(script: str, *args: str) -> None:
    print("\n>>", script, *args, flush=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args], cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=SEASON, help="season in consecutive YYYY_YYYY form")
    parser.add_argument("--card", type=Path, help="optionally export the finished roster to a memory card")
    parser.add_argument("--rematch-faces", action="store_true", help="redo automatic face matches")
    args = parser.parse_args()
    years = args.season.split("_")
    if (len(years) != 2 or not all(len(year) == 4 and year.isdecimal() for year in years)
            or int(years[1]) != int(years[0]) + 1):
        parser.error("--season must be consecutive YYYY_YYYY years")
    workspace = texture_iso_workspace.DEFAULT_WS
    palettes = workspace / "team_palettes"
    if not SOURCE.is_file():
        parser.error(f"Pristine ISO not found: {SOURCE}")
    if args.card:
        running = subprocess.run(["tasklist", "/FI", "IMAGENAME eq pcsx2-qt.exe"],
                                 capture_output=True, text=True, check=True)
        if "pcsx2" in running.stdout.lower():
            parser.error("Close PCSX2 before writing its memory card")
    for filename in ("_iso_logos.json", "_iso_uniforms.json", "_iso_textures.json"):
        if not (workspace / filename).is_file():
            parser.error(f"Missing native workspace manifest: {workspace / filename}")
    print("Warning: automatic light-reserve recolouring is not yet migrated to the ISO; "
          "only explicit Skin Tone overrides are generated.", flush=True)
    run("player_database.py")
    run("crop_headshots.py", "--season", args.season)
    roster_args = ("--season", args.season, "--iso-source", str(SOURCE), "--team-palettes", str(palettes))
    run("build_roster.py", *roster_args, "--prepare-faces")
    run("face_embed.py")
    run("face_match.py", *(["--rematch"] if args.rematch_faces else []),
        "--iso-source", str(SOURCE), "--repack-archive")
    run("build_roster.py", *roster_args)
    with SOURCE.open("rb") as stream:
        skins = skin_tones.populate_workspace(stream, workspace)
    print(f"Updated {skins['masters']} skin texture masters for {skins['players']} players.", flush=True)
    portraits = portrait_iso.populate(ROSTER, workspace)
    for key in ("missing_headshots", "suppressed_portraits"):
        if portraits[key]:
            print(f"Warning: {key}: {', '.join(map(str, portraits[key]))}", flush=True)
    print(f"Updated {portraits['generated']} portraits and {portraits['placeholders']} placeholders.", flush=True)
    report = season_iso.build_named(SOURCE, OUTPUT_DIR, ROSTER, palettes, stats_year=int(years[0]),
                                    skin_plan=skin_tones.PLAN, texture_workspace=workspace)
    if args.card:
        run("card_patch.py", "--bin", str(ROSTER), "--card", str(args.card))
    print(f"\nBuilt {report['output']} (build 0x{report['build_id']['value']})")


if __name__ == "__main__":
    main()
