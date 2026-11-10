# Jersey (uniform) texture workflow

How to replace jersey / shorts / warm-up / cloth textures and keep their low-res LODs and duplicates in sync.
Background and file formats: [pcsx2_texture_mapping.md](./pcsx2_texture_mapping.md).

For native source identification and possible old-label mistakes, run the
[read-only ISO catalogue/audit](./TextureISOMigrationPlan.md#milestone-1-implemented-inspection-workflow).
It preserves every artist file and reports label suggestions separately. COPY/LOD
labels alone are not verified ISO ownership. Native texture importing/patching is
not implemented yet; the editing and PCSX2 sync workflow below is unchanged.

The [native uniform format investigation](./UniformISOFormat.md) now maps all
834 formerly blocked uniform targets exactly, including their stored mip levels.
It explains the separate game/preview layouts and warmup bundles. This is
read-only source evidence, not a change to `sync` or an ISO texture publisher.

## The naming scheme

Clearly labelled uniform textures live in `texture_workspace/uniforms/<Team>/`.
Unknown/unsorted roles and unlabelled small parts stay in their existing locations.
The filename still determines inheritance; folders are for browsing only:

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

Team folders use NBA / in-game names (Pistons, 76ers, etc.), matching the stable texture labels.
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

After discovering/linking new LODs, an edited MASTER automatically generates missing
replacements even if it has not changed since the previous sync. To rebuild **all
linked COPYs and LODs**, including groups whose MASTER equals the original export:

```powershell
python scripts\texture_workspace.py sync --force-regen --dry-run
python scripts\texture_workspace.py sync --force-regen
```

Forced regeneration bypasses the derived-output cache and always uses the MASTER,
not an edited COPY. Sync now also refreshes the workspace COPY/LOD images for
browsing; MASTER images remain untouched. Generated workspace hashes are tracked
so generated COPYs are not mistaken for manual source edits. It respects
pipeline-managed replacements. Normal sync still reverts derived replacements
when the MASTER is restored to its original content.

## 2. After new texture dumps

1. `python scripts/texture_workspace.py export` - copies the new dumps into the workspace. For new uniform-family textures it then runs `adopt` automatically: hi-res files that look like an existing group become a `COPY__<label>`, LODs become `LOD__<label>`, everything else opens a new `MASTER__Unsorted<n>__...` group (unmatched LODs become `LOD__Unmatched__...`). New 256x256 cloth is compared to the existing cloth pixels.
2. Look at `texture_workspace/uniforms` and fix what the automatic matching got wrong (below). `python scripts/uniform_labels.py check` lists warnings and writes the tracked `data/uniform_lods/labels_snapshot.csv`.
3. `python scripts/texture_workspace.py sync`, then F10.

`adopt` can also be run alone (`uniform_labels.py adopt [--dry-run]`); it is slow because it compares all dumps.

Repeated `export` runs identify existing images by the stable `__ID` suffix,
not their prefix or folder. Artist edits and renamed role files are preserved.
An existing ID missing from the manifest is adopted without exporting a second
image; its original-content hash is recovered from the dump. Duplicate IDs already
present produce warnings (newest file wins); export does not delete artist files.
Different dump keys can legitimately have identical-looking images: keep those
COPY/LOD targets, since each addresses a distinct game texture.

## 3. Organising groups

Do it in the file explorer - rename the `ROLE` / `LABEL` part, keep `__RES__ID`. Or use the helper (names or IDs accepted):

| Command | Effect |
|---|---|
| `uniform_labels.py list [text]` | groups with master id, size, number of COPYs and LODs |
| `uniform_labels.py relabel OLD NEW` | rename a whole group, e.g. `Unsorted3` -> `PistonsJerseyHome2` |
| `uniform_labels.py link FILE MASTERFILE` | make FILE a COPY / LOD of that master's group |
| `uniform_labels.py promote FILE` | FILE becomes MASTER, the old master becomes a COPY |
| `uniform_labels.py restore [--dry-run]` | rename everything back to the committed snapshot |
| `uniform_labels.py organise [--dry-run]` | move clearly team-labelled roles into team folders, updating manifest paths without changing images or labels |

Typical work: identify an `Unsorted<n>` group -> `relabel Unsorted3 NetsJerseyAway`; wrong LOD -> `link` it to the right master.
Run `sync` afterwards.

`link`, `relabel`, `promote`, `adopt` and snapshot restoration retain this team-folder
layout. Scans, generation and sync are recursive. `organise` is safe to repeat;
ambiguous labels such as Legends/Unknown/Unsorted are not assigned to a team.

Warnings you can get: *several MASTERs with label X* (demote one to COPY or relabel it), *no MASTER* (promote one), *COPY size differs*,
*LOD not smaller*, *RES mismatch*, *duplicate ID*.

## 4. Generate baseline team jerseys (all 18 ProA teams)

`python scripts/create_baseline_jersey.py` colourises `texture_workspace/uniforms/templates/{jersey,short,warmup,cloth_top,cloth_shorts}_tmpl.png`
and writes the result over **every MASTER** whose label is `<Team><Item><Variant>`, then
`python scripts/texture_workspace.py sync` rebuilds COPYs and LODs, then F10 in PCSX2.

- Colours: `team.colorjersey1` / `team.colorjersey2` (hex) in `texture_workspace/team_palettes/<slot>/colours.json`. Home (and numbered variants) = white body, primary trim and short stripes. Away = primary body, secondary trim/stripes. Alt variants are skipped. Teams without a MASTER of an item print "no MASTER found - skipped". `colorui1` / `colorui2` are separate roster/UI controls and do not colour jersey cloth or lettering.
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
workspace and opt-in season ISO stage are now **implemented**. All 237 sources
were verified in a real all-slot diagnostic build: intended RGB changes, unchanged
alpha, descriptors and indices/mips, and a verified full output hash. Broader
in-emulator visual acceptance beyond the Pacers control case remains to be done.
Do not feed CPU-read source atlases through
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

Implemented layout, separate from ordinary dump/replacement sync:

```text
texture_workspace/team_palettes/
  manifest.json
  _originals/
    020/home/numbers.palette.png
    ...
  020/
    colours.json
    home/
      numbers.palette.png
      names.palette.png
      numbers.preview.png
      names.preview.png
    away/
      ...
    alt/
      ...
```

All 30 slot folders exist; `alt/` exists for the 19 mapped alternate uniforms.
There are 30 combined team colour-control files, 158 legacy editable palettes, 158 original
backups and 158 generated previews.

```powershell
# Export from the untouched original, not the earlier patched "- Kopie.iso".
python scripts\lettering_workspace.py export --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso"
# Edit colours.json, then rerun export to refresh previews.
python scripts\lettering_workspace.py export --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso"
# Read-only preflight, including destination and compressed-palette fit.
python scripts\lettering_workspace.py check --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "C:\Tools\isos\ESPN NBA 2K5 (Europe) - ProA.iso"
# Publish a new ISO; an existing output is refused.
python scripts\lettering_workspace.py build --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "C:\Tools\isos\ESPN NBA 2K5 (Europe) - ProA.iso"
# Explicitly discard palette edits for selected slots, including all their variants.
python scripts\lettering_workspace.py reset --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --slot 20
```

These standalone tools retain `texture_workspace/team_palettes` as their default;
`--workspace texture_workspace_ISO\team_palettes` selects the copied controls used by
the [native logo/season workflow](./NativeLogoWorkflow.md). That workflow defaults to
the selected native workspace's `team_palettes` subfolder. Keep alternate workspaces
outside ordinary replacement folders.
`--slots PATH` selects another assignment CSV. A changed assignment/source manifest
is rejected: export a new workspace and migrate the desired RGB swatches explicitly.

#### Simple colour controls (recommended)

Edit `uniforms.<variant>` in the team's `colours.json`, not individual swatch pixels.
The complete team/court/lettering schema is in the dedicated
[team palettes README](../texture_workspace/team_palettes/README.md).
For monochrome white numbers and names, use this **uniform-variant section**:

```json
{
  "numbers": {
    "mode": "monochrome",
    "fill": "#FFFFFF",
    "outline1": "#000000",
    "outline2": "#000000"
  },
  "names": {
    "mode": "monochrome",
    "fill": "#FFFFFF",
    "outline1": "#000000",
    "outline2": "#000000"
  }
}
```

* `monochrome`: only `fill` affects output. Every palette entry with nonzero source
  alpha gets that RGB, including entries used only by smaller mip levels. The
  original alpha supplies antialiasing. All existing foreground regions merge into
  one colour; this does not remove outline pixels or change the glyph silhouette.
* `outlined`: set `fill`, `outline1` and `outline2`. One generic algorithm infers
  reference colours from the original atlas/palette and fits convex blend weights
  for its entries. New colours replace those references while retaining original
  RGB shading/quantisation residuals. There are no hand-tuned uniform profiles.
  Weights always come from the pristine source, never from previously recoloured
  palettes, so changing colours again does not invalidate or accumulate the fit.
  The two outline controls are approximate colour roles, not a guaranteed
  inner/outer-border assignment for every font. Inspect the generated previews.
* `palette`: use the legacy `*.palette.png` inputs instead. This is the default
  on export, preserving original appearance and existing artist edits. Missing team
  documents require export; migrate older per-uniform JSONs explicitly.

Source number rasters are not identical: the inventory includes two widths and
59 distinct full-size silhouettes across 79 uniforms. A universal palette-index
gradient would therefore misassign colours. The generic algorithm is shared, but
looks up each original source's relationships automatically.

All three RGB fields must contain six hex digits, optionally prefixed by `#`.
Numbers and names have independent modes and colours. In colour-control modes,
legacy palette PNGs are preserved but are not the colour input. `export` refreshes
previews from the chosen mode; `check` and `build` derive the same palettes in memory
without overwriting workspace files. Mode/field typos and malformed colours fail.
Outlined approximation diagnostics and RGB range-clipping counts are reported by
preflight/build; clipping is a bounded approximation, not an archive-size workaround.
Unchanged outlined reference colours reproduce the original palette exactly.
Setting all three outlined colours equal produces the same result as monochrome.

Validation covered black, white and green monochrome for all 237 sources (711
source/preset combinations), with all 79 compressed preview spans fitting. A real
colour-controls ISO build verified every source, and the generic white-fill/black-
outlines preset also fitted all 79 preview spans. These are data/preview checks;
broader in-emulator acceptance still remains.

* Each legacy editable `*.palette.png` is a **16 x 16 RGB swatch image**, one pixel per
  logical CLUT entry (row-major). Edit at high zoom in an image editor. This avoids
  accidental atlas re-indexing or palette quantisation. Enlarged atlas previews are
  generated feedback, not import sources. The tool handles physical PS2 CLUT swizzling.
* Folders are keyed by stable NBA slot (000-029), not by the current ProA sheet.
  Assigned ProA sheets are separate manifest metadata; unassigned slots remain editable.
* The manifest keeps original PS2 alpha bytes, indices/mips hashes, source ISO hash,
  chunk/bundle identities, slot, ProA sheet and uniform variant. Import changes RGB
  only; alpha, geometry, glyph metrics and index buffers remain immutable.
* One number palette, generated from controls or imported in palette mode, updates
  both court and team-select sources; names have an
  independent palette. Artists can adjust fill, outlines and
  antialiasing ramps together. The diagnostic blue-to-green threshold is **not** the
  production recolouring algorithm.
* Export creates missing editable palettes/backups, validates existing ones and
  adds missing colour-control files without overwriting settings or palettes.
  It refreshes generated previews using current edits. `check` and `build` do not refresh
  previews or change the workspace. Backups and metadata are validated; RGB PNG mode
  and 16 x 16 dimensions are required (RGBA, indexed PNGs and other formats are rejected).
  `reset` restores selected editable palettes, uniform controls and previews from
  the verified source, returning those controls to palette mode; team/court colours stay intact.
  Keep extracted copyrighted atlas previews/workspace files out of Git; compact
  the 30 combined JSON controls and dedicated README are tracked separately.
* This folder is excluded from the existing `texture_workspace.py` export,
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
2. Export editable colour controls and legacy palettes for all 30 slots, keyed by NBA slot/variant with
   the current ProA sheet recorded separately where assigned. Unassigned slots
   remain editable and must not require a ProA sheet or guessed club colours.
   The exporter starts in palette mode with original appearance, not guessed club
   colours. Reference colours are automatically inferred for the generic outlined
   mode; nothing is seeded from `colorjersey1/2`.
   `colorui1/2` remain exclusively roster controls.
3. `update_season.py` is ISO-first, requiring `--iso-source` / `--iso-out` and optional
   `--team-palettes` (`--lettering-workspace` remains an alias). It runs read-only roster/lettering/court preflight before scraping,
   roster/card writes or replacement generation, then builds the ISO after the last
   logo-generation step. `season_iso.py` embeds the default roster alongside all visual/year/skin patches
   in one publication. Explicit `--card-only` / `--build-only` modes skip ISO publication.
   See [season commands](SeasonUpdateWorkflow.md#iso-first-roster-deployment).
4. Build a new output from a verified pristine source, never cumulatively edit an
   unknown image. Validate every original chunk/palette, apply equal-size patches,
   verify the whole expected output hash and unchanged bytes elsewhere, then publish
   the output atomically. Save a patch/restore manifest. Refuse a mounted output ISO.
   Compressed preview palettes are rebuilt inside the original stored span with
   decoder scratch limits enforced. If an edit does not fit, preflight names its
   slot/variant/asset and fails before ISO publication; no sources are silently
   skipped and no archive members are resized. Not every possible RGB palette fits:
   a full channel-rotation test fitted 75 of 79 original preview chunks; four needed
   1-3 extra bytes. Adjust the palette or leave that edit unapplied.
   Output must be outside the lettering workspace. The adjacent
   `<ISO filename>.lettering.json` records patch fingerprints, original byte spans,
   assignments and source/output hashes. Restore by booting the untouched source or
   resetting selected workspace palettes and rebuilding to another new output.
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
