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
1. Load the ProA roster, go to Team Select (left = slot 15, right = slot 9 after loading), save state slot 1 (F1).
2. `python scripts/texture_scan_run.py -9 -8 ... 8` (about 1 min per team). For each k: F3, pad to the right
   slot, R1 (k>0) or L1 (k<0) |k| times, Cross, wait for the Start Game screen, screenshot to `docs/_scans/k<k>.png`.
   Right team slot = 9 + k; the left team (slot 15) is on every screen. PCSX2 must stay in the foreground.
3. `python scripts/build_texture_map.py` matches the 5x2 face cells (column = starter index PG..C, same order as
   `data/roster_build/player_map.csv`) -> `data/texture_map/starter_faces.csv`.
4. `python scripts/build_team_icons.py` -> `data/texture_map/team_icons.csv`.
5. `python scripts/gen_replacements.py` writes the replacement PNGs (ProA headshots from `assets/PS_out`
   by `proa_id`, logos from `nba2k_editor/assets/<38+slot>.png`) into `replacements\`. F10 reloads textures.

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
legend-team reference (335 records; 207 in ProA slots 0-17, 128 in donor slots 18-29). Missing records are borrowed
from donor teams 18-22, which shrink to 7-9 players. Legend and conference teams stay untouched, so historic
players keep their faces. `gen_replacements.py` writes one face per ProA player keyed by its record.

## Open
Large logos, jerseys: see `PLAN.md`.
