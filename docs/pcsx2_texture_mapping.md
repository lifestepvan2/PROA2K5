# PCSX2 texture mapping (empirical method)

Texture keys cannot be derived from roster data, so they are measured: for each team the game is put on a
screen that shows the textures, a screenshot is taken, and the on-screen crops are matched against the
files PCSX2 dumps. The dump file name (`<hash1>-<hash2>-<family>.png`) is the replacement key; a PNG with
the same name in `replacements\` replaces the texture.

Folder: `%USERPROFILE%\Documents\PCSX2\textures\SLES-53022\{dumps,replacements}`.
PCSX2 settings: texture dumping and replacement on. A texture is dumped once per session and not while a
replacement with that key exists, so **scans need an empty `replacements\` and a fresh `dumps\`**
(rename the old one while PCSX2 is closed).

## Dump families
| family | size | content |
|---|---|---|
| `00001dd3` | 128x128 | player face; only the window (0,3)-(102,125) is visible on screen |
| `00001553` | 32x32 | small team logo (Start Game icons); visible window (4,5)-(28,27), drawn 80x62 px |
| `00002213` | 256x256 | large logos (not mapped yet) |

## Procedure
1. Load the roster, go to Team Select (left = slot 15, right = slot 9 after loading), save state slot 1 (F1).
2. `python scripts/texture_scan_run.py -9 -8 ... 20` (about 1 min per team). For each k: F3, pad to the right
   slot, R1 (k>0) or L1 (k<0) |k| times, Cross, wait for the Start Game screen, screenshot to `docs/_scans/k<k>.png`.
   Right team slot = 9 + k; the left team (slot 15) is on every screen. PCSX2 must stay in the foreground.
   Icons and logos are keyed by **NBA slot**, not by ProA team, so this scan is done once (slots 0-29 are covered)
   and stays valid when the ProA team order changes (`data/team_slots.csv`). The k9-k20 scans were taken with a
   slightly different window position (`ICON_BOX_NEW` in `build_team_icons.py`).
3. `python scripts/build_texture_map.py` (legacy, superseded by `record_faces.csv`, see below) matched the starter
   faces -> `data/texture_map/starter_faces.csv` (stale; keyed by the old slot order).
4. `python scripts/build_team_icons.py` -> `data/texture_map/team_icons.csv` (30 slots, 30 unique keys, scores 0.90-0.99).
5. `python scripts/gen_replacements.py` writes the replacement PNGs (ProA headshots from `assets/PS_out`
   by `proa_id`, logos from `nba2k_editor/assets/<38+ProA index>.png` placed on the icon of the NBA slot the team
   occupies) into `replacements\`. Files that an earlier run wrote but the current one no longer needs are removed
   (state in `pipeline_managed.json`). F10 reloads textures.

Matching scores are 0.88-0.98 for the right dump and clearly lower for others; the matchers print shared keys
and low scores. Matching must run after the scans because PCSX2 writes dump files with a delay.

## All 792 player records (exact, no per-team scrolling)
The dump key is a content hash of the image and the ISO archive (`/VC_53022/*.`) is hashed and compressed, so the
game's record -> texture link cannot be derived statically. Instead, the live injection scan reads it directly:
the Start Game screen draws the faces of the team's *starter pointers* (team record +0x90), so writing 10 arbitrary
player-record pointers there shows 10 arbitrary faces.

1. Empty `replacements\` (dumps are only written for keys without a replacement), refresh `docs/ps2_ram_base.txt`
   (`python scripts/full_scan_ps2_base.py`, changes every launch), open Start Game for slot 15 vs 9.
2. `python scripts/face_scan_inject.py 0 792` (80 batches, ~31 s each) -> `docs/_faces/b<first>.png`.
   Writes use `fast_scan.write_ps2_ram` (WriteProcessMemory); PINE writes fail.
3. `python scripts/build_record_faces.py` -> `data/texture_map/record_faces.csv` (record, key, score, runner_up, shared).
   `texture_scan.normalize()` warps screenshots of other window sizes into the 1934x1039 reference frame.

Record classes: 0-394 = players of NBA teams 0-29; 395-574 = legend-team-only players (teams 32-49);
578-791 and a few others = unreferenced create-a-player dummies, all sharing one silhouette texture.
Ten NBA records share the same placeholder portrait (39, 94, 95, 119, 121, 161, 171, 208, 226, 329), five more share a
second generic face (122, 172, 242, 315, 342), and some NBA players share their face with a legend duplicate
(e.g. Iverson 0 / 529 / 554). A replacement PNG replaces the texture for every user of the key.

`build_roster.py` therefore only places ProA players on records with a unique key, a match score >= 0.87 and no
legend-team reference (335 records). A ProA team first uses the qualifying records of its own NBA slot (final
mapping: ProA teams on slots 12-29, `data/team_slots.csv`); missing records are borrowed from the donor teams on
slots 0-11, which shrink. Legend and conference teams stay untouched, so historic
players keep their faces. `gen_replacements.py` writes one face per ProA player keyed by its record.

## Team logos
The 32x32 icons are zoomed crops of the full logos, so a multi-scale `cv2.matchTemplate` of each icon finds the
full-size logo textures (`logo_refs.csv`: 18 ProA + 12 donor reference frames, picked by eye). `build_logo_map.py`
(about 5 minutes) then matches every dump against those references: mode A = the dump is a window of the reference
frame (cropped/partial logos, different sizes), mode B = the reference sits inside the dump (signs). Raw matches are
noisy (number strips, faces), so `gen_logo_replacements.ACCEPT` filters on score, MAE, content fraction and window
size; 108 ProA variants pass (after a home game per ProA team was dumped) and were reviewed visually. 128x128 variants
live in the face family `00001dd3` (pre-game banner), so that family is matched too. Pistons (the default home team =
Falcons) has two references: the PISTONS ball (Team Select) and the horse logo (banner, `a252ef5c...-00002213`).
Incremental runs: `build_logo_map.py --since "YYYY-MM-DD HH:MM"` or `--families "00002213,00001993"` match only part of
the dumps and merge into the csv (quote the family list). The ProA logo is fitted into the reference's content box and
cut to each variant's window. Alpha is written in PS2 range 0..128. The content threshold scales with the reference's
own content (thin logos such as Rockets/Wizards), and score >= 0.75 adds the right halves of split logos (Lakers).

PCSX2 only dumps textures without a replacement, once per process: to see what is still unreplaced, restart PCSX2 with
an empty `dumps` folder (the in-memory set is not reset by F10 or by moving files), replay, then merge the folder back.

## Texture workspace (manual replacements)
`python scripts/texture_workspace.py export` mirrors all dumps (`dumps` + the older `bu` session) into
`texture_workspace/<group>/<subgroup>/<label>__<token>.png`: known maps first (faces by NBA player, team logos), then
family rules (video tiles, crowd sprites, name plates, jerseys...), then k-means content clusters for the mixed
families (`texcluster.py`, names in `cluster_names.json`). Edit files in place (any size/format; keep the `__token`;
folders may be rearranged), then `texture_workspace.py sync` writes them to `replacements\` resized to the original
resolution (`--fit stretch|contain|cover`) and F10 reloads in PCSX2. Restoring a file reverts it. Exported files use
normal 0..255 alpha; sync converts back to PS2 0..128, and images without alpha keep the original transparency.
Textures managed by the pipeline (ProA faces, team icons, logo variants) are not exported and win on conflicts.
Verified in-game: stretched RGB replacement of full jerseys, alpha cut-outs of numbers, revert. PCSX2 must be
unpaused (Space) for a reload to take effect on screen.

### Uniform LODs and duplicates (`scripts/uniform_lods.py`, `data/uniform_lods/`)
### Uniform LODs and duplicates (`scripts/uniform_labels.py`, file names in `texture_workspace/uniforms/`)
Uniform textures exist at five resolutions: 512x256 (families `2253`/`2254`) and the LODs 256x128 (`1e13`), 128x64 (`19d3`), 64x32 (`1593`),
32x16 (`1153`), 16x8 (`0d13`). The LODs are mip levels of the 512x256 originals (all levels share the middle hash of the dump key);
some originals exist 2-3 times as visually identical duplicates (NCC > 0.995 at 128x64). The 256x256 cloth textures (family `2213`) have only duplicates.

Which file inherits from which is stored in the **file name**: `ROLE__LABEL__RES__ID.png` (`MASTER`, `COPY`, `LOD`; same label = same group;
ID = dump token). `texture_workspace.py sync` writes the master's replacement to every COPY and box-downscales it (alpha-weighted)
for every LOD, so only the `MASTER__*` files need editing; hand edits of COPY / LOD files are ignored. Exactly one MASTER per label
is required (otherwise a warning and the group is skipped). New dumps are named automatically by `uniform_labels.py adopt`
(run by `export`): image matching (`uniform_lods.analyse`: 128x64 against the hi-res by normalised cross-correlation, every smaller LOD against
the next larger one or the hi-res) decides COPY / LOD of an existing label or opens `Unsorted<n>`. The decisions are plain file names, so they are
corrected with the file explorer or `uniform_labels.py relabel|link|promote`. `data/uniform_lods/labels_snapshot.csv` is the tracked copy of all names.
Full step-by-step: [JerseyTextureWorkflow.md](./JerseyTextureWorkflow.md).

## In-game player models: pid -> face / arm / neck

The link was found by reading the live RAM (no ID-stamp scaling needed; `head_probe_obs.csv` holds the 17 user observations
used to verify it: all 10 faces and 7 necks match).

- Every loaded player model has a file object named `p<ID><h|a>.iff` (UTF-16; `h` = home team, `a` = away team) with a pointer to
  the head `SCNE` at `+0xBC`. **ID = u16 at player record +4** (a second copy at +6). It identifies the *person* (629 distinct
  values in 792 records), not the record. ProA records inherit the pid of the NBA slot they replace, so the face asset belongs to
  the original NBA player of that slot.
- From the head `SCNE`, walk the `prev` pointers (offset 0): `TXTR` objects `neck`, `arm`, (a second `SCNE` for the body/hair,
  skip it), `face` and sometimes `hair`. `TXTR`: `+0xC` magic, `+0x10` name ptr (UTF-16), `+0x14` data header; header `+0x18`
  pixel pointer, `+0x2C/+0x2E` width/height. Faces 256x256, arms 128x128, necks 128x64, hair 64x64.
- Pixels are linear PSMT8 followed by a 1 KB CSM1-swizzled palette (index swizzle `i ^ ((((i>>3)&1)^((i>>4)&1))*0x18)`); the RGBA
  words equal the dump PNGs exactly, so a texture is matched to its dump key by an exact pixel compare (`txtr_match.py`).
- Faces are unique per pid. **Necks and arms are shared by skin class** (about 200 neck and 90 arm textures for 270 pids), so a
  replacement neck/arm affects every player sharing it.
- 24 models are loaded per game (12 per team). Rematch does not reload them; a real game start (Team Select -> Start -> Start Game
  -> Cross) re-reads the team structs. The ISO holds the assets hashed/compressed, so the mapping cannot be read statically.

Tools: `scripts/live_players.py` (read RAM now, merge into `data/texture_map/pid_textures.csv`), `scripts/face_load_scan.py`
(automated: loads savestate slot 2 = Team Select of team slot 28 (home) vs 16 (away), writes 12 record pointers + 5 starters into both
team structs (`TEAM_BASE + team*0x124`, roster ptrs at +0, starters at +0x90), starts the game, waits for the models, reads them
back; ~12 batches cover all 269 ProA pids; `--retry` re-loads pids whose face/neck has no dump, as starters). Only textures that PCSX2
has dumped can be matched; some faces never got dumped even when loaded on court (needs a close-up or more play).
`txtr_inventory.py` lists all TXTRs in RAM, `ram_dump.py ADDR LEN` hexdumps RAM, `head_ram_probe.py` finds a PNG's palette window.

## Casting ProA players with existing NBA models (pid swap)

Overwriting the pid (u16 at record +4/+6) makes the game load that NBA player's model (face, neck, arm textures; verified with
`scripts/pid_swap_test.py`). Name, number and ratings still come from the record. Only pids of NBA-team records (team slot < 39 in
`data/nba_defaults/players_unknown.csv`) are safe; higher slots are staff/placeholder models.

1. `face_load_scan.py --faces` saves every NBA pid's face/neck/arm texture from RAM to `data/face_match/faces/` (untracked, ~50 MB).
2. `face_embed.py` embeds ProA headshots (`assets/PS_out`) and those face textures (ArcFace `buffalo_l`, insightface).
3. `face_match.py` assigns each ProA player an NBA face model by ArcFace similarity plus skin lightness. The photo lightness is
   calibrated onto the texture lightness scale with the fixed curve `SKIN_CAL` (a per-photo-set percentile mapping wrongly darkened
   pale players). Every player gets a distinct pid league-wide (single Hungarian solve; `--w-skin` weights the lightness, default
   2.0), because the lineup headshot is keyed by pid. Only ~137 NBA faces are light but ~180 ProA players are, so the shortfall is
   covered by the **light reserve** (item 7): extra pids whose face is recoloured light. Writes **`data/face_match/proa_pid_map.csv`**, the single editable
   file: `pid` = automatic match, `override_pid` = manual pick (never written by the script, wins in `build_roster.py`).
   Players already in the file keep their pid on later runs (season updates only match new players); `--rematch` redoes all
   automatic matches and keeps overrides. Review via the contact sheets in `docs/_face_sheets/` (one per team, git-ignored); don't
   open them in a viewer that steals focus while PCSX2 automation runs.
4. `build_roster.py` writes the pid into both record fields (`player_map.csv` gets a `pid` column); unknown pids abort the build,
   players without a map entry keep the model of their record (reported in `report.md`).
5. **Lineup headshots follow the pid, not the record.** `gen_replacements.py` therefore writes each ProA headshot to the portrait
   key(s) of the NBA record that originally had the player's pid (`pid_keys()`). Consequence: a pid shared by players of different
   teams shows only the best player's headshot in the lineup portrait (`gen_replacements.py` lists these as CONFLICT), which is
   why face_match never reuses a pid. Pids whose portrait texture is shared with other pids (generic placeholders) are excluded
   from the candidates.
6. **Legs follow the record, not the pid.** The in-game textures `legs00`-`legs05` (128x128, one per skin tone; dump keys
   `17f9af64509fc471-<mid>-00001dd3`, mid = `3f1c16ddd47b1c3c, 30e4d3ebd8b48e10, 2d706d2a3649c572, 39f932e44379311f,
   1c94ddc2e789addf, 99b5644de059ce43` for tone 0..5, darkest to lightest) are not part of the `p<ID>h.iff` model. The tone is
   the record byte **+0x69** (6 values over all NBA records; the mean arm colour of the pid's arm texture is a function of it,
   r=0.985). A cast player kept the tone of the record he was written into, giving e.g. a white face with dark legs.
   `build_roster.py` now copies +0x69 from the NBA record that owns the pid (`load_skin_tones()`). Found by scanning RAM for
   TXTR names (the six `legsNN` objects all alias one pixel buffer that the engine fills per draw) and matching the structure of
   the dumped 128x128 textures against it.
7. **Light reserve (recoloured faces).** Arms are baked into the `p<ID>h.iff` model, so a pid's arm class cannot be chosen
   freely; the arm texture is shared by all pids of a skin class, and the class equals the record tone +0x69 exactly
   (tone 5: 95 pids, 3: 63+9, 2: 55, 1: 34, 0: 8). `skin_brighten.py` therefore *reserves* the largest tone-3 arm class
   (82 pids, key `bf7f58d465c440ee-1619018f767b405a-00001dd3`): its arm texture is replaced by the pixels of the tone-5 arm, its
   legs use tone 5 (`load_skin_tones()`), and each reserved pid's face and neck can be recoloured light per player.
   - `skin_brighten.py scan` writes `data/texture_map/pid_skin_keys.csv` (pid -> face/neck/arm dump key by RGB md5 of the RAM
     saves; the reserve is usable only with a unique face key and a neck not shared with another face: 53 of 82 pids, 23
     were never dumped, so `face_load_scan --retry` can grow the pool). `embed` writes `data/face_match/bright.npz`
     (ArcFace + lightness of every usable reserved face recoloured to a reference light tone).
   - Recolour: Lab shift of the skin pixels (median cheek tone -> light target, `skin_ab()` gives matching a/b), weighted by a
     smoothed skin mask, so hair, brows, eyes and stubble stay dark and the structure is unchanged; highlights are compressed.
   - `face_match.py` treats these as extra light candidates (`skin_target` column in `proa_pid_map.csv` holds the lightness the
     recolour aims at); `gen_skin_replacements.py` writes the recoloured face/neck PNGs (dump alpha kept) and the light arm into
     `replacements\` (pipeline-managed keys, pruned when no longer needed).
   - Side effect: classic/historic teams that still use reserved NBA models show dark faces with light arms.
   - The 9 pids of the second tone-3 arm class (`303a37...`) are left unchanged.

New roster/season: run `build_roster.py` (writes `player_map.csv`), `face_embed.py`, `face_match.py`, review, `build_roster.py` again,
then `gen_skin_replacements.py`. After new face dumps: `skin_brighten.py scan` and `embed`, then `face_match.py --rematch`.

## Labelling textures by home team (arena_props, uniform_parts, loading tiles, courts)

Method: **per-home-team live scan**. `scripts/arena_scan.py scan <slots>` loads a game with each NBA team as HOME (the right-hand team on Team Select; slot at PS2 `0x801908`), with an empty dump folder and a fresh PCSX2 process (a texture is dumped only once per process), and records which dump keys appear. Evidence is in `data/texture_labels/home_scan/slot*.txt` and `home_scan_summary.csv` (`arena_scan.py report`). `restore` repairs the dump folder if a scan is interrupted.
Attribution: 1 team -> that team; 2-4 -> `A+B`; 5 or more -> `various`. 7,632 of 8,975 keys belong to exactly one team.

Pipeline: `arena_scan.py scan/report` -> `texture_workspace.py export` -> `label_textures.py build` (adds rows to `data/texture_labels/labels.csv`, never overwrites; hand labels from `visual_labels.csv`) -> `texture_workspace.py export` (renames/regroups to `<Team>_<group>_<WxH>__<token>.png`; uniform-family textures are named `ROLE__LABEL__RES__ID.png` by `uniform_labels.py adopt`, see `JerseyTextureWorkflow.md`). Edit `labels.csv` to correct a label, then re-run `export`.

Caveats: the away team is fixed to Magic in the savestate, so Magic-away items appear in every run and are labelled `various`; late slots (Warriors) under-captured loading tiles (labelled visually, source `visual`); items never seen in any scan keep their old names.

## Court rendering investigation (2026-11-08)

Initially captured EE RAM and a four-field GS trace from the paused Falcons/Pistons
replay read-only. Subsequent user-approved probes changed one four-byte colour word
at a time and restored/read back its exact original bytes. No controller navigation,
ISO changes or emulator setting changes occurred.

The live court graphics match **`s021.iff`**, archive record 2365, ISO offset
`0x17A90800`, size 1,202,144 bytes in the pristine Europe ISO. Its court `SCNE` chunk
starts at bundle `+0xB6AA0`: compressed body 286,672 bytes, decoded system 116,480
bytes (`0x1C700`) and video 504,320 bytes. Embedded GS texture descriptors are not
ordinary named `TXTR` objects, explaining why the initial live texture-name inventory
missed these sources.

Offsets below are relative to that **decoded court SCNE body**, not the compressed
ISO bytes:

| Source | Descriptor | Pixel/video start | Verified representation |
|---|---|---|---|
| `floor_stuff_vcSwShader2` | `0x490` | `0x48700` | 64x32 PSMT4 horizontal white stripe: 256 opaque base pixels, 1,792 transparent pixels; 16-entry RGBA CLUT at `0x48C70` |
| `lines1` | `0x4C8` | `0x48CB0` | 64x64 PSMT8 diagonal line segment with antialiased alpha |
| `lines5` | `0x500` | `0x4A620` | 256x256 PSMT8 red filled-circle texture with transparent exterior and antialiased edge |
| `test_lines1` | `0x5A8` | `0x8C620` | 64x64 PSMT8 short curved white segment |
| `test_lines3` | `0x5E0` | `0x8DF90` | 64x64 PSMT8 short near-horizontal white segment |

Court geometry stretches/positions these masks; there is no single full-court line
image. Material records are 0x60 bytes for the verified shader records: the
self-relative name pointer is at `+0x08`, packed RGBA at `+0x58`, and the
self-relative GS-descriptor pointer at `+0x5C`. `lines1`, `lines5`, `test_lines1`
and `test_lines3` have white RGBA controls in both the source and captured RAM.

The **true out-of-bounds apron is reddish-brown**, not the blue area seen inside
the court in the initial camera view. A later sideline camera view exposed this
misattribution. Its base colour comes from material **`vcSwShader4`**, record
`0x6E0`, packed RGBA at decoded **`0x738`**: `(126,52,40,255)`, RGB `#7E3428`.
The material's texture pointer at `0x73C` is zero; it does not supply its colour
through an editable texture CLUT. This is separate from the red key/circle source
below.

The red-circle base predominantly samples logical palette index 10,
RGBA `(110, 0, 0, 128)`. That entry is at decoded `0x5E7A8`. The complete
90,112-byte packed video transfer matches the ISO scene and captured RAM, not just
a repeated-colour prefix. GS alpha 128 is full opacity: the circle interior is
not uniformly translucent. Its draw uses texture modulation and normal alpha
blending, with vertex alpha 128.

Approved live probes confirmed:

| Source edit | Visible result | Restoration |
|---|---|---|
| Red-circle CLUT index 10: `(110,0,0,128)` to `(0,110,110,128)` | Both the rectangular red key and free-throw circles turned cyan; 335,957 pixels passed the red-to-cyan change test | Exact original four bytes verified through host RAM and PINE |
| `floor_stuff_vcSwShader2` material RGBA at decoded `0xA38`: white to green | Selected straight lane/boundary lines and short markings turned green (35,397 pixels); curved lines stayed white | Exact original four bytes verified |
| `lines1` material RGBA at decoded `0x8B8`: white to green | A small diagonal/far-court line segment changed (156 pixels); not every curved marking | Exact original four bytes verified |
| `floor_stuff_vcSwShader5` material RGBA at decoded `0x798`: grey to green | No visible recolouring of the blue in-bounds region previously misidentified as out-of-bounds | Exact original four bytes verified |
| `vcSwShader4` material RGBA at decoded `0x738`: `(126,52,40,255)` to `(0,126,0,255)` | The true reddish-brown sideline/baseline apron turned green; in-bounds hardwood and white markings retained their colours | Exact original four bytes verified through host RAM and PINE |

Final PINE reads confirmed all five original source words. Comparing the initial four-probe restored
viewport with the first probe's baseline found no pixel differing by more than 20
RGB levels; mean absolute RGB difference was 0.025 levels, consistent with minor
rendering variation rather than a changed pose or retained recolouring.
The later sideline probe changed 406,717 pixels under a brown-to-green test.
A clear apron sample had median RGB `(131,51,28)` before, `(0,130,0)` during the
probe, and `(131,51,28)` after restoration. Alpha was preserved at 255.
That probe captured only the unobstructed game region because Windows refused
foreground focus transfer; no controller input or camera navigation was used.

The red texture is therefore reused for both filled circles and the rectangular
key, rather than being a separate complete key image. Other palette entries still
control antialiasing/mips: changing only the dominant entry is a diagnostic, not a
finished recolouring algorithm. White line colour controls are material RGBA,
distinct from the paint CLUT.

There is also subsequent wood-textured geometry with normal alpha blending:
vertex alpha 34, texture alpha 0..125, giving effective GS alpha 0..33 after
modulation. A separate additive lighting pass uses a shared 32x32 greyscale spot
texture and red/blue vertex tints. That spot's pixel and CLUT transfers match the
first arena `SCNE` chunk exactly. These additional passes must be considered when
explaining visible grain/reflections; the earlier red/blue vertex-tint observation
alone does not identify the base paint controls.

The out-of-bounds colour control is now confirmed. Its grain and reflections
remain visible after the material-colour change, consistent with the separate
wood/light passes rather than a baked reddish hardwood texture.

The blue **in-bounds lane/zone** is also confirmed, but uses a third representation:
**packed vertex RGB in the court scene's `paint` mesh**, not a CLUT or one material
RGB field. The mesh name pointer at decoded `0xDC0` resolves to `paint`; its
two-part table pointer at `0xDEC` resolves to `0x1BC70`, and its VIF data starts
at `0x1BCC0`. The complete source stream matches captured EE RAM at `0x18A1300`.
The two VIF `UNPACK V4-8` commands are `0x6E04412B` at `0x1BD04` and
`0x6E0441E1` at `0x1BDA8`; each supplies four RGBA vertices:

| Lane end | Decoded RGBA offsets | Original RGBA values, in stream order |
|---|---|---|
| Positive court Z | `0x1BD08`, `0x1BD0C`, `0x1BD10`, `0x1BD14` | `(52,78,128,128)`, `(17,31,81,128)`, `(0,0,95,128)`, `(0,0,0,95)` |
| Negative court Z | `0x1BDAC`, `0x1BDB0`, `0x1BDB4`, `0x1BDB8` | `(43,80,128,128)`, `(27,30,44,128)`, `(0,44,128,128)`, `(9,36,74,95)` |

The corresponding position streams at `0x1BD3C` and `0x1BDE0` describe mirrored
lane rectangles: X approximately -242..242, Z approximately 852..1436 or
-1436..-852, Y zero. Source colours already vary by corner; the rendered zone
also receives lighting, wood and reflection passes. There is no single original
blue hex colour that describes all of it.

An approved single-word probe at decoded **`0x1BDB4`**, captured EE
`0x18A13F4`, changed `(0,44,128,128)` to `(0,128,0,128)`. The visible blue zone
shifted toward green with interpolation toward the unchanged corners; 462,783
pixels gained more than 10 green levels and lost more than 10 blue levels.
Red paint, white lines, wood grain and reflections remained. Exact original bytes
were restored and independently verified through host RAM and PINE. The opposite
lane's first-vertex probe produced no visible change in this close-up; its source
assignment follows the matching mirrored geometry, not a separate visual proof.
A main-arena blue vertex probe also produced no visible change and is not the
zone control. Do not label the separate blue lighting tint as base paint.

### Court-colour tool design readiness

The verified court needs three bounded edit types: material RGB for the apron
and line masks, CLUT RGB for red paint, and vertex RGB for blue lane paint.
Preserve alpha, positions, topology, descriptors, indices and mip pixels.
Lane recolouring must cover all eight colour words, with an explicit policy for
retaining the original corner shading versus making the base vertex RGB uniform.
One-word probes establish ownership, not a finished whole-zone recolouring.

Read-only rebuilding experiments changed all eight lane RGB values to green,
then combined those edits with the apron RGB change. Both round-tripped exactly
inside the original court SCNE's 286,672-byte stored span and 16-byte scratch
limit using the existing bounded VC-LZ rebuilder; each used 286,660 bytes.
Only the requested RGB bytes differed after decoding. These are feasibility
checks, not an ISO patch or proof that every colour combination fits.

Before an all-30-arena tool is ready, inventory and structurally resolve each
arena's scene/material/mesh/CLUT locations; these names and offsets have only
been established for `s021.iff`. Complete the remaining curved/short-line
mask assignments if separate line-category controls are wanted. Recolour every
relevant paint palette entry, including antialiasing/mip colours, and validate
combined edits against stored-span/scratch bounds. Finally, confirm a published
ISO after a fresh boot at both court ends and multiple viewing distances.
Opacity authoring and geometry/line-shape edits are separate, unimplemented scope;
RGB-only tools can preserve the existing layered rendering without solving them.
Do not infer source ownership from the workspace's team labels alone: identical
white masks were found under multiple dump keys/team labels.

Court video contains pre-swizzled GS data and CLUTs inside compressed `SCNE`
resources. Do not apply the lettering assumption that the final 1,024 bytes are
the palette. IMAGE tags can split one transfer (e.g. 65,536 + 24,576 bytes);
VRAM addresses are reused, so attribution requires transfer versions and offsets.

## Open
Jerseys and name plates: see `PLAN.md`.
