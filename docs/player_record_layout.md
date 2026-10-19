# Player record layout (0x94 bytes, table at payload 0x64F4)

Decoded by matching the in-game ratings of Allen Iverson (record 0) and Glenn Robinson (record 2)
(filled in `docs/manual/manual_checks.xlsx`) and by statistics over all 567 roster records.
`scripts/build_roster.py` writes the fields marked **W**.

| Off | Size | Meaning | |
|---|---|---|---|
| 0x0C | ptr | last name | W |
| 0x10 | ptr | first name | W |
| 0x14 | u16 | unknown id (0-59) | |
| 0x16 | u8 | jersey number | W |
| 0x17 | u8 | position 0=PG 1=SG 2=SF 3=PF 4=C | W |
| 0x24 | ptr | nickname string (may be empty) | W (set empty) |
| 0x28 | ptr | birthday string `m/d/yy` | W |
| 0x2D | u8 | index in team roster (0-4 starters), 0xFF otherwise | |
| 0x2E | u8 | **handedness**: 1 = right-handed, 0 = left-handed (user finding, boolean) | W |
| 0x30 | u8 | blocking/rebounding/dunking-type trait; big centers ~90, speedy guards ~70; correlates with height (r=0.93, `0.9856*height_in+0.70`) | W (from height) |
| 0x32 | u8 | "fame" indicator, 10 (low) to ~40-44 (superstars); mapped from overall percentile | W (from overall) |
| 0x31 | u8 | height in inches (73 = 6'1") | W |
| 0x34 | u16 | weight in lb | W |
| 0x41 | u8 | years pro | W |
| 0x45 | u8 | Shot Close | W |
| 0x46 | u8 | Shot Med | W |
| 0x47 | u8 | Shot 3pt | W |
| 0x48 | u8 | Free Throw | W |
| 0x49 | u8 | Layup | W |
| 0x4A | u8 | Dunk | W |
| 0x4C | u8 | tier 0/50/99, correlates with dunk (r=0.69) | W (heuristic) |
| 0x4D | u8 | Ball Handling | W |
| 0x4E | u8 | Pass | W |
| 0x4F, 0x55 | u8 | tier 50/75/99, unknown (r~0.6 with average rating) | W (50) |
| 0x50 | u8 | unknown, 50-99 (Iverson 99) | W (70) |
| 0x51 | u8 | Low Post Offense | W |
| 0x52 | u8 | Low Post Defense | W |
| 0x53 | u8 | Block | W |
| 0x54 | u8 | Steal | W |
| 0x56 | u8 | Offensive Rebounding | W |
| 0x57 | u8 | Defensive Rebounding | W |
| 0x58 | u8 | Speed | W |
| 0x59 | u8 | Stamina | W |
| 0x5A | u8 | unknown 0-15 | W (0) |
| 0x5B | u8 | Durability | W |
| 0x5C | u8 | unknown (r=-0.68 with average rating, draft-like) | W (60) |
| 0x5D | u8 | Defensive Awareness | W |
| 0x5E | u8 | Offensive Awareness | W |
| 0x5F, 0x60 | u8 | unknown (75/99, 75/85/95) | W (75) |
| 0x69 | u8 | **skin tone 0-5**: selects the `legs00`-`legs05` texture (arm colour correlates r=0.985). Face/neck/arm follow the pid, so cast players get the tone of the borrowed model | W |

### Accessories (verified in game through the memory card)

The accessories are record bytes (not part of the pid model): they stay when the model is swapped, and `0` = none (`0x67`: 255 = none). Live RAM patching after `set_roster` is ignored by the game, so test only via the card (`scripts/acc_card_test.py` is the test harness).

| offset | meaning | values seen in game |
|---|---|---|
| 0x67 | **headband on** (0 = on, 255 = off) | |
| 0x62 | headband style (needs 0x67 = 0; alone it shows nothing) | 0 normal, 2 slightly larger; 4/5 untested |
| 0x75 | left wrist (player's left) | 7 wristband, 3 long forearm tape |
| 0x76 | right wrist | same items |
| 0x77 | left upper arm / elbow | 11 small band above the elbow, 6 large elbow brace |
| 0x78 | right upper arm / elbow | 11 small band (6 not tested on the right) |
| 0x79 / 0x7A | left / right, another slot: 7 shows a band above the elbow (looks like 0x77/0x78 = 11) | not exposed |
| 0x7E | left knee | 14 small knee tape (6 not tested on the left) |
| 0x7F | right knee | 14 small tape, 6 best-looking knee brace, 10 small brace |
| 0x61, 0x62 = 5 | nothing visible in the tests | |
| 0x64-0x66 | NBA only: 0x64/0x65 = 9 on the 80's Celtics (historic teams?), 0x66 = goggles index (`goggles00`-`07`) | not used |

Items are indices into one shared pool of model parts (`wristitem01-17`, `armitem01-03`, `elbowitem01-03`, `kneeitem01-04`, `legitem01-03`, `headitem02-33`), so other numbers (2-20 occur in the NBA data) give other looks; use the raw number in `data/accessories.csv` to try them.

`build_roster.py` clears all of these bytes for every ProA player (NBA records have their own accessories) and then applies `data/accessories.csv` (key `proa_id`; new players are appended with empty cells, existing rows are never overwritten, so hand edits survive re-scrapes). Columns: `headband` (1 normal, 2 larger), `wrist_l/r`, `arm_l/r`, `knee_l/r` (1 or 2 = presets from the table above: wrist 7/3, arm 11/6, knee 14/6; any number >= 3 is written raw as item index; blank/0 = none).

"Overall" is not a stored byte that matches (0x60 is close but not equal); it is probably computed.
Ratings are 0-99 bytes (NBA data is quantised to steps of 5, any value should be valid).

Only the first four string pointers (0x0C, 0x10, 0x24, 0x28) are real pointers in the player table;
other words that look like pointers (e.g. 0x14..0x17) are false positives and are ignored by
`build_roster.py`.

Rating conversion from the 2K26-style `proa_scraped.xlsx` columns is a placeholder in
`scripts/rating_map_2k5.py`. Units in the source: height in m, weight in kg.
