# Native texture workspace

The native authoring workspace is `texture_workspace_ISO`, not the original
PCSX2 workspace. Logos, uniforms and remaining archive textures share one
encoder and original-coordinate resource composer before archive repacking.

## Export and edit

Export logos and uniforms first, then all remaining textures:

```powershell
python scripts\remaining_texture_workspace.py export --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso"
```

`--scope arenas` limits initial export to arenas; omit it for the complete
inventory. A complete workspace cannot subsequently be narrowed to arenas.
The source ISO and catalogue identity are verified. Initial migration needs
the pristine dumps and original workspace; compilation does not.

Navigation:

- `arenas/slot_NNN_Team/`: home-team props, sponsors/signage, court and
  stands/crowd. Ownership uses `court_sources.csv`, **not** arena asset numbers.
  Night variants share their home-team folder; special arenas stay separate.
- `players/pid_NNNN/`: model-local home/away/alternate textures.
- `players/portraits/`: native player-card and lineup portrait sources.
- `interface/`, `interface/fonts/`, `broadcast/`, `cinematics/`, `objects/`.
- `jumbotron_movies/unresolved/hash_XXXXXXXX/`: flattened movie-frame textures
  grouped by native archive hash. Frame indices remain in the PNG filenames.
  Empty `jumbotron_movies/slot_NNN/` folders (slots 000-029) are available for
  manual team sorting after ownership is confirmed.
- `unresolved/`: verified physical textures whose archive filenames remain
  unknown. Hash labels describe missing names, not an unsupported codec.

Asset and scene subfolders preserve disc context. Filenames retain
`label__RES__ID.png`; the stable native ID binds artwork to its original
descriptor. Rename or move masters without changing IDs. Re-export preserves
existing native artwork and renamed paths.

Only base masters are exposed. Native mip levels are regenerated at encoding;
physical aliases reuse one master, while separate palettes remain separately
editable. Shared-index crowd variants are quantized jointly.
Font masters edit atlas artwork only: glyph metrics and layout are preserved.

### Stitching arena strips for editing

```powershell
python scripts\stitch_textures.py
# Edit the generated sts.png files, then:
python scripts\split_texture.py
```

Defaults collect each `arenas\slot_*\props\sNNN\sts_*\*.png` set and arrange
tiles left-to-right by numeric `sts_` index. Width is the number of existing
tiles times 128: six tiles produce **768x128**, while smaller sets produce
shorter strips. Arena asset numbers need not equal team slot numbers.

Editable strips and their mapping sidecars are saved under
`texture_workspace_ISO\_stitched\arenas\slot_*\props\sNNN\sts.png` and `sts.json`.
This derived folder is ignored by native texture compilation. Stitching
**overwrites** these strips from the current masters; split your edits before
stitching again. Keep the JSON beside the PNG and do not resize the strip.
Splitting overwrites only the original tiles, preserving their native filenames
and IDs. RGBA edits preserve edited alpha; RGB exports retain each source tile's
existing alpha. All selected groups are validated before any tile is overwritten.
Run the normal combined ISO build after splitting.

The same tools support other horizontal tiled textures and workspace roots:

```powershell
python scripts\stitch_textures.py --workspace "<workspace>" --groups "objects/banner_*" --tiles "*.png" --index-regex "tile_(\d+)" --tile-size 64 32 --name banner
python scripts\split_texture.py --workspace "<workspace>" --groups "objects/banner_*" --name banner
```

`--groups` selects workspace-relative directories; `--tiles` selects files
relative to each group. The first regex capture is the numeric tile index.
Indices must be unique but need not be contiguous. `--name` separates multiple
strip use cases within a group. Split reads tile dimensions and original paths
from the generated sidecar; it does not need the stitch-only options.

### Jumbotron video editing

Create one animated GIF for each team slot's jumbotron frame sequence:

```powershell
python scripts\stitch_video.py
```

GIFs and mapping sidecars are written under
`texture_workspace_ISO\_videos\jumbotron_movies\slot_NNN\hash_XXXXXXXX\`.
Import the `jumbotron_movie.gif` files into DaVinci Resolve Studio. Keep the
timeline at **64x64, 50 fps, 180 frames (3.6 seconds)** and export an animated
GIF. Replace the corresponding GIF with the edited export, leaving its JSON
sidecar in place. GIF timing has 10 ms granularity; a constant 20 ms delay
represents exactly 50 fps. This is a small cadence mismatch from the game's
60 fps playback, which is acceptable for this workflow. Then write the decoded
frames back to their original native PNGs:

```powershell
python scripts\split_video.py
```

Both tools accept `--groups "jumbotron_movies/slot_021/hash_*"` to work on a
subset. Stitch validates indices 000-179 and preserves existing GIFs by
default; pass `--overwrite` to regenerate them from the current PNGs. Split
rejects changed frame sets or GIFs that are not 64x64. If a GIF has fewer than
180 frames, its last frame is repeated to fill the sequence; frames after 180
are ignored. It stages every selected group before replacing any source PNG.
Existing per-frame alpha is preserved. GIF supports at most 256 colors per
frame, so frames with more colors may be quantized. The `_videos` folder is
derived and excluded from native master discovery.

## Manual artwork migration and review

Manual edits are detected against pristine and tracked automatically generated
files, then mapped using exact original base/mip pixels, not old labels.
The original workspace is not modified.

Conflicting edits or unmapped sources block publication and produce
`_iso_texture_review.json`. PNGs remain under `_native_export_pending` until
the complete export succeeds. Do not edit that staging directory.

Persist reviewed choices in `_iso_migration.json`:

```json
{
  "schema": 1,
  "source_sha256": "4cdad2339dbe2828b440ca222f869f234b15c0321c8dcdeac016a30b10678fb7",
  "choices": {
    "e5079817": "a9c978dc34574a43-e648e8dcb77fd448-00001993"
  }
}
```

Keys are native IDs; values are approved legacy keys, or `null` to retain
stock artwork. Choices must match pristine source evidence. All candidate
provenance and approved choices are retained in `_iso_textures.json`, including
superseded independent mip edits. No resolution is inferred from filenames.

The pregame ESPN/NBA animated letter atlas lives inside `loading.iff`'s
**MRKH markscene**, not its top-level HiSn scene. MRKH/MRKS and CNSR resources
contain a tagged pointer to a nested scene with the same descriptor/material
tables as SCNE. These containers are included, including the manually edited
SportEurope.TV/PROA loading atlas.

## Compile and validate

The season pipeline automatically discovers `_iso_textures.json`. Existing
`update_season.py` ISO mode includes these masters without another generator:

```powershell
python scripts\texture_iso_workspace.py check --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --repack-archive
```

Use the combined season check/build for roster, skin, lettering, court controls
and artwork together. `--repack-archive` pools compressed-resource savings
within the unchanged archive extents; it does not enlarge PS2 RAM or VRAM.
Native edits and skin recipes targeting the same player texture fail explicitly
rather than silently overriding each other. Court and lettering controls compose
at decoded-resource coordinates, with conflicting byte writes rejected.

Supported images include linear indexed 4/8-bit, true-color PSMCT32,
GS-upload indexed 4/8-bit, font atlases and shared-index palette variants.
Unchanged masters produce no patches. Encoded resources are decoded again and
compressed resources undergo in-place safety validation.

Offline checks do not certify rendered output. In particular, non-flat packed
PSMT4 spatial addressing still needs a consolidated in-game visual review.
Movies/audio and non-texture geometry are preserved, not converted to PNGs.
Automatic season portrait/team-icon and legacy reserve-skin **generation**
still uses its existing PCSX2 path; their native masters are editable here,
but exporting masters does not port those automatic generators.
