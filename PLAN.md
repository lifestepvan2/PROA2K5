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
- [ ] Check whether in-game "Overall" is computed or stored; birthday/years pro display check (player card)
- [ ] Years pro: currently estimated from the birth year

### Textures
- [ ] Map player record / team to texture keys (face 128x128 family `00001dd3`, logos `00002213`), see `docs/pcsx2_texture_mapping.md`
- [ ] Generate replacement PNGs from `assets/PS_out`, headshot map and logo map; install in PCSX2 `textures\SLES-53022\replacements`
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

### Nice-to-have (last)
- [ ] Fill the remaining 12 NBA team slots (18-29) with filler/other teams; handle all-star/legend teams referencing NBA records
