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
