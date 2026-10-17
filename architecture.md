# PS2 2K5 architecture plan

## Objective
Port the reusable part of the 2K26 editor stack to a PS2 emulation workflow for NBA 2K5, while keeping the data generation pipeline frozen to the last known good cache.

## Layer 1: data pipeline
The 2K26 project already includes a roster-and-attribute generation pipeline that is useful as-is:
- `scripts/scrape_proa_roster.py` scrapes the data source and caches HTML/JSON.
- `scripts/proa_attr_model.py` derives player ratings from scraped stats.
- `nba2k_editor/importing/excel_import.py` defines the import/export schema for the generated roster workbook.
- `docs/proa_field_re.md` documents what actual game fields the export corresponds to.

This layer is the most reusable piece and we are treating the existing `.xlsx` outputs as the source of truth until a PS2-specific memory map is established.

## Layer 2: static data assets
The project also reuses the static mapping artifacts already captured from the neighboring repo:
- `nba2k_editor/assets/team_mapping.json`
- `nba2k_editor/assets/proa_headshot_map.json`
- `nba2k_editor/Offsets/` for schema templates, import spreadsheets, and reference mappings

These are not regenerated; they are kept as cached artifacts for the 2K5 port.

## Layer 3: live-memory attachment to PCSX2
The immediate PCSX2 work is not a direct port of the Win32 game-memory layer. The PS2 emulator runs a separate process hosting the guest machine.

Planned steps:
1. Identify the actual `pcsx2.exe` process instance for the NBA 2K5 game.
2. Attach with a Windows memory reader using `OpenProcess` / `ReadProcessMemory`.
3. Validate whether the game data is stored in the emulator process heap or exposed through emulator debugging APIs.
4. Build a pointer-chain scanner and value maps against the guest PS2 memory layout.
5. Only then begin the initial write-back manipulations.

## Layer 4: future manipulation loop
Once the emulator memory layout is understood, the plan is to mirror the 2K26 pipeline:
- import data from the cached roster files
- map those values to live PS2 memory addresses
- patch the current game state
- verify in emulation with minimal read/write loops

## Current working assumption
This repo is intentionally in a frozen, cached-data, pre-RE phase. The next work is memory attach and scan planning, not a new data generation pass.
