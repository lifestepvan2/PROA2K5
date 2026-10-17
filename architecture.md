# PS2 2K5 architecture

## Objective
Turn ESPN NBA 2K5 (PS2, PCSX2) into a ProA game: replace team/player names, lineup textures and ratings
with the current ProA roster, reproducibly for each new roster.

## Layer 1: data pipeline (frozen, cached)
- `scripts/scrape_proa_roster.py` / `scripts/proa_attr_model.py` produced `proa*.xlsx` (not rerun).
- `nba2k_editor/assets/team_mapping.json`, `proa_headshot_map.json` - cached mappings.
- TODO: replace photoshop batch edit step (for cropping original player portraits to auto-select the face) with a python script

## Layer 2: game data formats (reverse engineered, see `docs/`)
- Roster save on the memory card (`/BESLES-53022Roster1/`): uncompressed heap snapshot with
  self-relative pointers, UTF-16LE string pool, CRC32 in `EXTRA` (`docs/roster_budget_plan.md`).
- Textures: PCSX2 texture replacement keyed by dump hashes (`docs/pcsx2_texture_mapping.md`).

## Layer 3: tooling
- Card: `mc_inspect.py` (read), `mc_write.py` (in-place write with ECC), `build_roster.py` (planned: payload builder).
- Live: PINE/ReadProcessMemory RAM access, keyboard input and screen capture for verification (`docs/poc_findings.md`).

## Layer 4: workflow
ProA data -> build roster payload (names/teams, later ratings) -> write card -> load in game ->
verify via screenshots/RAM -> generate texture replacements.
