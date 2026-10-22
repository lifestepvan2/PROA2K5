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

## Open
Jerseys and name plates: see `PLAN.md`.
