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

- Colours: `colorjersey1` / `colorjersey2` (hex) in `data/proa_teams.csv`. Home (and numbered variants) = white body, primary trim and short stripes. Away = primary body, secondary trim/stripes. Alt variants are skipped. Teams without a MASTER of an item print "no MASTER found - skipped". `colorui1` / `colorui2` are separate roster/UI controls and do not colour jersey cloth or lettering.
- Cloth structure (folds, perforations) is kept: every template region is divided by its median brightness and that shade map is applied on the target colour (`HIGHLIGHT` in the script tames the bright side).
- **Fabric layers for manual editing:** `python scripts/create_baseline_jersey.py --fabric` exports that shade map to `texture_workspace/uniforms/templates/fabric/` for jersey, shorts, warm-up and the 256x256 cloth (`<kind>_fabric_overlay.png`, `<kind>_fabric_shadow_light.png`, `warmup_sleeves_fabric_*`, `warmup_legs_fabric_*`). Existing files are kept (`--fabric --overwrite` regenerates).
  - `*_overlay.png`: grey, 128 = neutral. Blend mode Overlay / Soft Light / Linear Light.
  - `*_shadow_light.png`: black darkens, white lightens, alpha = strength; Normal blend.
- Logos: ProA patch (`data/proa_logo.png`) on the player's left breast and club logo (`nba2k_editor/assets/<38+index>.png`) on the right breast of the jerseys. Warm-up torsos carry the club logo on the chest. Shorts are plain. Positions are constants at the top of the script.
- Cloth (`WUsleeves`, `WUlegs`): plain `colorjersey1` from the logo-less `cloth_top_tmpl.png` / `cloth_shorts_tmpl.png`, folds kept.
- Output PNGs have no alpha channel, so `sync` keeps the game's original per-pixel alpha.
- Safety: the original is copied once to `texture_workspace/uniforms/backups/<ID>.png`; a MASTER is only replaced while it is still the exported default (manifest sha1) or the previous output of this script (`backups/_generated.json`). Hand-edited masters are kept unless `--overwrite`. `--dry-run`, `--team <sheet ...>`, `--restore` (put the backups back) are available.
- A contact sheet of the result is written to `docs/_tmp/baseline_sheet.png`.

## 5. Shared lettering and team-select preview plan

**Status:** Pacers home shared numbers/names and the separate team-select number
source are verified after a fresh boot. The read-only inventory now covers all 30
NBA slots: 60 home/away uniforms plus 19 alternates, 237 lettering sources.
Cosmetic palette choices are not part of these diagnostic tests. The editable
workspace and season pipeline described here are still **planned**,
not commands currently implemented. Do not feed CPU-read source atlases through
ordinary PCSX2 replacement sync: that route has not changed the generated output.
Experimental commands and measured offsets are in [the payload/ISO findings](roster_payload_format.md).

### A. Identify the preview's actual input before choosing a solution

**Resolved for the control case:** the visible preview number is a separate generated
128 x 64 buffer, not baked jersey artwork. A GS frame dump matches its palette uploads
to `jerseynum00` / `jerseynum01`; a reversible RAM probe turns the visible left/right
numbers magenta/green. Pacers home preview reads the compressed `numbers` resource in
`seluh020.iff` (archive entry 178), whereas court lettering reads `uh020.iff` (entry
2103). Patching both produces green home preview/court numbers after a fresh boot.
Details and diagnostic commands: [payload/ISO findings](roster_payload_format.md#team-select-preview-source-and-all-30-slot-inventory-2026-11-07).

The following checks remain the rollout procedure for other presentation surfaces:

1. Capture a fresh team-select frame and RAM snapshot. Resolve the visible number's
   draw texture/CLUT with a PCSX2 GS frame dump, then match it to the preview buffers
   or the full jersey texture. Do not infer this from filename labels alone.
2. Compare snapshots while changing team, home/away/alternate uniform and preview
   player/number where possible. Trace the actual read source and generation timing.
   A controlled patch to the **rendered preview buffer** can help, but account for
   already-uploaded GS texture caching before treating a negative RAM test as proof.
3. If separately generated, patch its shared source palette(s), including duplicated
   bundle copies, then verify both preview and court output after a fresh boot.
4. If genuinely baked, map the static preview texture per uniform and recolour only
   its number region, preserving the jersey artwork. A fixed per-uniform asset can
   be maintained; never introduce a per-player replacement list.
5. Test both sides, multiple preview numbers and uniform variants. Acceptance:
   preview and in-game fills/outlines agree, and a new roster player/number needs no
   new manual texture edit. The preview is not assumed to be the game's only static
   lettering surface.

### B. Dedicated editable palette workspace

Proposed layout, separate from ordinary dump/replacement sync:

```text
texture_workspace/lettering/
  manifest.json
  020/
    home/
      numbers.palette.png
      names.palette.png
      numbers.preview.png
      names.preview.png
    away/
      ...
    alt_<variant>/
      ...
```

* Each editable `*.palette.png` is a **16 x 16 RGB swatch image**, one pixel per
  logical CLUT entry (row-major). Edit at high zoom in an image editor. This avoids
  accidental atlas re-indexing or palette quantisation. Enlarged atlas previews are
  generated feedback, not import sources. The tool handles physical PS2 CLUT swizzling.
* Folders are keyed by stable NBA slot (000-029), not by the current ProA sheet.
  Assigned ProA sheets are separate manifest metadata; unassigned slots remain editable.
* The manifest keeps original PS2 alpha bytes, indices/mips hashes, source ISO hash,
  chunk/bundle identities, slot, ProA sheet and uniform variant. Import changes RGB
  only; alpha, geometry, glyph metrics and index buffers remain immutable.
* Numbers and names have independent palettes. Artists can adjust fill, outlines and
  antialiasing ramps together. The diagnostic blue-to-green threshold is **not** the
  production recolouring algorithm.
* Export creates missing files only. Preserve existing edits, keep backups for an
  explicit reset, reject wrong dimensions/modes or an unexpected team/slot mapping.
  Keep extracted copyrighted atlas previews/workspace files out of Git; compact
  user palette overrides and mapping metadata can later be tracked separately.
* Explicitly exclude this folder from the existing `texture_workspace.py` export,
  sync and uniform-label/LOD scans. It targets the ISO, not PCSX2's replacements.

### C. Inventory and pipeline integration

1. Inventory `HITX names/numbers` chunks and compressed preview `TXTR numbers`
   across the archive. Map every required
   slot/variant through known RAM owners and decoded previews; do not assume matching
   palette hashes imply identical ownership. Include all confirmed preview/game copies.
   Cover **all 30 NBA slots (0-29)**, including donor teams, not just the current
   18 ProA teams. NBA slot/variant is the stable asset identity; current ProA
   assignments from `data/team_slots.csv` are a separate layer, not CSV row indices.
   **Implemented inventory:** `python scripts/inventory_lettering_iso.py PRISTINE.iso --out data/texture_map/lettering_sources.csv`.
   Home/away and `ux`/`selux` alternate pairs are mapped by the verified filename hash;
   all 79 pairs have identical game/preview number palettes. Number atlases may be
   1024 x 64 or 512 x 64 (17 uniforms use the latter); names are 1024 x 32.
2. Export editable palettes once for all 30 slots, keyed by NBA slot/variant with
   the current ProA sheet recorded separately where assigned. Unassigned slots
   remain editable and must not require a ProA sheet or guessed club colours.
   `colorjersey1/2` may seed a **new** club's initial choices after fill/outline ramps
   are mapped, but must never overwrite hand-edited palettes on a season rebuild.
   `colorui1/2` remain exclusively roster controls.
3. Add an explicit opt-in ISO stage to `update_season.py` after roster/texture
   generation (proposed options: `--iso-source`, `--iso-out`, `--lettering-workspace`).
   Normal roster-only runs must neither require an ISO nor write one.
4. Build a new output from a verified pristine source, never cumulatively edit an
   unknown image. Validate every original chunk/palette, apply equal-size patches,
   verify the whole expected output hash and unchanged bytes elsewhere, then publish
   the output atomically. Save a patch/restore manifest. Refuse a mounted output ISO.
   Compressed preview assets need a separately verified codec/repack path if their
   palettes cannot be patched in place; do not silently resize archive members.
5. Gate rollout with fresh-boot preview + gameplay checks for home/away/alternate,
   long/short/new player names, one/two-digit numbers, outlines, warm-ups and loading.
   F10 only reloads PCSX2 replacement textures: ISO changes require a fresh boot.

Once a slot/variant is configured, adding or changing players uses the same shared
alphabet/digit sources automatically. Palette editing is per team/uniform, not per
player or season.

## File reference

| File | Meaning |
|---|---|
| `scripts/uniform_labels.py` | name grammar, group analysis, `adopt` / `link` / `promote` / `relabel` / `check` / `restore` |
| `scripts/uniform_lods.py` | library: image matching used by `adopt`, `workspace_state` |
| `data/uniform_lods/labels_snapshot.csv` | tracked copy of all role names (token, key, role, label, res) - rewritten by `check` / `export` / `adopt`; `restore` uses it |
