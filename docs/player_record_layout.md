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
| 0x04 | u16 | player identifier; often, but not always, equal to `+0x06` | W (set to PID) |
| 0x06 | u16 | player model ID and numeric portrait lookup key; see [Portrait selection](#portrait-selection) | W (set to PID) |
| 0x08 | u8 | player flags; bit 0 participates in the created-model predicate, bit 1 bypasses numeric portrait lookup | W (bit 0 for created overrides; other bits preserved) |
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
| 0x61 | i8 | **hairstyle selector** in create-a-player; `0` Bald, `7` Afro; `-1`/`0xFF` common in stock players | W |
| 0x62 | u8 | **build selector** in create-a-player: `0` Normal, `1` Thick, `2` Fat; also written by the NBA headband workflow, but its headband-style role is unproven | W |
| 0x67 | i8 | **headband selector**: `-1`/`0xFF` None, `0` Headband 1 | W (headband workflow) |
| 0x68 | u8 | nonzero required with `+0x08` bit 0 for a created-model predicate; full meaning unproven | W (1 for created overrides) |
| 0x69 | u8 | **skin tone 0-5**: selects `legs00`-`legs05`. Automatic casting inherits the PID's tone; manual workbook `Skin Tone` 1..6 writes `6 - value` with a matching model-local ISO recipe | W |
| 0x6A | u8 | **muscle tone** in create-a-player: `0` Buff, `1` Ripped | W |
| 0x6D | u8 | created-player moustache: `0` None, `1` Moustache 1 | W |
| 0x6E | u8 | created-player beard: `0` None, `1` Beard Style 1 | W |
| 0x6F | u8 | created-player sideburns: `0` None, `1` Sideburns 1 | W |
| 0x70 | u8 | created-player hair colour: `0` Black, `1` Brown, `2` Blond; also used for facial-hair resources | W |
| 0x71 | u8 | **created-player head selector**; `0` Head 1, `1` Head 2 | W |
| 0x86 / 0x87 | u8 each | created-player left / right neck tattoo: `0` None, `1` Tattoo 1, `2` Tattoo 2 | W |
| 0x8A / 0x8B | u8 each | created-player left / right bicep tattoo: `0` None, positive value selects tattoo | W |
| 0x8C / 0x8D | u8 each | created-player forearm tattoos: `0` None, positive value selects tattoo; left / right respectively inferred from the batch | W |

### Created-player head and hairstyle probe

On 2026-11-26, two otherwise identical created players `a` and `b` were saved
to Roster1 with Bald and Afro respectively. Their `+0x61` values were `0` and
`7`. After changing only player `a` from Head 1 to Head 2 and saving again,
its `+0x71` changed from `0` to `1`; its other `0x94` record bytes were
unchanged. Player `b` retained Head 1 (`+0x71 = 0`). The pair's names, tagged
pointers and created-player PIDs differ as expected.

The pristine Europe executable independently corroborates both fields. The
head-selection display table at EE `0x8FD338` maps values `0..6` to Head 1
through Head 7; its editor code reads/writes `+0x71` at EE `0x30B9F8` and
`0x30BA24..0x30BA78`. The hairstyle table at EE `0x8FD388` maps `0..25`,
including Bald `0` and Afro `7`; its editor accesses `+0x61` at EE
`0x30BC48..0x30BCC8`. The head-loading path uses `+0x71` and `+0x61` with the
`hihead%02d%02d.iff` resource-name format at EE `0x18D4C0..0x18D518` and
`0x18D67C..0x18D6D4`. This establishes a link to head assets, not that every
player follows that loading path.

In the pristine roster, **all 395 players referenced by the 30 original NBA
teams have `+0x71 = 0`**; all 792 primary records also have zero. The same
byte therefore exists in real-player records, but a stock zero does not prove
that their PID-specific faces use Head 1. Their record byte `+0x08` is `4`;
the two created players have `5`. Prior testing of `+0x61 = 6` on a real
player showed no visible change. The later complete created-model test
successfully displayed added facial hair and tattoos on Jarne, but did not
isolate the head or hairstyle selectors; changing a player type may have
other effects and should not be assumed safe.

### Created-player muscle tone probe

After the head experiment above, the user changed only player `a` from Buff to
Ripped. Comparing its saved `0x94`-byte record with the captured prior record
shows one change: **`+0x6A` changed from `0` to `1`**. Player `b`, still
Buff, has `0`. The absolute payload offset for `a` is `0x1B386`. The later
build-edit save described below changed `a`'s muscle tone back to `0`.

The pristine Europe executable independently confirms the mapping: the
two-entry label table at EE `0x8FD658` contains Buff and Ripped, and editor
code at EE `0x30BB28..0x30BB9C` indexes it with `+0x6A` and cycles between
`0` and `1`. Appearance code at EE `0x192114..0x192138` uses skin tone
`+0x69` and muscle tone `+0x6A` to format `arm%02d%02d`; at
`0x192348..0x192368` it similarly formats `barm%02d%02d`. Further paths use
the muscle byte in `bic_...` and `for_...` resource names. This is static
evidence of resource selection, not a demonstration that changing the byte
visibly modifies an NBA player's PID-specific model.

All **395 players referenced by the original 30 NBA teams** have `+0x6A = 0`
in the pristine roster, as do all **792 primary records** and 20 auxiliary
records. The field exists in real-player records, but this alone does not
establish that their visible muscle tone is controlled by it. No in-game
test has checked a real player with `+0x6A = 1`.

### Created-player build probe

The pristine Europe executable's create-a-player menu indexes the table at
EE `0x8FD698` with record byte **`+0x62`**: `0` Normal, `1` Thick, `2` Fat.
Its menu code at EE `0x30BBA0..0x30BC30` cycles these three values.

After player `a` was changed from Normal to Thick and the roster saved, its
`+0x62` changed from `0` to `1` (payload offset `0x1B37E`); player `b` remains
`0`. The comparison with `a`'s previous saved record also found weight at
`+0x34` changed from 210 to 225 lb and muscle tone at `+0x6A` changed from
Ripped `1` back to Buff `0`. These are the only three changed record bytes.
Whether the additional changes were automatic or separately made is unknown.

At EE `0x18C3D4..0x18C3FC`, an appearance path indexes a 252-byte-per-entry
table with `+0x62`, then passes that entry to other model routines. It takes
this branch only when the predicate at EE `0x189080` finds bit 0 of `+0x08`
set **and** `+0x68` nonzero. This is consistent with selecting a build-specific
model configuration, but does not by itself establish the exact scaling.

The pristine 395 NBA-team records contain `+0x62` values `0` (373), `2` (15),
`4` (2) and `5` (5). Across 792 primary records the counts are `0` (750),
`2` (27), `4` (4) and `5` (11); the 20 auxiliary records are all zero.
All 395 NBA records have `+0x08 = 4` and `+0x68 = 0`, so they fail the
predicate above. Therefore these stock values must not be interpreted simply
as created-player builds; effects of changing them on NBA models are unproven.

The existing headband workflow also writes `+0x62`. Its proposed role as an
NBA headband style is not established: the earlier test set `+0x62 = 2` and
`+0x67 = 0` together on one player, rather than isolating `+0x62` on the same
player. The apparent size difference could have another cause. Do not assume
that changing `+0x62` changes headband style or that its NBA interpretation
is the same as the created-player build selector.

### Created-player headband probe

After the build experiment, the user gave player `a` a headband and saved
Roster1. The only difference in its `0x94`-byte record was **`+0x67` changing
from `0xFF` to `0`** (payload offset `0x1B383`); its Thick build at `+0x62`
remained `1`. Thus the headband and build use separate bytes in this created
player, and its headband byte matches the offset previously observed for NBA
players.

The executable's editor reads signed `+0x67` at EE `0x30C2D0` and indexes
the table at EE `0x8FD358` using the value plus one: `-1` is None and `0` is
Headband 1. Its editor cycles between those values at
`0x30C2FC..0x30C34C`. The appearance path at EE `0x18BDE4..0x18BE1C`
also reads `+0x67`. In the pristine roster, 58 NBA-team players have `0`
and 337 have `0xFF`; among them, `+0x62` has nonzero values both with and
without a headband.

There is no evidence here of a fixed offset shift between created and NBA
player records: both use the same record stride and headband offset. The
build-dependent branch above is instead gated by record fields `+0x08` and
`+0x68`. This does not establish the meaning of every appearance byte for
both player types, or prove what `+0x62` does for NBA players.

### Created-player hair, facial hair and tattoo probe

The user saved seven cumulative edits of player `a` to Roster1 through Roster7.
Each transition below lists all changes in its `0x94`-byte record; no other
primary player record changed between successive Roster1-7 saves. The first
row compares with the previously captured headband record.

| Save | Edit | Record change |
|---|---|---|
| Roster1 | hair colour Black to Brown | `+0x70: 0 -> 1` |
| Roster2 | beard None to Style 1 | `+0x6E: 0 -> 1` |
| Roster3 | moustache None to Moustache 1 | `+0x6D: 0 -> 1` |
| Roster4 | sideburns None to Style 1 | `+0x6F: 0 -> 1` |
| Roster5 | left neck None to Tattoo 1 | `+0x86: 0 -> 1` |
| Roster6 | right neck None to Tattoo 2 | `+0x87: 0 -> 2` |
| Roster7 | left bicep, right bicep, forearms to Tattoos 1, 2, 3, 4 in order | `+0x8A: 0 -> 1`, `+0x8B: 0 -> 2`, `+0x8C: 0 -> 3`, `+0x8D: 0 -> 4` |

The four arm changes were saved together, but their distinct tattoo values
associate each byte with the stated edit order. The first forearm was described
as `ft forearm`; its identification as left is inferred from the paired layout
and right forearm being the second edit, not independently tested.

The Europe executable corroborates these selectors through the editor getters:
hair colour at EE `0x30BCE0` (label table Black, Brown, Blond), beard at
`0x30BD78`, moustache at `0x30BE10`, sideburns at `0x30BEA8`, and tattoos at
`0x30BF40..0x30C248`. The facial-hair appearance path at
`0x191DD4..0x191ECC` uses `+0x70` together with the respective style bytes
to form `beard%02d%02d`, `stache%02d%02d` and `burns%02d%02d` resources.
The tattoo paths at `0x191F88..0x19202C` and `0x192184..0x1922F8` use the
selectors with skin tone, and for arms also muscle tone, to form `neck_...`,
`bic_...` and `for_...` names. For these resource names the code subtracts
one from a nonzero tattoo selector; the UI numbering and resource numbering
therefore differ.

All ten bytes above are zero in all 395 pristine NBA-team records, all 792
primary records and all 20 auxiliary records. Their presence in the same
record layout does not establish that edits affect real NBA PID models. In a
test save, Jarne Juergens (PID 268, `+0x08 = 4`, `+0x68 = 0`) was given all
six tested tattoo selections, beard, moustache, sideburns and Brown hair.
The user reported that none appeared on his in-game model.

At EE `0x189314..0x1893BC`, initial created-player texture composition
(`0x191C08`) is reached only if the predicate at `0x189080` succeeds:
`+0x08` bit 0 must be set and `+0x68` must be nonzero. Merely changing
`+0x08` from `4` to `5` leaves Jarne's `+0x68 = 0` and does not satisfy this
branch. A second test also sets `+0x68 = 1` and changes hairstyle `+0x61`
from `0xFF` to Bald `0`, providing a valid created-head selection.
The user confirmed that the complete-predicate test displayed
Jarne's tattoos and facial hair and retained his portrait. This does not
isolate the effects of the individual flag and hairstyle changes.

### All-created roster stress test

On 2026-11-26, the user reported that the all-created ProA roster stress test
worked well in game. The test card converted all 252 ProA players by setting
`+0x08` bit 0 and `+0x68 = 1`, while retaining their assigned PID, portrait ID
and skin byte. It used Bald (`+0x61 = 0`) and per-player heads selected with
the skin-tone restrictions below. This is a milestone for roster-wide use of
the created-model approach, though the report does not establish that every
appearance combination or game mode has been tested. The newer randomized
hairstyle defaults were added after this card was prepared.

### Portrait selection

These are numeric IDs, not a stored pointer to portrait pixels. In Roster7,
created players `a` and `b` have `+0x04 = 0` and `+0x06 = 3000` or `3001`
respectively, with `+0x08 = 5`. All 395 original NBA-team records have equal
`+0x04` and `+0x06`; not all 792 primary records do.

The Europe executable's portrait lookup at EE `0x2D4FB0..0x2D503C` checks
bit 1 (`0x02`) of `+0x08`. When clear, it formats `+0x06` as `%04d` and
looks for that TXTR; if absent, or if bit 1 is set, it uses `nophoto`.
Pristine portrait collection `35cb8d72` contains `0268`, but no `3000` or
`3001`. Thus the created-player examples fall back when using this numeric
lookup, while keeping Jarne's `+0x06 = 268` and changing `+0x08` from `4`
to `5` leaves this lookup eligible for `0268`. Which image is displayed
depends on the loaded portrait textures, and actual display after enabling
the created-model path was confirmed for Jarne. `+0x06` is also consumed by model
loading, so it must not be treated as an independent portrait-only pointer.

### Created-model overrides

The following optional columns in `data/overrides.xlsx` and the generated roster workbook use
the editor's raw numeric selectors. Blank means no override; even an explicit
zero selects the created model. Set overrides in the override workbook for persistence
across workbook regeneration.

| Column | Byte | Values |
|---|---|---|
| Head | `+0x71` | 0-6 = Head 1-7 |
| Hairstyle | `+0x61` | 0-25 (0 Bald, 1 Buzz, 2 buzz fade, 5 natural, 7 Afro, 10 cornrows, 11 dreadlocks, 
13 short flattop, 16 mullet, 18 slicked back, 19 slicked back long, 21 chin long open, 22 part right, 23 part mid,  )    |
| Build | `+0x62` | 0 Normal, 1 Thick, 2 Fat |
| Muscle Tone | `+0x6A` | 0 Buff, 1 Ripped |
| Hair Color | `+0x70` | 0 Black, 1 Brown, 2 Blond, 3 red |
| Beard | `+0x6E` | 0 None, 1 Full, 2 Full trimmed, 3 chin, 4 goat, 5 goatee, 6 full with goatee|
| Moustache | `+0x6D` | 0 None, 1 slim, 2 regular, 3 weird, 4 trucker, 5 wide, 6 regular
| Sideburns | `+0x6F` | 0 None, 1 short, 2 medium, 3 long |
| Lt Neck Tattoo / Rt Neck Tattoo | `+0x86` / `+0x87` | 0 None, 1-6, 1 and 4 are least ridiculous |
| Lt Bicep Tattoo / Rt Bicep Tattoo | `+0x8A` / `+0x8B` | 0 None, 1-12, 5 tribal, 8 cross |
| Lt Forearm Tattoo / Rt Forearm Tattoo | `+0x8C` / `+0x8D` | 0 None, 1-12, 3,4 dragon, 8 tribal, 11 lion |

Any supplied selector sets bit 0 of `+0x08` and `+0x68 = 1`, retains the
assigned PID and portrait ID, and defaults the remaining selectors to zero
(Normal, Buff, Black and no facial hair or tattoos). Missing Head and Hairstyle
are chosen pseudo-randomly and reproducibly from the ProA ID and effective
in-game skin byte: skin bytes 4 and 5 use heads 2-6 and hairstyles 5, 13 or 22;
other skin bytes use heads 0-6 and hairstyles 1 or 2. Explicit Head and
Hairstyle overrides win, including Hairstyle 0 (Bald). Created-model Build
owns `+0x62`; for such players the existing headband
style preset is ignored, but the headband itself remains enabled. The build
report notes the conflict.

### Accessories (verified in game through the memory card)

The accessories are record bytes (not part of the pid model): they stay when the model is swapped, and `0` = none (`0x67`: 255 = none). Live RAM patching after `set_roster` is ignored by the game, so test only via the card (`scripts/acc_card_test.py` is the test harness).

| offset | meaning | values seen in game |
|---|---|---|
| 0x67 | **Headband** | 0 on, 255 off |
| 0x72 | **Shades** | 0 None, 1-8 Shades 1-8; 1 sports dark, 2 sports white, 6 sports large, others funky |
| 0x75 / 0x76 | **Left / Right Wrist Band** | 7 wristband, 3 long forearm tape |
| 0x77 / 0x78 | **Left / Right Elbow Pad** | 11 small band above elbow, 6 large brace (right 6 not tested) |
| 0x79 / 0x7A | **Left / Right Arm Band** | 0 None, 1-12 raw editor indices; 7 shows a band above elbow |
| 0x7E / 0x7F | **Left / Right Knee Pad** | 14 small tape; right 6 brace, 10 small brace |
| 0x63 | **Shorts Length** | 0 Short, 1 Long; editor mapping only |
| 0x83 | **Sock Length** | 0 Ankle Socks, 1 Short, 2 Medium, 3 Long; editor mapping only |
| 0x84 / 0x85 | **Home / Away Sock Color** | 0 Black, 1 White; editor mapping only |
| 0x62 | created-player build; NBA headband-style hypothesis remains unproven (see probes above) | existing NBA workflow writes 0 or 2 |
| 0x61, 0x62 = 5 | nothing visible in the earlier real-player tests; `0x61` is also the created-player hairstyle selector above | |
| 0x64-0x66 | legacy candidates: 0x64/0x65 = 9 on the 80's Celtics (historic teams?), 0x66 may be a goggles index (`goggles00`-`07`) | raw experimental overrides; meanings unconfirmed |

Items are indices into one shared pool of model parts (`wristitem01-17`, `armitem01-03`, `elbowitem01-03`, `kneeitem01-04`, `legitem01-03`, `headitem02-33`), so other numbers (2-20 occur in the NBA data) give other looks; use the corresponding accessory column in `data/overrides.xlsx` to try them.

The menu names and selectors above were recovered from the Europe executable's
editor descriptors and getters at EE `0x30C2C0..0x30CAA0`. Shades, shorts,
socks, sock colours and individual right-side variants still need isolated
in-game tests on real and created players; `+0x64..+0x66` also need isolated
tests to establish their relationship to the Shades menu. The forearm tattoo
left/right assignment should be independently confirmed. Additional checks
should cover individual created heads, hairstyles and player PIDs, and game
modes not covered by the successful all-created roster stress test.

`build_roster.py` clears the original accessory fields for every ProA player (NBA records have their own accessories), then reads the canonical workbook columns. The former `data/accessories.csv` values have been migrated into ID-keyed `data/overrides.xlsx`; edit only that file for persistent changes. Columns: `headband` (1 or 2: both enable the headband, and write 0 or 2 to `+0x62` for NBA models; a size difference is unproven), `wrist_l/r`, `arm_l/r`, `knee_l/r` (1 or 2 = presets from the table above: wrist 7/3, arm 11/6, knee 14/6; any number >= 3 is written raw as item index; 0 = none). An empty override cell means no override, not removal.

Additional columns `Shades`, `Left Arm Band`, `Right Arm Band`, `Shorts Length`,
`Sock Length`, `Home Sock Color` and `Away Sock Color` write their raw editor
values from the table. `Legacy Accessory 0x64`, `Legacy Accessory 0x65` and
`Legacy Goggles 0x66` are experimental raw bytes (0-255; 255 is the existing
cleared default), not verified editor options. These columns do not enable a
created model. Blank new columns preserve previous behavior: arm-band bytes
are cleared to 0 and legacy bytes to 255, while shades, shorts and socks
retain their inherited values. Explicit 0 is written, including for shorts
and sock colours. See [Persistent player edits](SeasonUpdateWorkflow.md#persistent-player-edits-and-exclusions)
for override correction and warning behavior.

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
overridable via `data/overrides.xlsx`); `scripts/rating_map_2k5.py` maps column name -> byte offset. The database workflow validates ratings in 25-99 before building.
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
