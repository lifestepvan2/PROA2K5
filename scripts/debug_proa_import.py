"""
Standalone debug / dry-run tool for ProA roster import.

Connects to the running game (or works offline for sheet-matching checks),
then runs import_proa_roster with verbose=True, dry_run=True and prints
the full diagnostics without writing anything.

Usage:
    python scripts/debug_proa_import.py proa_rosters.xlsx [--write]

    --write   Actually apply the import (still shows verbose diagnostics first).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make sure the repo root is on the path when invoked as a plain script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from nba2k_editor.core.config import MODULE_NAME
from nba2k_editor.core.offsets import initialize_offsets, MAX_PLAYERS
from nba2k_editor.memory.game_memory import GameMemory
from nba2k_editor.models.data_model import PlayerDataModel


def _hr(char: str = "-", width: int = 60) -> str:
    return char * width


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Debug / dry-run ProA roster import.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ap.add_argument("workbook", help="Path to the ProA roster .xlsx file.")
    ap.add_argument(
        "--write",
        action="store_true",
        help="Apply changes to live memory (default: dry-run only).",
    )
    ap.add_argument(
        "--no-verbose",
        action="store_true",
        help="Skip per-sheet debug output (just print summary).",
    )
    args = ap.parse_args()

    workbook = Path(args.workbook)
    if not workbook.is_file():
        print(f"ERROR: file not found: {workbook}")
        sys.exit(1)

    verbose = not args.no_verbose
    dry_run = not args.write

    # ── Load offsets ──────────────────────────────────────────────────────
    print(_hr())
    print("Loading offsets...")
    try:
        initialize_offsets()
    except Exception as exc:
        print(f"WARNING: offset init raised {exc!r} -- continuing anyway")

    # ── Connect to game ───────────────────────────────────────────────────
    print("Connecting to game process...")
    mem = GameMemory(MODULE_NAME)
    game_running = mem.open_process()
    if not game_running:
        print("WARNING: NBA 2K26 process not found.")
        print("         Sheet-name matching will still be checked.")
        print("         Player-slot diagnostics will be empty (no players in memory).")
    model = PlayerDataModel(mem, max_players=MAX_PLAYERS)
    if game_running:
        print("Connected.  Refreshing players...")
        try:
            model.refresh_players()
            print(f"         {len(model.players)} player(s) loaded.")
        except Exception as exc:
            print(f"WARNING: refresh_players raised {exc!r}")

    # ── Import dry-run ────────────────────────────────────────────────────
    from nba2k_editor.importing.excel_import import import_proa_roster

    print()
    print(_hr())
    mode_label = "DRY-RUN" if dry_run else "LIVE WRITE"
    print(f"Running import [{mode_label}]  verbose={verbose}")
    print(f"Workbook: {workbook}")
    print(_hr())

    result = import_proa_roster(
        model,
        workbook,
        dry_run=dry_run,
        verbose=verbose,
    )

    # ── Print debug_info ──────────────────────────────────────────────────
    if result.debug_info:
        print()
        print("=== DEBUG INFO ===")
        for line in result.debug_info:
            print(line)

    # ── Print warnings / errors ───────────────────────────────────────────
    if result.warnings:
        print()
        print("=== WARNINGS ===")
        for w in result.warnings:
            print(f"  ! {w}")

    if result.errors:
        print()
        print("=== ERRORS ===")
        for e in result.errors:
            print(f"  !! {e}")

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    print(_hr("="))
    print(result.summary_text())
    print(_hr("="))

    if result.teams_skipped:
        print()
        print("TIP: For each skipped sheet, check that the sheet name (lowercased)")
        print("     exactly matches one of these patterns from team_mapping.json:")
        print("       <team_name>          e.g. 'dragons'")
        print("       <city_name>          e.g. 'artland'")
        print("       <city_name> <team_name>  e.g. 'artland dragons'  <- default export format")
        print("       <team_id> (integer)  e.g. '38'")

    sys.exit(1 if result.errors else 0)


if __name__ == "__main__":
    main()
