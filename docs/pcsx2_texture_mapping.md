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
Uniform textures exist at five resolutions: 512x256 (families `2253`/`2254`) and the LODs 128x64 (`19d3`), 64x32 (`1593`),
32x16 (`1153`), 16x8 (`0d13`). The LODs are mip levels of the 512x256 originals; some originals exist 2-3 times as
visually identical duplicates (NCC > 0.995 at 128x64; 139 visual groups from 210 files). `uniform_lods.py match` finds them
on the original dumps (never on the edited workspace): 128x64 against the hi-res (normalised cross-correlation), every
smaller LOD against the next larger one (strong evidence, independent of the hi-res) or directly against the hi-res.
Contact sheets for visual confirmation go to `docs/_tmp/uniform_lods/` (`dups_*`, `lods_*`, `unmatched_*`);
`uniform_lods.py save` freezes them as `data/uniform_lods/mapping.csv` (`key, role, master, size, score`;
`exclude.txt` removes wrong entries). Roles: `master` (the one duplicate you edit; the one you already edited wins,
otherwise the lexicographically first), `copy` (other duplicates), `lod`.
`texture_workspace.py sync` writes the master's replacement to every copy and box-downscales it for every LOD, so only the
`MASTER_*` files in `uniforms/512x256` need editing; `uniforms/512x256_duplicates` and `uniforms/auto_lods_*` are generated
(hand edits there are ignored). LODs without a dumped hi-res original (mostly shorts of teams never seen close up)
stay unmatched and remain manually editable. Missing links can be added by hand: pick the LOD from `data/uniform_lods/unmatched.csv`
(workspace file names + best guess), add a row `lod,master` to `data/uniform_lods/manual.csv` (file name, `__token`, 6-char id or key),
then `uniform_lods.py save`, `texture_workspace.py export`, `texture_workspace.py sync`.

## Open
Jerseys and name plates: see `PLAN.md`.
