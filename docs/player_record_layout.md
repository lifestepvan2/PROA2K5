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
| 0x62 | u8 | **build selector** in create-a-player: `0` Normal, `1` Thick, `2` Fat; old NBA headband overrides are preserved as `Legacy Accessory 0x62`, but its headband-style role is unproven | W |
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

The legacy headband workflow also wrote `+0x62`. Its proposed role as an
NBA headband style is not established: the earlier test set `+0x62 = 2` and
`+0x67 = 0` together on one player, rather than isolating `+0x62` on the same
player. The apparent size difference could have another cause. Do not assume
that changing `+0x62` changes headband style or that its NBA interpretation
is the same as the created-player build selector. These old overrides are now
preserved separately as `Legacy Accessory 0x62`; the canonical `Headband`
selection writes only `+0x67`.

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

### Created-player hairstyle level of detail

**Current default, approved 2026-11-27:** the user accepted the final
780-triangle cornrow revision and the complete supported per-style mesh set.
Normal `build.py` builds now apply that exact geometry and selector through
`scripts/created_hair_lod.py`, using the versioned assets and fingerprints in
`data/created_hair_lod`. Styles 1 and 7 retain the stock short and afro meshes;
styles 2, 5, 10, 11, 13, 16, 18, 19, 21, 22 and 23 use the approved custom
streams. `--basic-meshes` retains the explicit three-stock-mesh fallback below.
No high-LOD forcing, experimental roster assignments or session-file dependency
is included. The final scene, selector and binding patches were compared
byte-for-byte with the approved ISO before integration.

Each expanded scene has 18 parts/materials and 109,552 decoded bytes.
Cornrows use 1,565 transformed vertices; the other custom styles use 278..445.
These are resource/renderer counts, not measured per-player RAM or hardware
performance. Original PS2 hardware remains unvalidated. The user considers the
build pipeline feature-complete, with manual texture artwork still required.

#### Investigation and review history

The following describes the earlier prototypes; statements that a prototype
was not part of normal builds refer to that stage, before the integration above.
The generated experimental ISOs were later removed to recover disk space;
the approved assets and their provenance remain in the repository.

Issue #35 reported different hairstyles at gameplay distance and a reddish
close-up beard. The initially tested ISO, `proa2k5_493cc7292c1186db.iso`, contained
the current generated roster payload. Its records and the live game agree:
Addae-Wusu has head 0, hairstyle 10 and Black hair; Mayer has head 5,
hairstyle 22; Uzoma has head 5, hairstyle 7. All three have the created-model
gate enabled. The earlier bald-only stress test did not test this mismatch.

The Europe executable loads the selected `hihead%02d%02d.iff` for a created
head. At EE `0x18A894..0x18A8AC`, it deliberately skips the player's `lohead`
lookup for created models. Instead, it initializes a separate
`locreatehead` pool at `0x18A59C..0x18A5B8` and allocates from it at
`0x18C7D4..0x18C844`. In the running game, both Addae-Wusu and Mayer were in
LOD state 1 and their low-head scenes were distinct instances of
`locreatehead`; their high-head scenes were `hihead`. The shared low-head
scene contains only `hair01_mat`, `hair02_mat` and `hair03_mat`, whereas
the selected high-head resources contain hairstyle-specific geometry.
The game's `0x18BF58..0x18C060` logic maps `+0x61` into those few low-detail
parts; it does not load a matching low-detail model for every hairstyle.
The mapping itself also contributes to the mismatches: live LOD-1 samples
show hairstyle 10 uses `hair01_mat`, hairstyle 7 uses `hair03_mat`, and
hairstyle 22 uses `hair02_mat`. Hairstyle 22 shares that fallback with 15,
16, 21, 23 and 24, despite the different high-detail styles.

An isolated MIPS execution experiment changed only hairstyle 22's jump-table
entry at EE `0x41473C` from `0x18B7B0` to `0x18B740`. This selects
`hair01_mat` instead of `hair02_mat`; all 25 other supported selectors kept
their stock results. The prototype
`C:\Tools\isos\proa2k5_493cc7292c1186db_lod22_experiment.iso` contains that
change and an ELF checksum compensation. The user confirmed in game that
Mayer's distant hairstyle is more suitable; Addae-Wusu and Uzoma were
unchanged. Hardware performance remains untested. Cold boot the prototype
rather than loading a save state containing the old executable; it inherits
the source ISO's title build ID. It is not part of the normal build.

The pristine `frontend.iff` and `gamedataextra.iff` each contain an
identical `locreatehead` SCNE: 14,256 compressed bytes, 21,408 decoded
system bytes and no video tail. Its single player mesh has seven parts and
seven material slots. Their hair parts are:

| Runtime material | Mesh part | Stream bytes | Packed input points |
|---|---:|---:|---:|
| `hair01_mat` | 2 | 1,568 | 59 |
| `hair02_mat` | 3 | 2,128 | 99 |
| `hair03_mat` | 4 | 1,664 | 66 |

These are **input points, not triangle counts**: vertices can be reused.
The game's material lookup at EE `0x18AFF0..0x18B01C` reads names from
`scene.materials + index * 0x60 + 0x58`. The older
`texture_catalogue.scene_materials` inspector reads the previous record's
name, so its labels and `inspect_logo_iso.material_consumers` labels are
shifted; do not use them to identify a mesh until that shared inspector and
its workspace consumers are migrated. Its descriptor links have not been
revalidated by this discovery.

The archive also has all 182 `hihead%02d%02d.iff` combinations for heads
0..6 and hairstyle selectors 0..25. Each selector 1..25 has a hair material
`hair{selector - 1:02d}_mat`; selector 0 has none. For example, Addae-Wusu's
high-detail hair is `hihead0010.iff` / `hair09_mat`, part 4, with 1,305
packed input points; Uzoma's is `hihead0507.iff` / `hair06_mat`, part 0, with
467; Mayer's is `hihead0522.iff` / `hair21_mat`, part 0, with 201. The
executable's binding table associates all three low materials and all 25
high hair materials with a texture named `hair`. The exact generated texture
instance, UV interpretation and colour treatment remain to be traced; the
SCNE has no embedded video texture.

For offline inspection of the original Europe ISO:

```powershell
python scripts\inspect_created_hair.py --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --head 5 --output "C:\Tools\isos\hair-review-head05"
```

The output directory must be new. It contains four contact sheets, a CSV
inventory, and colour-coded PLY point clouds (grey face, orange hair) for
the three low variants and all 26 high styles for that head. These are
quantized local coordinates, **not decoded surfaces**: texture, face/strip
connectivity, transforms and runtime deformation are not reproduced. The
front and side projections are for shape comparison only. The three shared
low meshes are visibly much simpler than the affected high-detail hair;
the point clouds alone cannot establish that any low mesh is an unselected
dreadlock or show the actual textured result.

For experimental triangle surfaces instead, use a different new directory:

```powershell
python scripts\inspect_created_hair_surfaces.py --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --head 5 --output "C:\Tools\isos\hair-surfaces-head05"
```

This exports OBJ meshes, a triangle-count inventory, and untextured contact
sheets. Triangles are reconstructed from the VIF output slots and strip
restart metadata; runtime VU instructions mark each listed start and its
following vertex. The export does not reproduce skinning, transforms, UVs,
texture or lighting. The contact sheets use approximate painter sorting,
not a depth buffer, and are not proof of surface coverage or clipping.

The user's visually assessed fallback mapping, if custom low-detail meshes
are not feasible, is:

| Low mesh | Hairstyle byte values |
|---|---|
| `low_01` / `hair01_mat` (short) | 1, 2, 5, 13, 18, 22, 23 |
| `low_02` / `hair02_mat` (Afro) | 7 |
| `low_03` / `hair03_mat` (long) | 10, 11, 16, 19, 21 |

`python build.py --basic-meshes` applies this mapping to the ISO; values not
listed retain their original selection. All 26 selectors were checked in
isolated executable emulation, but the complete mapping has not been validated
in game or on original hardware. Without the flag the normal build still uses
the original selection; custom low-detail meshes are not yet integrated.

An isolated experimental ISO, `C:\Tools\isos\proa2k5_hair11_experiment.iso`,
replaces `hair03_mat` with a 240-triangle candidate in both scene copies. Its
private roster copy sets Crailsheim's Dylan Addae-Wusu to head 5, hairstyle 11.
For this experiment only, hairstyle 11 selects the custom slot, hairstyle 7
selects stock `hair02_mat`, and hairstyle 22 selects stock `hair01_mat`.
All other selector results were checked unchanged in isolated MIPS execution.
The ISO uses the existing generated roster payload and current native texture
workspace; it does not change the workbook, normal build, or memory cards.
Both relocated scenes, the roster bytes and selector table were read back
after publication. On 2026-11-27 the user confirmed that the ISO boots and
plays, Addae-Wusu's hair "looks fantastic", scalp clipping was not noticeable,
and Uzoma's and Mayer's hair both looked fine. This is an emulator observation,
not proof for every view, player, game mode or original hardware. The
experiment is not a production build. Although it reduces triangle count,
its simple independent-triangle encoder submits 720 packed input vertices,
versus 464 for the original high-detail hair and 66 for stock `hair03_mat`;
triangle count alone therefore does not demonstrate a lower vertex-processing
cost.

The separate `C:\Tools\isos\proa2k5_hair11_strips_experiment.iso` re-encodes
the same candidate using [`created_hair_strips.py`](../scripts/created_hair_strips.py):
118 triangle strips, 476 output slots and 445 packed input vertices, with
31 output vertices copied from the preceding VU batch. The stream is 7,664
bytes rather than 12,240. After repacking, both scene copies were read back
and their oriented triangles, UVs and normals compared against the first
prototype; its roster and selector bytes were unchanged. This second ISO
was also reviewed in-game by the user on 2026-11-27 and looked the same as
the first. Original-hardware behavior remains untested, and vertex counts
alone do not prove a performance improvement.

The fourth-mesh experiment adds the same strip-encoded dreadlock candidate
as a new `hair10_mat` part, rather than overwriting `hair03_mat`. Both
`locreatehead` copies retain the original seven parts/materials and add an
eighth. The decoded scene grows from 21,408 to 30,064 bytes (+8,656); this
is resource size, not a measured per-player RAM increase. The added material
starts hidden and reuses executable binding index 32, which already maps
`hair10_mat` to the generated `hair` texture.

An isolated low-detail-only code replacement at EE `0x18BF58..0x18C064`
selects one of runtime bindings 20, 21, 22 or 32 and hides the other three,
using the existing material lookup and visibility helper. Hairstyle 11 selects
the fourth part; the other supported styles follow the user's basic mapping.
Unlisted styles retain their stock selection. No new scene pool or forced
high LOD is introduced.

Isolated MIPS execution checked all 256 hairstyle-byte values through the
existing name-based and cached material lookup paths, the actual 64-bit
visibility flag updates, and repeated changes in two independent synthetic
scene instances. R5900 quadword save/restore, three-register multiplication
and conditional moves are explicitly emulated where Unicorn lacks support;
the UTF-16 equality helper is intercepted. The cached lookup test supplies
the expected cache entries; it does **not** prove that the game populates
those entries or allocates independent materials for the expanded scene.
Native stream roundtrips compare oriented geometry, UVs and normals and
verify that the three original hair meshes and face are unchanged.
The user subsequently reported that the four-mesh experiment was working
fine in game. That supports the selection approach in the reviewed matchup,
but does not establish original-hardware performance or all game modes.

The previously published `C:\Tools\isos\proa2k5_four_hair_experiment.iso`
was removed to free disk space. It passed full output-hash verification,
relocated scene/vertex-attribute readback and
complete ELF readback; its game XOR CRC remains `0xF5931256`. It uses the
current roster payload and native workspace, but changes only its private
roster copy: Addae-Wusu becomes hairstyle 11/head 5, and Till Isemann becomes
hairstyle 16 with his existing head 2. Neither the workbook nor normal builds
are changed. Cold boot a Crailsheim-Essen game, not a previous save state:
Addae-Wusu tests the new fourth mesh, Marko Dordevic the stock short mesh,
Isemann the stock long mesh, and Uzoma the stock afro. Check their coexistence,
close/distant transitions, hair colour and scalp coverage, including after
replays and substitutions. The user reported the experiment working fine
in game; the report did not detail individual review cases.

The expanded test uses eleven new custom meshes and the three original
stock meshes: supported hairstyle 1 selects the stock short mesh, and 7 the
stock afro. The remaining supported hairstyles select their own simplified
mesh. The original stock meshes remain available for unsupported hairstyle
values. Each scene copy has 18 parts and 18 materials, and its decoded
system size is 92,752 bytes instead of 21,408. This is resource size, not
measured per-instance RAM. Selector and existing material lookup code were
checked offline for all byte values, including repeated updates of synthetic
instances; real pool memory, gameplay performance and original hardware are
not yet established for the larger scene.

All eleven custom meshes derive from high-detail head 5, use per-scene scale
and approximate face alignment, and retain at most 240 reconstructed
triangles apiece. They are experimental, not in the normal build. The coarse
radial clearance probe is not a reliable visibility or skinning simulation:
the most negative samples for style 10 and style 5 were respectively about
7.7% and 6.1% of head width inside the low head, including original hairline
anchor positions. The user-tested dreadlocks measured 1.7% by the same
approximation. Style 10 also has visibly coarser untextured strand geometry.
In-game scalp coverage, textures and LOD transitions should be reviewed
especially for those styles before treating the candidates as final.

The original test was `C:\Tools\isos\proa2k5_thirteen_hair_experiment.iso`;
it was later removed to free disk space.
The ISO, selector, both relocated scenes, all hair vertex attributes and the
private roster were read back; PCSX2 XOR CRC remains `0xF5931256`. It leaves
the workbook and normal build unchanged. Cold boot Crailsheim vs Essen and
review all 13 styles using these temporary assignments:

| Hairstyle | Test player | Team | Starting? |
|---:|---|---|---|
| 1 (stock short) | Simon Krajcovic | Crailsheim | yes |
| 2 | Nico Hoellerl | Crailsheim | yes |
| 5 | Quashawn Lane | Essen | yes |
| 7 (stock afro) | Benjamin Uzoma | Essen | yes |
| 10 | Isaiah Jevon Sanders | Essen | yes |
| 11 | Dylan Addae-Wusu | Crailsheim | yes |
| 13 | Marko Dordevic | Crailsheim | yes |
| 16 | Till Isemann | Crailsheim | yes |
| 18 | Hendrik Drescher | Crailsheim | substitute |
| 19 | Darius Dawson | Essen | yes |
| 21 | Courtney Alexander | Crailsheim | substitute |
| 22 | Lucas Mayer | Crailsheim | substitute |
| 23 | JJ Mann | Essen | yes |

Five players normally using NBA PID models were temporarily converted to
created models for this ISO; their PID, portrait and skin byte are retained.
Check the entire batch for simultaneous correct selection, scalp gaps or
clipping, texture/colour, and close-to-distant transitions. Also check for
gameplay or loading issues; the larger scene has not been tested on hardware.

The user reviewed the thirteen-style ISO: style 10 cornrows lost too much
detail, and styles 2, 13 and 16 exposed scalp at the rear corners. Styles 5,
18, 19, 21, 22 and 23 were reported satisfactory. Earlier tests established
that the stock short and afro and the custom dreadlocks worked in the
reviewed matchup; this feedback is not a hardware performance test.

A targeted follow-up candidate replaces only styles 2, 10, 13 and 16.
For cornrows it retains 540 triangles instead of 240 (high-detail source:
894), giving visibly more detail in untextured offline projections. It
requires 1,154 transformed vertices versus 561 in the prior 240-triangle
candidate; the cost on hardware is unknown. All four candidates add a
smooth, radial rear-corner adjustment, up to 2.7% of head width, tapering
off toward the front and lower head. Identical positions receive identical
displacement across UV seams; front hairline anchors remain in place.
UVs and normals are unchanged. This may affect rear silhouette and must be
reviewed in game.

An offline ray test sampled each hair triangle at a four-interval barycentric
grid, selecting rear-corner points above the lower head. The fractions of
samples inside the low-head surface before and after the adjustment were
27.3% to 0.1% for style 2, 12.5% to 0.2% for style 10, 19.9% to 0.2%
for style 13, and 8.6% to 0% for style 16. Points enter or leave the
region as geometry moves, so counts differ slightly between measurements.
These rays do not model visibility, deformation or animation, and do not
detect absent hair coverage. In particular, some style-10 samples remain
deep inside the head near an edge; the probe cannot determine whether these
are intentional intersections or visible gaps.

The follow-up ISO is `C:\Tools\isos\proa2k5_revised_hair_experiment.iso`
(SHA-256 `a7bbcfab9ab74d3bd6e5dde78bbdc741a80652724348070ee713e721ffced199`).
Both scene copies were read back: the revised streams match their encoded
candidates, and every other mesh stream is byte-identical to the previous
test. The full private roster matches the previous test, the complete ELF
was read back, and the PCSX2 XOR CRC remains `0xF5931256`. Each decoded
scene is now 102,736 bytes. Normal builds remain unchanged.

Cold boot the same Crailsheim vs Essen matchup for one review batch:

| Style | Player | Review |
|---:|---|---|
| 2 | Nico Hoellerl | Rear-corner scalp coverage, silhouette and hairline |
| 10 | Isaiah Jevon Sanders | Braid shape and texture, scalp coverage, transitions |
| 13 | Marko Dordevic | Rear-corner scalp coverage, silhouette and hairline |
| 16 | Till Isemann | Rear-corner scalp coverage, silhouette and hairline |

Check close and distant views, both rear corners, movement and replays,
and report loading or gameplay problems. This is an isolated experiment,
not an original-hardware validation or production integration.

The user reported that styles 2, 13 and 16 no longer showed problems in
the follow-up ISO, but that cornrows still needed work at the lower back.
The next candidate protects 272 lower-rear source triangles, including
their UVs and normals, during simplification. Their positions are then
aligned to the low head and receive the bounded clearance adjustment.
The candidate retains 540 triangles total and uses 1,127 transformed
vertices, compared with 1,154 for the preceding cornrow candidate.
An additional lower-back offset of up to 2% of head width is combined with,
not added to, the earlier rear-corner offset. It tapers off at the low
tips and toward the front.

On a lower-rear subset of the same offline ray probe, 29.6% of samples
intersected the head in the reviewed candidate and 14.1% in the new one.
The topology and sample counts differ, and some deep intersections remain;
these values cannot establish visible coverage, texture quality or
animation behavior. The new candidate must still be reviewed in game.

The new test is `C:\Tools\isos\proa2k5_cornrow_back_experiment.iso`
(SHA-256 `01a8fd2a33a9ce2053866727712758b86cce0bfa4dea993693caeced5b3df39a`).
It is a verified copy of the reviewed follow-up with only the cornrow
stream changed in both low-head scenes. Both scene streams, the complete
roster and the ELF were read back; all other hair streams are byte-identical.
The decoded scene size and selector are unchanged. Cold boot Crailsheim vs
Essen and review Isaiah Jevon Sanders' cornrows from the rear and sides,
including the low tips, scalp coverage, close-to-distant transitions,
movement and replays. Also watch for loading or gameplay issues.

The user accepted the lower-back cornrow revision, but reported a jarring
transition between the two row shapes. The user subsequently questioned
which version was straighter; the goal is matching the high-detail source,
not making either version deliberately straighter or wavier.
A higher-budget candidate retains 780 of the source's 894 triangles
instead of 540, preserving the same 272 lower-rear source triangles and
clearance treatment. Its encoded stream uses 1,565 transformed vertices
instead of 1,127 (+38.9%), with 33 copied vertices and 26,384 stream bytes.
Rear-view offline projections retain more of the original strand detail.
This is an explicit cornrow-only budget exception, not forced high LOD.

The candidate passed native geometry/UV/normal roundtrip, both scene
replacement checks, source-ISO hash verification and archive allocation
planning. The larger stream requires more scene storage; all other mesh
streams remain unchanged. Disk exhaustion initially prevented publication.
After the experimental ISOs were removed to recover space, the next test
was rebuilt from the pristine disc and the saved accepted mesh streams.
The new candidate is not yet reviewed in game or on original hardware,
and does not change normal builds.

An offline comparison uses the aligned head-5 high-detail hair with the
same accepted clearance adjustment as the reference. For 3,576 fixed
reference vertex/centroid samples, exact nearest-triangle distances give
RMS surface error of 0.698% of head width for the accepted 540-triangle
candidate and 0.361% for the 780-triangle candidate. The 95th-percentile
error falls from 1.447% to 0.814%. This measures geometric fidelity on
fixed samples, not texture alignment, animation or visible LOD popping;
the reference also includes the intentional scalp-clearance displacement.

The published test is `C:\Tools\isos\proa2k5_cornrow_wave_experiment.iso`
(SHA-256 `8edfb1fe27bdc5703868da0edb09bd30d63976a08c8bf3a157186b1e95495c80`).
Both scene copies' custom streams match the saved accepted candidates
byte-for-byte, except style 10, which matches the new 780-triangle stream.
The full private test roster and ELF were read back, and the PCSX2 XOR CRC
remains `0xF5931256`. Each decoded scene is 109,552 bytes.
Cold boot Crailsheim vs Essen and review Sanders' cornrow shape and
low/high transitions, especially from the rear and sides during replays.
Also check that the accepted lower-back coverage is preserved.

The VIF streams use V3-8 or V4-8 normal-like arrays, V2-16 UV-like arrays,
and V4-16 packed coordinates plus output addresses. Batch metadata can
copy previously emitted vertices into output slots and mark strip starts.
In a read-only gameplay save, renderer command lists set both VIF ROW and
COL to `0x48000000` in every lane. For an unsigned 16-bit value added to
that ROW, the resulting float is `131072 + value / 64`. Scene scale and
bias are then involved in the VU matrix construction. This supports the
high-to-low scale ratio used by the experiment, but does not establish the
relative high- and low-head bone transforms.
The experimental surface decoder processed all 182 high-head scenes.
For head 5, hairstyle 11 (`hair10_mat`) it reconstructs 536 triangles;
the three stock low hairs reconstruct 92, 108 and 103 triangles.
An offline 240-triangle simplification and native-stream encoding experiment
round-tripped through the experimental decoder and was subsequently observed
in-game by the user. The simplifier experimented with retaining hairline
anchors and a slight outward offset, but neither anchor detection nor
complete clearance against the head surface is established. The candidate uses an
approximate face-surface alignment; a coarse radial check against the
low-head mesh found 11 inward samples out of 960, with the largest penetration
about 1.7% of head width. That check does not prove complete coverage and
does not model runtime skinning. The experimental ISO above contains the
candidate; no custom geometry patch is integrated in the normal build. For comparison,
`hihead0010.iff` and `hihead0507.iff` have 73,632 and 58,464 decoded system
bytes respectively. This makes custom simplified low-detail hair plausible,
but not a texture replacement: the encoded stream, UVs, native coordinate
conversion, skinning, and per-hairstyle selection still need validation.

The tested build's archive report has 30,531,584 bytes free; this is disc
capacity, not a guarantee of runtime memory or original-hardware performance.
Adding parts to the shared scene may increase the size of every instance;
separate low-detail scenes would require new loading/selection logic and may
require archive-directory changes beyond the existing repacker. A prototype
must check all relevant scene copies and modes, bounded RAM and renderer
workload, colour and headband behavior, and LOD transitions before deployment.
It must also retain scalp coverage without significant clipping against the
low-detail head. Test a mild outward displacement if needed, while keeping
hairline anchors aligned to the head; validate coverage rather than assuming
that a radial offset alone is sufficient.
The experimental remap alone cannot provide dreadlocks or resolve all
hairstyle transitions. Forcing high detail risks finite scene pools and
performance.

Addae-Wusu's Black beard (`+0x70 = 0`, `+0x6E = 1`) uses `beard0000`.
That texture is byte-identical in the pristine and tested ISOs, and its
visible pixels average RGB approximately `(62, 44, 26)`: the stock Black
beard source is brown-tinted. This is consistent with the red/brown report,
although lighting and compositing have not been independently isolated.

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
owns `+0x62`; for such players the old headband
build-byte override (`Legacy Accessory 0x62`) is ignored, but the headband itself remains enabled. The build
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
| 0x62 | created-player build; NBA headband-style hypothesis remains unproven (see probes above) | `Legacy Accessory 0x62` preserves old overrides |
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

`build_roster.py` clears the original accessory fields for every ProA player,
then reads the canonical workbook columns. Edit `data/overrides.xlsx` for
persistent selections. All fourteen accessory columns are grouped after the
appearance columns in **in-game menu order**, with the exact English slot names.
Their dropdowns use the Europe executable's literal option labels:

| Slot | Editor indices |
|---|---|
| Headband | 0 None, 1 Headband 1; encoded as signed `+0x67 = -1` / `0` |
| Shades | 0 None, 1..8 Shades 1..8 |
| Left / Right Arm Band | 0 None; 1..4 Upper Arm, 5..8 Lower Arm, 9..12 Sleeve |
| Left / Right Elbow Pad | 0 None; 1..4 Pad, 5..8 Sleeve, 9..12 Band |
| Left / Right Wrist Band | 0 None; 1..4 Forearm Band, 5..8 Wrist Band, 9..12 Dbl Wrist Band |
| Left / Right Knee Pad | 0 None; 1..4 Pad, 5..8 Brace, 9..12 Sleeve, 13..16 Strap, 17..20 Calf Sleeve |

Each four-entry colour group is White, Black, Team, 2nd Team; the dropdowns
preserve the game's `Wht`/`Blk` abbreviations where used. Shorts, sock length
and home/away sock colours retain the mappings above. String tables are at EE
`0x8FD358` (headband), `0x8FD360` (shades), `0x8FD518` (wrist),
`0x8FD550` (arm), `0x8FD588` (elbow), `0x8FD5C8` (knee),
`0x8FD630` (shorts), `0x8FD638` (socks), `0x8FD648` (sock colours).
They were checked in the complete 8,783,992-byte `SLES_530.22`, SHA256
`d60570a00122aac72bdf1b7768308f68ddb5a44b091c2251c20891e6c7a47611`.

Named wrist/elbow/knee values now mean **raw editor indices**, not the former
1/2 convenience presets. Old `wrist_l/r` presets 1/2 migrate to 7/3,
`arm_l/r` to **Elbow Pad** 11/6 (not Arm Band), and `knee_l/r` to 14/6.
Older CSVs/workbooks remain readable through those aliases; conflicting old
and named values are rejected. Other old raw item indices remain unchanged,
including experimental 0..255 wrist/elbow/knee values outside the menu range.
Dropdowns list only verified editor options, not invented names for raw indices.

An old nonzero `headband` becomes `Headband = 1`. Its extra build-byte setting
(preset 2 or other raw values) is preserved as `Legacy Accessory 0x62`.
The regular Headband dropdown has **only None and Headband 1**; there is no
verified alternate headband style. Created-player `Build` still owns `+0x62`
and overrides that legacy byte after accessories, as before.

`Legacy Accessory 0x62`, `Legacy Accessory 0x64`, `Legacy Accessory 0x65`
and `Legacy Goggles 0x66` follow the menu fields in an explicitly raw block.
They do not enable a created model. Blank columns preserve previous behavior:
wrist/elbow/knee/arm bands are cleared to 0, headband to 255, `+0x62` to 0,
other legacy bytes to 255, while shades, shorts and socks retain their
inherited values. Explicit 0 is written, including for shorts and sock colours.
An empty override cell means no override, not removal. See
[Persistent player edits](SeasonUpdateWorkflow.md#persistent-player-edits-and-exclusions).

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
