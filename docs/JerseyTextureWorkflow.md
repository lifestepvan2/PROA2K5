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
and stay editable by hand until they are mapped. LODs are matched by image similarity and by the middle hash of the dump
key, which all mip levels of one texture share (exact; this is how the 256x128 level, family `00001e13`, is linked).

## 1. Replace a texture

1. Edit the `MASTER_*` file in `texture_workspace/uniforms/512x256` (keep the file name and 512x256 size).
2. `python scripts/texture_workspace.py sync` - writes the master's replacement to the live replacement folder, copies it to
   every duplicate and box-downscales it for every LOD (256x128, 128x64, 64x32, 32x16, 16x8).
3. Press **F10** in PCSX2 to reload the textures.

Files that the roster pipeline already replaces (team logos, player faces, ...) take priority over the workspace.

## 2. Change which textures belong together (the sort tree)

Each group is one folder inside `visual_sort/` (any depth; the usual layout is `Team/Home|Away|Alt/Jersey|shorts/g_<token>`, warm-ups in `Team/warmups`):

- a 512x256 file is a hi-res texture; the one named `MASTER_*` is the **master**, other 512x256 files are its **duplicates**
- every smaller 2:1 file (256x128, 128x64, 64x32, 32x16, 16x8) in the same folder is a **LOD** of that master
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

## 4. Generate baseline team jerseys (all 18 ProA teams)

`python scripts/create_baseline_jersey.py` colourises `texture_workspace/uniforms/templates/{jersey,short,warmup}_tmpl.png`
and writes the result over each team's home and away MASTER 512x256 textures (located through the sort tree), then
`python scripts/texture_workspace.py sync` rebuilds the duplicates and LODs, then F10 in PCSX2.

- Colours: `color1` / `color2` (hex) in `data/proa_teams.csv`. Home = white body, `color1` trim and short stripes. Away = `color1` body, `color2` trim/stripes. Edit and re-run.
- Cloth structure (folds, perforations) is kept: every template region is divided by its median brightness and that shade map is applied on the target colour (`HIGHLIGHT` in the script tames the bright side).
- **Fabric layers for manual editing:** `python scripts/create_baseline_jersey.py --fabric` exports that shade map to `texture_workspace/uniforms/templates/fabric/` for the jersey, shorts and warm-up (`<kind>_fabric_overlay.png` and `<kind>_fabric_shadow_light.png`). Put one on top of your flat colour/logo layers in Photoshop/GIMP:
  - `*_overlay.png`: grey, 128 = neutral. Set the layer's blend mode to Overlay (strong), Soft Light (gentle) or Linear Light.
  - `*_shadow_light.png`: black (darkens) and white (lightens) pixels whose alpha is the strength; plain Normal blend, adjust with layer opacity.
  Same 512x256 layout as the textures. They are independent of team colour, so one set serves all teams.
- Logos: ProA patch (`data/proa_logo.png`) on the player's left breast and club logo (`nba2k_editor/assets/<38+index>.png`) on the right breast of the jerseys. Shorts are plain. Positions are constants at the top of the script.
- Warm-ups: one plain jacket per team in `color1` with the club logo on the chest (`warmup_tmpl.png`), written to every MASTER filed under `visual_sort/<Team>/warmups/` (all groups). Textures there that are not warm-ups go into `NOT_WARMUPS`. Unsorted warm-up dumps are only picked up once they are sorted into that folder.
- Output PNGs have no alpha channel, so `sync` keeps the game's original per-pixel alpha.
- **Cloth (warm-up top with sleeves, full-length trouser legs):** the semi-transparent 256x256 textures in `uniforms/cloth_256x256` (labelled `<Team>_cloth-top` / `<Team>_cloth-shorts`) are treated like the warm-ups. Every MASTER under `visual_sort/<Team>/cloth/` is generated from the logo-less templates `templates/cloth_top_tmpl.png` (sleeves/torso) and `templates/cloth_shorts_tmpl.png` (trouser legs) in the team's `color1` (plain, folds kept; all variants of a team get the same texture, the kind - top or shorts - comes from the file's label). Teams without a dumped cloth texture are skipped ("no MASTER found"). The files carry no LODs, only pixel-identical duplicates: `uniform_sort.py populate` (or `label_textures.py sort`) puts each team's cloth into `<Team>/cloth/g_<token>/` with a `MASTER_` file and its identical copies, `apply` + `export` + `sync` then propagate edits of the master to the copies like for the jerseys. Textures of an unknown team sit in `unknown/cloth/`; move a group folder into the right `<Team>/cloth/` once identified. Cloth wrongly filed under arena_props: add a row to `data/texture_labels/visual_labels.csv` (`token,team,cloth-top|cloth-shorts,uniforms,cloth_256x256,evidence`), run `label_textures.py build`, `texture_workspace.py export`, `label_textures.py sort`.
- Cloth fabric layers: `--fabric` also writes `warmup_sleeves_fabric_*.png` and `warmup_legs_fabric_*.png` (256x256), the crease structure of the two cloth templates. Existing layer files are not overwritten (`--fabric --overwrite` regenerates them).
- Safety: the original is copied once to `texture_workspace/uniforms/backups/`; a MASTER is only replaced while it is still the exported default (manifest sha1) or the previous output of this script (`backups/_generated.json`). Hand-edited masters are kept unless `--overwrite`. `--dry-run`, `--team <sheet ...>`, `--restore` (put the backups back) are available.
- A contact sheet of the result is written to `docs/_tmp/baseline_sheet.png`.

## File reference

| File | Meaning |
|---|---|
| `data/uniform_lods/mapping.csv` | final mapping: key, role (master / copy / lod), master, size, score |
| `data/uniform_lods/sorted.csv` | result of the last `uniform_sort.py apply`; wins over everything else (role `none` = unmapped) |
| `data/uniform_lods/manual.csv` | optional hand-typed `lod,master` pairs (the sort tree is easier) |
| `data/uniform_lods/exclude.txt` | keys / 6-char ids that must never be matched |
| `data/uniform_lods/unmatched.csv` | LODs without a hi-res original (probably not dumped yet) |
| `data/uniform_lods/candidates.csv` | raw `match` output with scores |
