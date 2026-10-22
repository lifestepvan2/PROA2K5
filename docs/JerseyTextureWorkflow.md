# Jersey (uniform) texture workflow

How to replace jersey / shorts / warm-up / cloth textures and keep their low-res LODs and duplicates in sync.
Background and file formats: [pcsx2_texture_mapping.md](./pcsx2_texture_mapping.md).

## The naming scheme

All uniform textures live **flat** in `texture_workspace/uniforms/` and the file name says everything:

```
ROLE__LABEL__RES__ID.png
MASTER__PistonsShortsHome__512x256__7431831b.png
COPY__PistonsShortsHome__512x256__592667fe.png
LOD__PistonsShortsHome__32x16__d726dae8.png
```

| Part | Meaning |
|---|---|
| `ROLE` | `MASTER` = the file you edit. `COPY` = same size, generated from the master. `LOD` = smaller, box-downscaled from the master. |
| `LABEL` | groups one MASTER with its COPYs and LODs (characters `A-Za-z0-9-`). The file system sorts a group together. |
| `RES` | informational (a mismatch with the real size only warns). |
| `ID` | 8 hex characters = the dump token. **This alone decides which in-game texture is replaced. Never edit it.** |

Inheritance is nothing but "same LABEL": every COPY / LOD is regenerated from the MASTER with its label by
`texture_workspace.py sync`. A group needs exactly one MASTER; none or several give a warning and the group is skipped.
A COPY must have the MASTER's size, a LOD must be smaller.

Generator labels: `<Team><Item><Variant>` - Team = NBA / in-game name (Pistons, 76ers, ... see `data/team_slots.csv`),
Item = `Jersey | Shorts | WUtorso | WUsleeves | WUlegs`, Variant = `Home | Away | Alt` (optionally followed by a counter)
or a plain number for not-yet-identified variants. `create_baseline_jersey.py` reads these labels. Other labels
(`Legends1`, `Unknown3`, `Unsorted2`, ...) work for the inheritance but are ignored by the generator.

Not part of the scheme (stay in their sub folders, unchanged): shoes, the 64x64 parts and everything else in `uniforms/64x64`,
`128x64`, ... that has no role name. Hand-edit those directly.

## 1. Replace a texture

1. Edit the `MASTER__*` file (keep the file name and size).
2. `python scripts/texture_workspace.py sync` - writes the master to the live replacement folder, copies it to the COPYs and downscales it for the LODs. Hand edits of COPY / LOD files are ignored (they are generated from the MASTER).
3. Press **F10** in PCSX2.

If you had edited a COPY and not the MASTER, `sync` notices (it prints a note) and uses the edited copy as the source.

## 2. After new texture dumps

1. `python scripts/texture_workspace.py export` - copies the new dumps into the workspace. For new uniform-family textures it then runs `adopt` automatically: hi-res files that look like an existing group become a `COPY__<label>`, LODs become `LOD__<label>`, everything else opens a new `MASTER__Unsorted<n>__...` group (unmatched LODs become `LOD__Unmatched__...`). New 256x256 cloth is compared to the existing cloth pixels.
2. Look at `texture_workspace/uniforms` and fix what the automatic matching got wrong (below). `python scripts/uniform_labels.py check` lists warnings and writes the tracked `data/uniform_lods/labels_snapshot.csv`.
3. `python scripts/texture_workspace.py sync`, then F10.

`adopt` can also be run alone (`uniform_labels.py adopt [--dry-run]`); it is slow because it compares all dumps.

## 3. Organising groups

Do it in the file explorer - rename the `ROLE` / `LABEL` part, keep `__RES__ID`. Or use the helper (names or IDs accepted):

| Command | Effect |
|---|---|
| `uniform_labels.py list [text]` | groups with master id, size, number of COPYs and LODs |
| `uniform_labels.py relabel OLD NEW` | rename a whole group, e.g. `Unsorted3` -> `PistonsJerseyHome2` |
| `uniform_labels.py link FILE MASTERFILE` | make FILE a COPY / LOD of that master's group |
| `uniform_labels.py promote FILE` | FILE becomes MASTER, the old master becomes a COPY |
| `uniform_labels.py restore [--dry-run]` | rename everything back to the committed snapshot |

Typical work: identify an `Unsorted<n>` group -> `relabel Unsorted3 NetsJerseyAway`; wrong LOD -> `link` it to the right master.
Run `sync` afterwards.

Warnings you can get: *several MASTERs with label X* (demote one to COPY or relabel it), *no MASTER* (promote one), *COPY size differs*,
*LOD not smaller*, *RES mismatch*, *duplicate ID*.

## 4. Generate baseline team jerseys (all 18 ProA teams)

`python scripts/create_baseline_jersey.py` colourises `texture_workspace/uniforms/templates/{jersey,short,warmup,cloth_top,cloth_shorts}_tmpl.png`
and writes the result over **every MASTER** whose label is `<Team><Item><Variant>`, then
`python scripts/texture_workspace.py sync` rebuilds COPYs and LODs, then F10 in PCSX2.

- Colours: `color1` / `color2` (hex) in `data/proa_teams.csv`. Home (and numbered variants) = white body, `color1` trim and short stripes. Away = `color1` body, `color2` trim/stripes. Alt variants are skipped. Teams without a MASTER of an item print "no MASTER found - skipped".
- Cloth structure (folds, perforations) is kept: every template region is divided by its median brightness and that shade map is applied on the target colour (`HIGHLIGHT` in the script tames the bright side).
- **Fabric layers for manual editing:** `python scripts/create_baseline_jersey.py --fabric` exports that shade map to `texture_workspace/uniforms/templates/fabric/` for jersey, shorts, warm-up and the 256x256 cloth (`<kind>_fabric_overlay.png`, `<kind>_fabric_shadow_light.png`, `warmup_sleeves_fabric_*`, `warmup_legs_fabric_*`). Existing files are kept (`--fabric --overwrite` regenerates).
  - `*_overlay.png`: grey, 128 = neutral. Blend mode Overlay / Soft Light / Linear Light.
  - `*_shadow_light.png`: black darkens, white lightens, alpha = strength; Normal blend.
- Logos: ProA patch (`data/proa_logo.png`) on the player's left breast and club logo (`nba2k_editor/assets/<38+index>.png`) on the right breast of the jerseys. Warm-up torsos carry the club logo on the chest. Shorts are plain. Positions are constants at the top of the script.
- Cloth (`WUsleeves`, `WUlegs`): plain `color1` from the logo-less `cloth_top_tmpl.png` / `cloth_shorts_tmpl.png`, folds kept.
- Output PNGs have no alpha channel, so `sync` keeps the game's original per-pixel alpha.
- Safety: the original is copied once to `texture_workspace/uniforms/backups/<ID>.png`; a MASTER is only replaced while it is still the exported default (manifest sha1) or the previous output of this script (`backups/_generated.json`). Hand-edited masters are kept unless `--overwrite`. `--dry-run`, `--team <sheet ...>`, `--restore` (put the backups back) are available.
- A contact sheet of the result is written to `docs/_tmp/baseline_sheet.png`.

## File reference

| File | Meaning |
|---|---|
| `scripts/uniform_labels.py` | name grammar, group analysis, `adopt` / `link` / `promote` / `relabel` / `check` / `restore` |
| `scripts/uniform_lods.py` | library: image matching used by `adopt`, `workspace_state` |
| `data/uniform_lods/labels_snapshot.csv` | tracked copy of all role names (token, key, role, label, res) - rewritten by `check` / `export` / `adopt`; `restore` uses it |
