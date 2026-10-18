# ProA on NBA 2K5 (PS2) - plan and todo list

Workflow: `scripts/build_roster.py` builds a roster payload from `proa_scraped.xlsx` and writes it to the
virtual memory card; load it in-game (Load/Save > Roster1). Details: `docs/roster_payload_format.md`,
`docs/player_record_layout.md`, `docs/roster_budget_plan.md`.

## Done
- [x] Data pipeline and cached data copied over; PCSX2 attach/inspection (PINE, RAM, screenshots, key input)
- [x] Memory card roster read/write (in place, ECC + CRC)
- [x] Team names/abbreviations/cities, player names (relocated strings, longer names work)
- [x] Rosters and starters for 18 ProA teams in NBA slots 0-17
- [x] Jersey, position, height, weight, years pro, birthday, 19 ratings written and verified in-game (ratings confirmed correct)

## Todo
### Attributes / ratings
- [ ] **Lift the low end of the rating scale.** 2K5 shows values below 50 clipped at 50 (observed in game); the
      ProA data has many values 45-60. When generating 2K5 attributes, rescale so the ProA range maps
      into roughly 50-99 (or 55-99) instead of clipping. Check `rating_map_2k5.py`.
- [ ] Rework the skill/attribute estimation step to output the 19 2K5 attributes directly
      (Shot Close/Med/3pt, FT, Layup, Dunk, Ball Handling, Pass, Low Post Off/Def, Block, Steal, Off/Def Reb,
      Speed, Stamina, Durability, Def/Off Awareness) and one-time convert the existing dataset
- [ ] **Decode the hidden/unknown player record bytes using the NBA default export.** Data:
      `data/nba_defaults/players_unknown.csv` (792 records, 575 on teams, 51 non-constant unknown byte columns
      `uXX` next to name, team, birthday, jersey, position, height, weight, years pro) and `teams_unknown.csv`,
      exported from the freshly reset default roster with `scripts/export_unknown_attrs.py`. Method: correlate
      each column with real-life data (draft year/pick, minutes, usage, stats, awards, tendencies, handedness,
      signature styles, contract, etc.) and with the known ratings; tiered columns (0/50/99, 50/75/99) look like
      tendency/skill-tier flags. Until decoded, `build_roster.py` writes neutral values for 0x4C/0x4F/0x50/0x55/
      0x5A/0x5C/0x5F/0x60 and ProA players inherit the NBA slot's bytes for the rest (u00-u0a, u14, u2c-u30, u32,
      u3c-u44, u61-u67, u69, u75-u7f, u83-u85, u8e-u92), which should be reset/overwritten once understood.
      Findings so far (user, from the export): **u2e = handedness** (1 right, 0 left), **u30 = height-correlated
      big-man trait** (~70 guards to ~90 centers), **u32 = fame** (10..~44, superstars highest). Many of the
      remaining bytes are probably equipment (sleeves, shoes, bands, ...) or animation indexes; animation
      indexes could be found by correlating columns with position.
- [ ] **Add a "Right Handed" (or "Handedness") column to the ProA database** for u2e. Not public information, so it
      will be filled by manual edits only; `build_roster.py` reads an optional `Right Handed` column
      (0/L = left) and defaults to right-handed. u30 is generated from height and u32 from the overall percentile
      (see `write_record_fields`).
- [ ] Check whether in-game "Overall" is computed or stored; birthday/years pro display check (player card)
- [ ] Years pro: currently estimated from the birth year

### Textures
Method: `docs/pcsx2_texture_mapping.md` (screenshot the Start Game screen per team, match crops offline against the dump folder).
- [x] Starter faces (90, 18 teams): `data/texture_map/starter_faces.csv`, `scripts/gen_replacements.py`, verified in-game
- [x] Small team icons on Start Game (32x32 `-00001553`): `data/texture_map/team_icons.csv`, verified in-game
- [x] Bench faces (all 269 players): `data/texture_map/record_faces.csv` via live injection scan, record allocation in `build_roster.py`, spot-checked in-game (see `docs/pcsx2_texture_mapping.md`)
- [ ] Verify shrunken donor teams 18-22 (7-9 players) in-game, and low-score matches (records 70, 103, 231) - low prio
- [ ] in-game player faces (and body textures) - figure out existing mapping and work on re-mapping (by figuring out visual matches) as a first step. replacement file generation down the line.
- [ ] Large team logos and jerseys (Team Select, scoreboards, court): `00002213` family etc.
- [ ] create a workflow allowing for systematic, part automated, part manual, asset replacement. e.g. by creating a mirrored folder with a good, readable structure (clustering and labelling assets by group - e.g. a folder "sponsor logos", a folder "jerseys"...) where the user can replace dumped image files with any image (using the same name), then the pipeline crops it to the right dimensions and routes it back to the live replacement folder
- [ ] Re-run the scan whenever the roster slot order changes; `replacements\` must be empty during a scan
- [ ] Face crop (`CROP` in gen_replacements.py) is a fixed head+shoulders box; check a few headshots for badly framed faces
- [ ] Team jerseys/colours (optional)

### Roster/data quality
- [ ] Duplicate player: Lars Lagerpusch is on Falcons and Baskets in the source data (stale row?)
- [ ] Two teams named "Baskets" (Koblenz, Paderborn); consider disambiguating
- [ ] Review name shortening rules / overrides (`data/overrides.csv`); umlaut glyph support untested
- [ ] Spare player records (482+) used for 15-man rosters: check conflicts with all-star teams
- [ ] Nicknames are blanked; birthday display untested

### Automation / tooling
- [ ] Player card cannot be opened via keyboard (Select = Backspace not working); verify other bindings
- [ ] Restore the SDL pad bindings in `PCSX2.ini` when automation is done (`docs/pad1_sdl_backup.txt`)
- [ ] Replace the photoshop batch step (cropping portraits) with a python script (see `architecture.md`)
- [ ] CRC/ECC experiments (E3), glyph-set test (E5)

### QOL
- [ ] make the default matchup (Lakers at Pistons) be a full ProA game. e.g. by shifting the overwritten teams from slots 1-18 to slots 12-30 instead

### Nice-to-have (last)
- [ ] Fill the remaining 12 NBA team slots (18-29) with filler/other teams; shift the teams handle all-star/legend teams referencing NBA 
records
- [ ] create a pipeline to generate in game player face assets from our portrait database
## out of scope:
- sound replacements
