# Jersey (uniform) texture workflow

How to replace jersey / shorts / warm-up textures and keep their low-res LODs and duplicates in sync.
Background and file formats: [pcsx2_texture_mapping.md](./pcsx2_texture_mapping.md).

## The three places

| Place | Purpose | Edit it? |
|---|---|---|
| `texture_workspace/uniforms/512x256/MASTER_*.png` | the hi-res master of each group | **yes - the only place to edit** |
| `texture_workspace/uniforms/512x256_duplicates/copy-of-MASTER-*` and `auto_lods_<size>/AUTO-LOD-of-MASTER-*` | generated from the master by `sync` | no (hand edits are ignored) |
| `texture_workspace/uniforms/visual_sort/` | copies used only to sort textures into groups | no (editing does nothing; ignored by all scans) |

Unmatched LODs (still in `128x64`, `64x32`, `32x16`, `16x8`) and the `64x64` files are not generated from anything
and stay editable by hand until they are mapped.

## 1. Replace a texture

1. Edit the `MASTER_*` file in `texture_workspace/uniforms/512x256` (keep the file name and 512x256 size).
2. `python scripts/texture_workspace.py sync` - writes the master's replacement to the live replacement folder, copies it to
   every duplicate and box-downscales it for every LOD (128x64, 64x32, 32x16, 16x8).
3. Press **F10** in PCSX2 to reload the textures.

Files that the roster pipeline already replaces (team logos, player faces, ...) take priority over the workspace.

## 2. Change which textures belong together (the sort tree)

Each group is one folder inside `visual_sort/` (any depth; the usual layout is `Team/Home|Away|Alt/Jersey|shorts/g_<token>`, warm-ups in `Team/warmups`):

- a 512x256 file is a hi-res texture; the one named `MASTER_*` is the **master**, other 512x256 files are its **duplicates**
- every smaller 2:1 file (128x64, 64x32, 32x16, 16x8) in the same folder is a **LOD** of that master
- to change the master, put `MASTER_` in front of another 512x256 file's name
- files in `unsorted/`, or in a folder with no 512x256 file, are not mapped
- being in the same folder as a master is what links a texture to it; just drag files between folders

After editing the tree:

1. `python scripts/uniform_sort.py apply --check` - dry run: reports changes and folders without a `MASTER_` file (one is picked automatically).
2. `python scripts/uniform_sort.py apply` - writes `data/uniform_lods/sorted.csv`, regenerates `data/uniform_lods/mapping.csv` and fixes the `MASTER_` prefixes on the sorting copies.
3. `python scripts/texture_workspace.py export` - regroups the real workspace files (masters -> `512x256`, duplicates -> `512x256_duplicates`, LODs -> `auto_lods_<size>`).
4. `python scripts/texture_workspace.py sync`, then F10 in PCSX2.

If you had already edited the old master and then make another file the master, `sync` uses the edited duplicate
while the new master is unedited and prints a note - watch for it so no work is lost.

## 3. After new texture dumps

Dump the textures in game (pregame cutscenes for warm-ups, close-ups for shorts), then:

1. `python scripts/texture_workspace.py export`
2. `python scripts/uniform_lods.py match` - re-detects duplicates and LODs (contact sheets in `docs/_tmp/uniform_lods/`)
3. `python scripts/uniform_lods.py save` - freezes the mapping; your `sorted.csv` still overrides it
4. `python scripts/uniform_sort.py populate` - adds only the new files to the tree (new groups go to `unknown/`, unmatched files to `unsorted/`); existing files are never touched
5. sort the new groups by hand, then continue at step 2 above.

## File reference

| File | Meaning |
|---|---|
| `data/uniform_lods/mapping.csv` | final mapping: key, role (master / copy / lod), master, size, score |
| `data/uniform_lods/sorted.csv` | result of the last `uniform_sort.py apply`; wins over everything else (role `none` = unmapped) |
| `data/uniform_lods/manual.csv` | optional hand-typed `lod,master` pairs (the sort tree is easier) |
| `data/uniform_lods/exclude.txt` | keys / 6-char ids that must never be matched |
| `data/uniform_lods/unmatched.csv` | LODs without a hi-res original (probably not dumped yet) |
| `data/uniform_lods/candidates.csv` | raw `match` output with scores |
