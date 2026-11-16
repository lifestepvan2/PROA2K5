# Player record layout (0x94 bytes, table at payload 0x64F4)

Decoded by matching the in-game ratings of Allen Iverson (record 0) and Glenn Robinson (record 2)
(filled in `docs/manual/manual_checks.xlsx`) and by statistics over all 567 roster records.
The hidden attribute names and byte offsets below were subsequently verified
offline against the pristine Europe executable's label, getter and setter tables;
see [Static attribute probe](#static-attribute-probe-europe-iso).
`scripts/build_roster.py` writes the fields marked **W**.

| Off | Size | Meaning | |
|---|---|---|---|
| 0x00 | ptr | college-table row; its first pointer resolves to the player-card FROM string | W |
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
| 0x4B | u8 | **Dunk Range**; raw value 10 in all 792 main-table stock records; units/effect not established | W (named column; generated 10) |
| 0x4C | u8 | **Standing Dunk**; stock tiers 0/50/99 | W (named column; position/height model) |
| 0x4D | u8 | Ball Handling | W |
| 0x4E | u8 | Pass | W |
| 0x4F | u8 | **Offense Clutch**; stock tiers 50/75/99 | W (named column; FG%/turnover model) |
| 0x50 | u8 | **Shoot or Pass**; stock 50-99 (Iverson 99); behavioral direction not independently traced | W (named column; assists/FGA model) |
| 0x51 | u8 | Low Post Offense | W |
| 0x52 | u8 | Low Post Defense | W |
| 0x53 | u8 | Block | W |
| 0x54 | u8 | Steal | W |
| 0x55 | u8 | **Defense Clutch**; stock tiers 50/75/99 | W (named column; steals/blocks model) |
| 0x56 | u8 | Offensive Rebounding | W |
| 0x57 | u8 | Defensive Rebounding | W |
| 0x58 | u8 | Speed | W |
| 0x59 | u8 | Stamina | W |
| 0x5A | u8 | **Emotion**; raw stock values 0-15; scale/effect not established | W (named column; random 0..5 by default) |
| 0x5B | u8 | Durability | W |
| 0x5C | u8 | **Fouls per Min**; raw stock 20-99; scale not established | W (named column; foul-rate model) |
| 0x5D | u8 | Defensive Awareness | W |
| 0x5E | u8 | Offensive Awareness | W |
| 0x5F | u8 | **Consistency**; raw stock 50-99 | W (named column; age/minutes model) |
| 0x60 | u8 | **Fastbreak**; raw stock 0-95 | W (named column; Speed clamped to 50..99) |
| 0x69 | u8 | **skin tone 0-5**: selects `legs00`-`legs05`. Automatic casting inherits the PID's tone; manual workbook `Skin Tone` 1..6 writes `6 - value` with a matching model-local ISO recipe | W |

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

Items are indices into one shared pool of model parts (`wristitem01-17`, `armitem01-03`, `elbowitem01-03`, `kneeitem01-04`, `legitem01-03`, `headitem02-33`), so other numbers (2-20 occur in the NBA data) give other looks; use the corresponding accessory column in `data/overrides.csv` to try them.

`build_roster.py` clears all of these bytes for every ProA player (NBA records have their own accessories) and then reads the canonical workbook columns. The former `data/accessories.csv` values have been migrated into ID-keyed `data/overrides.csv`; edit only that file for persistent changes. Columns: `headband` (1 normal, 2 larger), `wrist_l/r`, `arm_l/r`, `knee_l/r` (1 or 2 = presets from the table above: wrist 7/3, arm 11/6, knee 14/6; any number >= 3 is written raw as item index; 0 = none). An empty override cell means no override, not removal.

`Shooting Hand` in the workbook writes byte `+0x2E`: 0 = left, 1 = right. It defaults to right until manually overridden. `College` defaults to English country names expanded from the site's `Nat` value (e.g. `Germany / United States`), and writes the player-card FROM label through `+0x00`. A manual College override is literal; `<CLEAR>` produces a valid empty label rather than retaining the inherited college. See [College / FROM labels](roster_payload_format.md#college--from-labels) for table layout and capacity safeguards.

"Overall" is not a stored byte; the game computes it at runtime from the ratings and the player's position.
`scripts/fit_overall.py` fits that formula from displayed values (see "Overall formula" below).
Attributes are stored as unsigned bytes, not packed bitfields. The generic
attribute getter and setter clamp to **50-100**, even though pristine records
contain lower raw values. This does not establish that every gameplay consumer
uses the same clamp or that special fields share a conventional rating scale.
The workbook currently accepts 25-99; this probe did not change that policy.

Only the first four string pointers (0x0C, 0x10, 0x24, 0x28) are real pointers in the player table;
other words that look like pointers (e.g. 0x14..0x17) are false positives and are ignored by
`build_roster.py`.

The 19 rating columns of `proa_scraped.xlsx` are the 2K5 attributes themselves (written by `scripts/proa_attr_model.py`,
overridable via `data/overrides.csv`); `scripts/rating_map_2k5.py` maps column name -> byte offset. The database workflow validates ratings in 25-99 before building.
Units in the source: height in m, weight in kg.

## Static attribute probe (Europe ISO)

This probe used only the pristine ISO and isolated evaluation of its small
attribute getter. It did not launch the game, edit RAM, write a card, or patch
the ISO. Scope: `SLES_530.22`, executable SHA256
`d60570a00122aac72bdf1b7768308f68ddb5a44b091c2251c20891e6c7a47611`.

The ordering clue is confirmed, but with a discrepancy in the external FAQ's
separate **Def (Defense)** entry:

- The native UTF-16 label-pointer table at **EE `0x59EFE8`** has 28 attribute
  names, from Shot-Close through Fastbreak. The diagnostic string after it is
  `PlayerData_GetAttributeStringByType Error`; the name lookup starts at
  **EE `0x2474B8`**.
- The getter at **EE `0x247598`** uses the jump table at **EE `0x59F060`**.
  Enum `i` in `0..27` reads player byte **`0x45 + i`** with `lbu`.
  Enum 28 and out-of-range values return zero, not another stored rating.
- The setter at **EE `0x247960`**, jump table **EE `0x59F0E0`**, independently
  writes the same byte for every enum. All 28 label/getter/setter mappings were
  checked; all 19 previously mapped visible offsets agree.
- Exhaustive isolated evaluation of all 256 possible raw byte values for each
  of the 28 getter cases (7,168 inputs) confirmed `min(100, max(50, raw))`.
  This is evidence about that accessor, not a recommendation to normalize
  special raw values or a complete model of gameplay behavior.

| Hidden field | Enum | Record offset | Getter case EE | Setter case EE |
|---|---:|---|---|---|
| Dunk Range | 6 | `+0x4B` | `0x24768C` | `0x247A90` |
| Standing Dunk | 7 | `+0x4C` | `0x2476AC` | `0x247ABC` |
| Offense Clutch | 10 | `+0x4F` | `0x24770C` | `0x247B40` |
| Shoot or Pass | 11 | `+0x50` | `0x24772C` | `0x247B6C` |
| Defense Clutch | 16 | `+0x55` | `0x2477CC` | `0x247C48` |

For comparison, selected **raw** stock bytes are:

| Player | Dunk Range | Standing Dunk | Offense Clutch | Shoot or Pass | Defense Clutch |
|---|---:|---:|---:|---:|---:|
| Allen Iverson | 10 | 0 | 75 | 99 | 75 |
| Kobe Bryant | 10 | 99 | 99 | 90 | 75 |
| Shaquille O'Neal | 10 | 99 | 99 | 95 | 50 |
| Ben Wallace | 10 | 50 | 50 | 55 | 99 |
| Steve Nash | 10 | 0 | 50 | 60 | 50 |

Four additional formerly unknown fields are directly named by the same tables:
Emotion (`+0x5A`, enum 21), Fouls per Min (`+0x5C`, enum 23), Consistency
(`+0x5F`, enum 26), and Fastbreak (`+0x60`, enum 27).
Their exact effects/scales remain outside this probe.

**No separate Defense attribute exists in this verified 28-entry enum.**
Low Post Defense at `+0x52` is immediately followed by Block at `+0x53`;
there is no byte-sized gap for the FAQ's extra entry. A position-dependent
defensive aggregate routine at EE `0x246EC8` combines Post Defense, Block,
Steal, Defensive Awareness, Defensive Rebound and Speed; it is called alongside
offensive and rebound aggregates in the overall calculation at EE `0x246178`.
That supports a derived-defense interpretation, but does **not** prove that
the FAQ's Def refers to this routine. A distinct attribute elsewhere in the
record has not been demonstrated; do not assign one by shifting known offsets.

Raw ranges here cover the 792 primary stock records, excluding 20 auxiliary
templates. The [stock hidden-attribute CSV](../data/roster_dump/stock_hidden_attributes.csv)
contains all nine fields for each of those records, with a zero-based record
index, PID, names and position. Values are raw bytes, not clamped getter values;
historical, duplicate and placeholder entries are retained.
Machine-readable evidence is generated at
`cache/hidden-rating-probe.json`. All offsets are relative to the existing
`0x94` player record and are unchanged by disc/save header normalization.
The builder now requires all nine named hidden columns and writes their raw
values. Generation rules and manual ranges are documented in
[Season update workflow](SeasonUpdateWorkflow.md#hidden-attributes).
`DunkFlag` and `Bxx` remain legacy calibration aliases, not an alternative
source of silently overriding defaults. New calibration workbooks keep those
aliases equal to their corresponding named columns.

## Overall formula (displayed overall)

The overall shown in game is computed at runtime. Its fitted model uses the
19 visible ratings, primary position, selected hidden fields, height and weight.
Its visible-rating component is
`overall = intercept[pos] + sum(weight[pos][attr] * rating[attr])`, stored in `data/overall_model.json`
(`scripts/overall_model.py: predict_overall`). `build_roster.py` uses it for the `ovr` column of `player_map.csv`,
starter selection and the fame byte.

`proa_scraped.xlsx` shows the prediction as a live **Overall** column (last column of every team sheet, an Excel formula, so
manual edits of ratings or the position recompute immediately). The weights live on the `_Overall_Model` sheet, generated
from `data/overall_model.json` by `scripts/overall_sheet.py`; `fit_overall.py` and the scraper call it, or run
`python scripts/overall_sheet.py` by hand. Do not edit the weights on that sheet - refit instead. Helper sheets starting with
`_` are ignored by `build_roster.py`. The column is for display; `build_roster.py` computes the same value itself.

Re-fit after adding observations (no other input needed):

1. In game, read the overall of players and put it in the `Overall` column of the team sheets in `overall_ratings.xlsx`
   (the file may keep stale columns; only `Overall` and the `ProA ID` column are read). Teams without `Overall` are skipped.
2. The attributes are taken from the current `proa_scraped.xlsx` by ProA ID: it must match what was on the card when the
   values were read (re-check with a dry `build_roster.py` and a card extract if in doubt).
3. `python scripts/fit_overall.py` prints leave-one-out error, weights and the worst residuals and rewrites the model.

Findings with 97 observed players (Dragons, Bremerhaven, Koblenz, Essen, LIONS, Koln, Wolmirstedt, Gottingen):
- the formula is position specific (a single weight vector has leave-one-out error 1.1, per-position weights 0.43;
  the rounding of the integer display alone limits it to about 0.29);
- height and weight do not improve the fit; Durability gets no weight;
- the weights are only reliable as a predictor inside the range of the training data. The model's ratings are strongly
  stereotyped per position (many attributes identical for all players of a position), so individual weights are not identified.
  Fix: a calibration round (below).

### Calibration round

`scripts/make_calibration.py` takes the real roster and randomises everything the formula could depend on (position, height,
weight, all 19 visible ratings, and eight named hidden attributes at
0x4C/0x4F/0x50/0x55/0x5A/0x5C/0x5F/0x60. Their legacy calibration aliases
`DunkFlag, B4F, B50, B55, B5A, B5C, B5F, B60` are kept equal to the named
columns, so existing fitting datasets remain usable. Dunk Range stays 10):

1. `python scripts/make_calibration.py` -> `data/calibration/proa_calibration.xlsx`
2. `python scripts/build_roster.py --proa data/calibration/proa_calibration.xlsx --out data/calibration/build --card <card>`
   (PCSX2 closed; back up the card first; rebuild the real roster afterwards with a plain `build_roster.py --card <card>`)
3. `python scripts/make_calibration.py --lineup` -> `data/calibration/lineup.md` and `observed.csv` (game names per team)
4. In game, read the overall of every player; fill `overall` in `observed.csv`.
5. `python scripts/fit_overall.py` (merges both sources; `--calibration-only` ignores the real-roster observations).
   A different `--seed` plus an empty `observed.csv` starts a second round.

The fit reports whether the extra bytes / height / weight matter. Tested on synthetic observations generated from a hidden
per-position formula: weights recovered to within 0.01.

#### Round 1 results (101 random players, 8 teams, `observed.csv`; transcribed screenshot in `screenshot_round1.csv`)

- In-game positions matched the workbook for all 101 players.
- A single shared weight vector fails (in-sample rmse 3.1); position-specific weights are needed.
- Height and weight: no effect. Durability, Stamina: about zero weight.
- Three record bytes matter: **B4F, B50, B55** (about +0.06..0.07 overall per point each; range 50..99 gives about 3 points).
  Leave-one-out error drops from 2.7 to 1.4 when they are included. DunkFlag, B5A, B5C, B5F, B60 carry no weight.
  At the time of this calibration, real players used neutral `default_extras`.
  They now use their explicit named hidden values in every Overall prediction.
- Midrange Shot has the largest weight at every position; Post Defense and Defensive Rebound dominate the C and PF
  weights; Passing, Ball Handling and Steal dominate the PG weights. Weight sums are 1.2 to 1.4 (the overall is spread
  wider than the mean of the ratings).
- Merged model (211 observations): leave-one-out rmse 1.39 overall, **0.65 on the real-roster rows**, 1.9 on the
  calibration rows (random ratings lie far outside the realistic range). In-sample 151/211 exact after rounding, 208/211
  within 1. Largest residual: Johannes Patrick (72 shown, 4 points above the prediction; probable misread).
- With about 20 observations per position and 27 parameters, individual weights remain only loosely identified.
  A second round (`make_calibration.py --seed N`) would tighten them.
