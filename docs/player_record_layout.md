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

### Accessory candidates (NOT confirmed)

In the NBA data bytes 0x61-0x67 default to 255 ("none") and look like item indices; most other bytes up to 0x94 are 0 for all 792 records.

| offset | NBA values | observation |
|---|---|---|
| 0x61 | 255, 2/6/7/8/10/14 | 6 on Bird/McHale (80's East) |
| 0x62 | 0, 2/4/5 | 2 on Iverson, Person, Thomas, Odom, Livingston; 5 on Maggette, Malone; 4 on Traylor (sleeve-like wearers?) |
| 0x64, 0x65 | 255, 9 (Iverson A-T: 5, 12) | 9/9 on the 80's Celtics |
| 0x66 | 255, 0-6 | only players known for goggles/glasses (Kareem, Worthy, Mikan, Horace Grant, Outlaw): goggles index (`goggles00`-`07` TXTRs exist in RAM) |
| 0x67 | 255, 0 | 0 on Iverson, Maggette |
| 0x75-0x7A, 0x7E, 0x7F | see `players_unknown.csv` | pairs of equal values (left/right?) |

Live test (PCSX2, savestate -> `set_roster` -> patch record bytes -> start game, 3 runs, ~24 players each): setting 0x75-0x7A=6, 0x64/0x65=9 + 0x66=3, and 0x61=6 + 0x62=2 + 0x69=5 on every record changed **nothing** on screen (not even the known-good skin byte 0x69), so patching records after `set_roster` is ignored by the game (records are probably copied earlier). Headbands, wristbands and knee sleeves seen in game on cast ProA players (all records identical in these bytes) come from the cast NBA model/textures, not from these bytes. The candidates above therefore need to be tested through the memory card (`build_roster.py`) before being exposed in the roster sheet. Model sub-object names that the indices probably select: `wholeheaditem02-33`, `neckitem01-18`, `faceitem02-26`, `headitem02-33`, `armitem01-03`, `wristitem01-17`, `elbowitem01-03`, `kneeitem01-04`, `legitem01-03`.

"Overall" is not a stored byte that matches (0x60 is close but not equal); it is probably computed.
Ratings are 0-99 bytes (NBA data is quantised to steps of 5, any value should be valid).

Only the first four string pointers (0x0C, 0x10, 0x24, 0x28) are real pointers in the player table;
other words that look like pointers (e.g. 0x14..0x17) are false positives and are ignored by
`build_roster.py`.

Rating conversion from the 2K26-style `proa_scraped.xlsx` columns is a placeholder in
`scripts/rating_map_2k5.py`. Units in the source: height in m, weight in kg.
