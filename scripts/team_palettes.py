"""Shared per-team colour documents and explicit legacy-workspace migration."""
import argparse
import csv
import json
import shutil
from pathlib import Path

from lettering_colours import parse_hex, validate_controls

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WS = ROOT / "texture_workspace" / "team_palettes"
TEAM_FIELDS = ("colorjersey1", "colorjersey2", "colorui1", "colorui2")


def relative(slot: int) -> Path:
    if type(slot) is not int or slot not in range(30):
        raise ValueError("NBA slot must be an integer in 0-29")
    return Path(f"{slot:03}") / "colours.json"


def validate(value: object) -> dict:
    if (not isinstance(value, dict) or set(value) != {"schema", "team", "uniforms", "court"}
            or type(value["schema"]) is not int or value["schema"] != 1):
        raise ValueError("Team colours require schema 1, team, uniforms and court")
    if not isinstance(value["team"], dict) or set(value["team"]) != set(TEAM_FIELDS):
        raise ValueError("team requires colorjersey1, colorjersey2, colorui1 and colorui2")
    for colour in value["team"].values():
        parse_hex(colour)
    if not isinstance(value["uniforms"], dict) or not value["uniforms"]:
        raise ValueError("uniforms requires at least one uniform variant")
    for variant, controls in value["uniforms"].items():
        if variant not in ("home", "away", "alt"):
            raise ValueError(f"Unknown uniform variant {variant!r}")
        validate_controls({"schema": 1, **controls} if isinstance(controls, dict) else controls)
        if set(controls) != {"numbers", "names"}:
            raise ValueError(f"{variant}: expected numbers and names")
    court = value["court"]
    if (not isinstance(court, dict) or set(court) != {"mode", "primary", "secondary", "lines"}
            or court["mode"] not in ("original", "recolour")):
        raise ValueError("court requires mode (original/recolour), primary, secondary and lines")
    for field in ("primary", "secondary", "lines"):
        parse_hex(court[field])
    return value


def load(workspace: Path, slot: int) -> dict:
    path = workspace / relative(slot)
    try:
        return validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError) as error:
        raise ValueError(f"{path}: {error}") from error


def team_colours(workspace: Path, slot: int) -> dict[str, str]:
    return load(workspace, slot)["team"]


def defaults(slot: int, uniforms: dict) -> dict:
    # New exports inherit the canonical team colours, not stale metadata CSV fields.
    canonical = DEFAULT_WS / relative(slot)
    if canonical.exists():
        team = team_colours(DEFAULT_WS, slot)
    else:
        with (ROOT / "data" / "nba_defaults" / "teams_unknown.csv").open(encoding="utf-8") as file:
            row = next(row for row in csv.DictReader(file) if int(row["slot"]) == slot)
        ui = ["#" + "".join(f"{int(row[f'b{offset:x}']):02X}" for offset in range(start, start + 3))
              for start in (0x62, 0x65)]
        team = dict(zip(TEAM_FIELDS, ui + ui))
    from court_colours import default_controls, source_catalogue
    arena = source_catalogue()["arenas"][slot]
    return validate({"schema": 1, "team": team, "uniforms": uniforms,
                     "court": default_controls(arena)})


def migrate(source: Path, destination: Path, teams: Path, slots: Path) -> None:
    if source.resolve() == destination.resolve() or destination.exists():
        raise ValueError("Migration destination must be a new directory")
    with slots.open(encoding="utf-8") as file:
        mapping = {row["sheet"]: int(row["nba_slot"]) for row in csv.DictReader(file)}
    with teams.open(encoding="utf-8") as file:
        metadata = {mapping[row["sheet"]]: row for row in csv.DictReader(file)}
    documents = {}
    old_paths = []
    for slot in range(30):
        variants = {}
        for path in sorted((source / f"{slot:03}").glob("*/colours.json")):
            controls = validate_controls(json.loads(path.read_text(encoding="utf-8")))
            variants[path.parent.name] = {key: controls[key] for key in ("names", "numbers")}
            old_paths.append(path.relative_to(source))
        if not variants:
            raise ValueError(f"Slot {slot}: no legacy uniform controls to migrate")
        config = defaults(slot, variants)
        if slot in metadata:
            config["team"] = {field: metadata[slot][field] for field in TEAM_FIELDS}
        documents[relative(slot)] = validate(config)
    # Renaming preserves all swatches, previews, originals and the source manifest.
    copied = False
    try:
        source.rename(destination)
    except PermissionError:
        print("Directory rename is locked; copying and verifying files before retiring the old workspace.")
        shutil.copytree(source, destination)
        for path in source.rglob("*"):
            if path.is_file() and path.read_bytes() != (destination / path.relative_to(source)).read_bytes():
                raise ValueError(f"Migration copy differs: {path}")
        copied = True
    for path, config in documents.items():
        (destination / path).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    for path in old_paths:
        (destination / path).unlink()
    if copied:
        for path in source.rglob("*"):
            if path.is_file():
                path.unlink()
        for path in sorted((path for path in source.rglob("*") if path.is_dir()),
                           key=lambda path: len(path.parts), reverse=True):
            path.rmdir()
        try:
            source.rmdir()
        except PermissionError:
            print(f"Empty old directory remains locked: {source}")
    print(f"Migrated 30 teams and {len(old_paths)} uniform variants to {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("migrate",))
    parser.add_argument("--source", type=Path, default=ROOT / "texture_workspace" / "lettering")
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WS)
    parser.add_argument("--teams", type=Path, default=ROOT / "data" / "proa_teams.csv")
    parser.add_argument("--slots", type=Path, default=ROOT / "data" / "team_slots.csv")
    args = parser.parse_args()
    try:
        migrate(args.source, args.workspace, args.teams, args.slots)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Migration refused: {error}\n")


if __name__ == "__main__":
    main()
