# Native logo ISO workflow (POC)

Use `texture_workspace_ISO`, never the legacy `texture_workspace`, for this
workflow. The original workspace and PCSX2 replacements remain available for
comparison; uniforms, portraits and other copied image categories have **not**
been migrated by this POC.

## Export and edit

The read-only native catalogue must exist first:

```powershell
python scripts\texture_catalogue.py --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --out cache\texture_iso\catalogue.sqlite
python scripts\texture_iso_workspace.py export --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso"
```

The catalogue output must be new; reuse an existing verified catalogue rather
than overwriting it. Export discovers native sources, not replacement hashes:

- `team_logos`: standalone logo textures in native team bundles and the common
  logo collection, including previously untouched sources.
- `centerlogo`: textures referenced by the native floor scene's `centerlogo`
  mesh. This includes some wood, wordmarks and NBA graphics, not just badges.
- `_iso_logos.json`: native identity, ownership, descriptor/mip information,
  source fingerprints and seeding provenance. Do not edit this generated file.
- `_encoded`: decoded encoded previews and verified compression caches, not
  editable masters. Underscore-prefixed folders are excluded from scanning.

There is **one master per native texture descriptor**, named
`native_label__WIDTHxHEIGHT__ID.png`. Labels include native asset/resource names;
they are useful context, not guaranteed descriptions of the picture. Keep the
eight-character ID unchanged. Labels and folders can be changed freely; there
is no special behavior attached to `centerlogo` or any other folder.

Keep masters at their native resolution where practical. RGBA masters use normal
editor alpha (0-255). RGB-only edits preserve the original texture's alpha.
Build resizes to the native base and generates every stored mip, quantizing all
levels together against one native palette. Do not author separate mip files.

Export currently discovers **987 masters: 590 team logos and 397 centerlogo
textures**, with 343 confirmed-current sources editable and no unsupported
inventory exceptions. Historical/unconfirmed owners remain stock references;
editing them fails explicitly. No content-alias fan-out is applied.
Native numbered team IDs are mapped through `teams_unknown.csv`, not treated
as roster slots; arena ownership uses `court_sources.csv`.

Initial export seeds 110 team-logo and 14 centerlogo masters from current club
artwork. Native-pixel-keyed recipes preserve the existing split-piece composition.
This is **one-time population**, not ongoing auto-splitting: subsequent exports
preserve existing masters and builds read each master independently. Additional
centerlogo textures without a proven composition recipe retain stock pixels and
are listed in `unseeded_centerlogo`/`stock_centerlogo` for review. In particular,
the exporter does not blindly fit a badge into wood or trophy graphics.
The copied legacy team-logo folder is preserved under `_legacy_pcsx2` on first
export. Other copied categories remain untouched.

## Validate and publish

```powershell
# JSON report and decoded previews; nonzero exit if any resource cannot fit:
python scripts\texture_iso_workspace.py check --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso"
# Logo-only proof of concept; refuses publication if any requested edit fails:
python scripts\texture_iso_workspace.py build --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "C:\Tools\isos\ProA-logos.iso"
```

Checks do not change artist masters or the source ISO, but refresh `_encoded`.
Inspect these previews, which show native quantization and normalized alpha.
The report includes palette size, visible RGB RMSE, maximum native-alpha error,
resource budgets and decoded fingerprints. Fixed resource spans and original
decoder scratch limits are enforced; overflow never silently omits a logo.

The initial combined season preflight has 124 changed textures, 109 fitting
resources and **12 capacity failures**. Thus the seeded defaults are not yet a
publishable complete build. Lower-color profiles require explicit quality review;
some resources still exceed capacity even at 16 colors. No reduced profile is
automatically selected. These are historical **fixed-span** results; the
experimental pooled allocator below supersedes those limits when selected.

The batched review subsequently approved 64 colors for the Merlins logos and
32 for the Miners small logos, Lions logos and both Stars center-court pieces.
These ten per-master caps are saved in the workspace's `_iso_encoding.json`.
That combined recheck verified **118 fitting resources and 3 remaining
failures**: Miners main logos in `uh023.iff` / `ua023.iff`, and the Miners
center-court texture in `s023.iff`. All 987 master files remained unchanged.
With the subsequent memory-independent codec, fixed-span encoding fits 120
resources; only the Essen floor scene remains blocked. No POC ISO has been
published. The fixed-span default remains blocked; the
opt-in repacking check now fits the complete set without simplifying Essen.

A per-master palette cap is recorded explicitly:

```json
{"schema": 1, "palette_colors": {"b1331bd7": 64}}
```

Save this as `_iso_encoding.json` at the native workspace root. Valid caps are
16, 32, 64, 128 and 256; the native PSMT4 limit remains 16. Unlisted masters use
their full native palette. This changes encoded output only, not artist masters.
Re-run the complete check after any policy change; individually fitting profiles
do not establish that their final combination fits.

### Experimental pooled archive storage

Add `--repack-archive` to either check/build command or to the season pipeline.
This recompresses complete edited resources, updates their size/scratch headers,
and pools package sectors within the existing four archive extents. It does not
grow the disc image or change team slots.

The real combined check verifies **121 resources, zero capacity failures**, with
**636,928 bytes (622 KiB) free** after packing. Essen's main logos encode to
9,456 bytes each instead of the original 15,536-byte bodies; its floor scene
grows from 269,680 to 288,432 bytes and borrows storage released elsewhere.
All 987 masters and all non-ProA artwork remain unchanged. The largest additional
temporary scratch requirement is 16 bytes.

These are offline loader/encoding/allocation results, not an in-game certificate.
See [archive repacking](./ArchiveRepacking.md) for executable evidence, class
palette measurements, limitations and the consolidated runtime review catalogue.
Repacking remains explicitly opt-in pending that review.

Season automation consumes the same masters:

```powershell
python scripts\update_season.py --skip-scrape --season 2026_2027 --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "C:\Tools\isos\ProA-season.iso"
```

`--texture-workspace PATH` selects another native workspace. Its `team_palettes`
subfolder is used for both roster UI colors and lettering/courts unless
`--team-palettes PATH` overrides it. The standalone `season_iso.py` equivalent
override is `--workspace PATH`. Court controls and logo changes are merged in
decoded space, checked for conflicting writes and compressed once per resource.

Standalone legacy cloth, roster and lettering tools retain their original
`texture_workspace/team_palettes` default. Pass
`--workspace texture_workspace_ISO\team_palettes` explicitly when exporting or
checking the copied lettering controls. The legacy cloth generator still reads
the original workspace; native uniform artwork migration is a later milestone.

ISO season mode no longer generates legacy logo replacements by default.
`--legacy-logo-replacements` explicitly retains that optional comparison output;
card-only/build-only alternatives preserve legacy generation behavior.
Existing replacement files are not deleted.

Publication uses the verified, equal-size ISO-copy publisher (with streaming
relocation when selected) and writes
an adjacent `.logos.json` or `.season.json` manifest with patch/source/output
fingerprints. Always build from the untouched pristine Europe ISO to a **new**
output outside the workspace; never chain patches over an earlier output.

For in-game review, disable legacy logo replacements, cold-boot the new ISO and
avoid old rosters/savestates. F10 reloads PCSX2 replacements, **not ISO assets**.
Native encode/decode and compression verification are not an in-game rendering
certification.
