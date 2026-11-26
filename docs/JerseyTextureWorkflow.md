# Jersey (uniform) texture workflow

Edit native masters in `texture_workspace_ISO\uniforms`, retaining their eight-digit IDs.
Game, preview and warmup textures are independent; edit each desired master. Run
`python build.py` and boot the resulting ISO afresh. See
[NativeUniformWorkflow.md](./NativeUniformWorkflow.md) for native IDs and mip handling.

## Optional baseline generation

`python scripts\create_baseline_jersey.py --dry-run` previews generation for
identified home/away native jerseys, shorts and warmups. Remove `--dry-run` to
write unedited masters. Manually edited masters are never overwritten, including
when restoring backups. `--team` restricts the selection; `--restore` restores
only files still matching this generator's last output. Templates are in
`texture_templates`; `--fabric` exports optional editing layers there.

The sections below preserve historical lettering-format investigations; old
standalone command examples are not the current build workflow.

## 5. Shared lettering and team-select preview plan

**Status:** Pacers home shared numbers/names and the separate team-select number
source are verified after a fresh boot. The read-only inventory now covers all 30
NBA slots: 60 home/away uniforms plus 19 alternates, 237 lettering sources.
Cosmetic palette choices are not part of these diagnostic tests. The editable
workspace and opt-in season ISO stage are now **implemented**. All 237 sources
were verified in a real all-slot diagnostic build: intended RGB changes, unchanged
alpha, descriptors and indices/mips, and a verified full output hash. Broader
in-emulator visual acceptance beyond the Pacers control case remains to be done.
The native-workspace preview only considers sources recorded in its native manifests;
these CPU-read source atlases are not previewed or modified by it.
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

Implemented layout, separate from native texture-master previews:

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
* This folder is separate from the native image masters and targets the ISO.

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
3. `python build.py` embeds the default roster alongside all native visual/year/skin
   patches in one ISO. Scraping is a separate `python scrape.py` step.
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
