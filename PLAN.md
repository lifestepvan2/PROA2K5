# ProA on NBA 2K5 (PS2) - plan and todo list

Workflow: `scripts/build_roster.py` builds a roster payload from `proa_scraped.xlsx` and writes it to the
virtual memory card; load it in-game (Load/Save > Roster1). Details: `docs/roster_payload_format.md`,
`docs/player_record_layout.md`, `docs/roster_budget_plan.md`.

## Done
- [x] Data pipeline and cached data copied over; PCSX2 attach/inspection (PINE, RAM, screenshots, key input)
- [x] Memory card roster read/write (in place, ECC + CRC)
- [x] Team names/abbreviations/cities, player names (relocated strings, longer names work)
- [x] Rosters and starters for 18 ProA teams in NBA slots 12-29 (final mapping `data/team_slots.csv`; Falcons = Pistons slot 21, Gottingen = Lakers slot 15, so the default Quick Match is a full ProA game)
- [x] Jersey, position, height, weight, years pro, birthday, 19 ratings written and verified in-game (ratings confirmed correct)

- [x] Home arena names: venue table in the payload (rows keyed by `sNNN` = team slot), `data/proa_arenas.csv`, built by `build_roster.py` (see `docs/roster_payload_format.md`); live RAM patch verified, card write pending a roster rebuild

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
- [x] Starter faces (90, 18 teams): superseded by `record_faces.csv` (`starter_faces.csv` is stale), `scripts/gen_replacements.py`
- [x] Small team icons on Start Game (32x32 `-00001553`): `data/texture_map/team_icons.csv` keyed by NBA slot, all 30 slots mapped (scores 0.90-0.99)
- [x] Bench faces (all 269 players): `data/texture_map/record_faces.csv` via live injection scan, record allocation in `build_roster.py`, spot-checked in-game (see `docs/pcsx2_texture_mapping.md`)
- [ ] Verify shrunken donor teams (NBA slots 0-11) in-game, and low-score matches (records 70, 103, 231) - low prio
- [ ] in-game player faces (and body textures) - figure out existing mapping and work on re-mapping (by figuring out visual matches) as a first step. replacement file generation down the line.
- [x] Team logo variants on Team Select, courts, scoreboards, pre-game banner (`00002213` / `00001993` / `00001dd3`): 108 variants across all ProA slots, found by template matching (`scripts/build_logo_map.py` -> `data/texture_map/logo_variants.csv`, `scripts/gen_logo_replacements.py`). Verified in-game: Team Select and banner for BG/Falcons. Only variants that have been rendered/dumped exist; more dumps (e.g. playing a game per team) -> re-run both scripts
- [ ] Logo atlases (256x256 `2213` collages, 512x512 `2653` grids of NBA logos, in-game jumbotron/court signs) are not handled automatically (need multi-ref masked matching + compositing); use the workspace
- [ ] Cavaliers wordmark is split over two textures (`PARTIAL_REFS`); needs a composite reference. Logos inside arena signs (mode B matches) and team-name wordmarks are not handled automatically; use the workspace
- [x] Manual replacement workspace (`scripts/texture_workspace.py`, folder `texture_workspace/`, gitignored): dumps grouped into named folders, edits synced back resized to the original resolution; pipeline-managed textures always win. Alpha convention verified in-game (see `docs/pcsx2_texture_mapping.md`)
- [x] Uniform LODs: 16x8/32x16/64x32/128x64 uniforms and duplicate 512x256 files matched to MASTER textures (`scripts/uniform_lods.py`, `data/uniform_lods/mapping.csv`); `texture_workspace.py sync` generates all copies and LODs from the MASTER (see `docs/pcsx2_texture_mapping.md`)
- [x] Folder-based sorting of the uniform LOD mapping (`scripts/uniform_sort.py populate|apply`, `texture_workspace/uniforms/visual_sort/`, result in `data/uniform_lods/sorted.csv`); step-by-step in `docs/JerseyTextureWorkflow.md`
- [ ] Workspace follow-ups: name the 12 donor teams' wordmarks, re-run `texcluster.py fit` + rename clusters when many new dumps arrive, jersey name plates (`0d93`/`11d3`/`1613`) from ProA names, team jerseys/colours (`2253` = full jerseys)
- [x] Team mapping is final (`data/team_slots.csv`). `record_faces.csv` is record-keyed, icons/logos are keyed by NBA slot: no re-scan needed when the ProA order changes, only re-run the generators. More logo variants need more dumps (only rendered textures exist)- [ ] Face crop (`CROP` in gen_replacements.py) is a fixed head+shoulders box; check a few headshots for badly framed faces
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
- [x] Default matchup (Lakers at Pistons) is a full ProA game: Gottingen at Falcons (ProA teams moved to slots 12-29)

### release
- [ ] re-scrape online data for 2026/27 season, update textures of new teams. 
- [ ] manual refinement pass over player attributes
- [ ] manual editing of Falcons home court (texture, via the workspace)
- [ ] verify the arena names in `data/proa_arenas.csv` (only the Falcons entry is confirmed; rest are best guesses, flag `verified`)
- [ ] re-do player face mapping
- [ ] rollout and test

### Nice-to-have (last)
- [ ] Fill the remaining 12 NBA team slots (0-11, now the donor teams) with filler/other teams; handle all-star/legend teams referencing NBA 
records
- [ ] create a pipeline to generate in game player face assets from our portrait database
## out of scope:
- sound replacements
