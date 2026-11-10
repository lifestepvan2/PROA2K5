# Native logo storage and rendering investigation

## Result and scope

**All 90 previously blocked generated-logo targets have exact native matches.**
The comparison includes dimensions and every RGBA byte, including original PS2
alpha, checked against the current clean dump PNGs. No artist/replacement pixels
were used as matching evidence.

These are specifically the 90 `logo-variant-or-scene-transfer-unproved` entries
in the frozen milestone-one audit, not the entire logo generator inventory or
every sign/logo on disc. Their dimensions are:

| Dimensions | Legacy keys |
|---|---:|
| 256 x 256 | 31 |
| 128 x 128 | 31 |
| 64 x 64 | 28 |

The 90 keys represent **76 distinct dimension-aware images**. Different old keys
can contain identical pixels; they must remain aliases, not separate edit intents.
The source search retains **315 matching native mip images**, across 141 native
texture groups and 115 archive assets.

| Native storage | Target keys | Matching mip images | Texture groups |
|---|---:|---:|---:|
| Standalone TXTRs in team/uniform bundles and the common logo collection | 38 | 261 | 121 |
| Embedded SCNE textures, all in scenes named `floor` | 52 | 54 | 20 |

The two key sets are disjoint. The first 38 were found in the uniform investigation;
the additional 52 require correctly isolating uploads inside scene video data.
Every match here is a **whole stored mip image**. No fuzzy matching, native atlas
rectangle extraction, rotation, or reconstruction from game screenshots was
needed. A texture containing one piece of a split logo is still a whole native
texture, not evidence that the dump itself was cropped from an atlas.

This is source identification and read-only rendering-context analysis.
Encoding, quantization, recompression, capacity, alias publication policy and
in-game validation were not implemented or certified by this investigation.
The subsequent [native logo POC](./NativeLogoWorkflow.md) implements the writing
path and current-team ownership policy, with explicit capacity/quality blockers;
in-game validation remains outstanding.

## Shared scene video: the missing link

SCNE/HiSn descriptors have a 56-byte stride. Their field at descriptor `+0x18`
is a **raw byte offset relative to the resource's decoded video tail**. It is
not a tagged system pointer, GS address, or writable ISO offset.

For a descriptor with video offset `start`:

1. Read all descriptor video offsets in that resource.
2. Its upload ends at the next **distinct larger** offset, or declared video end.
3. Repeated offsets retain separate descriptor identities but share the span.
4. Require valid descriptor/system bounds and `0 <= start < end <= video_size`.
5. Decode only `data[system_size + start : system_size + end]`.

The shared helper first tries fully size-accounted linear layouts (including the
known seven-mip layout), then the independently tested GS32-upload decoder.
The POC extended fully size-accounted linear decoding to one through seven
levels; newly inventoried centerlogo textures include six-level PSMT8/PSMT4
chains. This does not change the GS32-only result for the historical 90 targets.
Unsupported layouts remain explicit report rows. It never uses a plausible
partial decode as an exact match.

An independent cross-check is `s021.iff` / `floor` / `lines1`:
system size `0x1C700` plus raw video offset `0x2C5B0` gives decoded pixel offset
`0x48CB0`, agreeing with the existing court map. Its 6,512-byte span is a linear
64 x 64 seven-mip indexed texture with palette. This line mask is a format
cross-check, **not one of the 90 logo targets**.

Unlike that line mask, **all 315 matched logo mip images use GS32-packed uploads**:
consecutive 64 x 32 PSMCT32 upload pages, sampled as PSMT8 with a PSMCT32 CSM1
palette. The same address equations established for uniforms apply after
isolating the correct upload. A mixed scene resource need not itself have a
page-aligned video size or page-aligned upload start.

See [UniformISOFormat.md](./UniformISOFormat.md) for the address equations,
palette handling and representative 256 x 256 allocation. The common logo chain
is 256, 128, 64, 32, 16 and 8 pixels square. `mip_chains.csv` records the complete
stored chain for each matching native descriptor, including levels absent from
the 90-key cohort. A future writer must regenerate those stored levels too,
not just the levels that happened to be dumped.

The final run verified six stored levels, from 256 x 256 through 8 x 8, for
**all 141 matched texture groups**. The dimension-filtered search retained
exactly the same 315 native matches as the initial full-resource search, and
every source alias recorded for the earlier 38-logo result remains represented.

## What the archive structure reveals

The matched assets fall into three structural families:

- **99 team/uniform bundles: 54 with verified uniform-family filenames and
  45 still unnamed.** Their common resource sequence includes
  `coachhead`, `coachneck`, `coachmodel`, `coachaface`, `coachaskin`, `smlogo`,
  `chiclet`, `logo`, names/numbers, `unif`, `short` and bands. Many also contain
  cheerleader, mascot or other team-associated resources. Even the named uniform
  files are broader team bundles, not jersey-only archives. Their logo is a
  separate TXTR; being stored with a uniform does not prove it is drawn on the
  jersey. For the unnamed files, the native bundle context is now identified
  even though the filename remains unresolved.
- **One common logo collection, archive hash `a90f4964`.** It contains 67 TXTR
  resources named `logoNNN`, including ordinary and non-ordinary team IDs. Its
  filename remains unresolved. Do not equate every numbered logo with a current
  NBA roster slot or apply one modern-team replacement to the entire collection.
- **15 arena bundles**, containing the matched `floor` scene descriptors.
  Some are non-ordinary arena IDs and are intentionally not assigned a modern
  owner without independent evidence.

An unknown filename is not a missing patch location: the verified archive hash,
resource ordinal, descriptor and source fingerprint already locate it.
Conversely, an exact image does not prove exclusive ownership or authorize
editing every matching bundle. `asset_contexts.csv` preserves the native resource
sequence and separates structural role, filename resolution and known ownership.

## Floor rendering and misleading material names

For every matched scene descriptor, the inspector follows:

`descriptor <- material texture reference <- mesh part material index`.

The material table uses 96-byte records; the table pointer is biased 16 bytes
into the first record. Name, RGBA and descriptor reference are at record
`+0x08`, `+0x58` and `+0x5C`. Meshes have 112-byte records, names at `+0x40`,
part counts at `+0x68`, and part pointers at `+0x6C`. Each 24-byte part selects
its material at `+0x08`. All arrays, references and stream spans are bounds-checked.

The matched floor-logo materials reference mesh parts of **`centerlogo`**.
Examples, using the authoritative arena map rather than assuming
`s{roster_slot:03}.iff`:

| Arena | Descriptor/material label | Actual mesh use |
|---|---|---|
| Wizards, `s002.iff` | `floor_stuff_vcSwShader2`, `centerlogoleft` | `centerlogo` parts 0 and 1 |
| Jazz, `s012.iff` | `wood`, `floor_stuff_vcSwShader2` | `centerlogo` parts 0 and 1 |
| Knicks, `s014.iff` | `wood` | `centerlogo` part 0 |
| Lakers, `s015.iff` | `floor_stuff_vcSwShader2`, `team_name` | `centerlogo` parts 0 and 1 |
| Magic, `s016.iff` | unnamed material, `descriptor-0` | `centerlogo` part 0 |
| Pistons, `s021.iff` | `ball` | `centerlogo` part 2 |

Thus `wood`, `ball`, `team_name`, `outside_border` and similar native material
names cannot safely label image content. The clean pixels plus the mesh/material
graph establish substantially better context than either name alone.

For example, the Wizards' two 90,112-byte uploads start at video offsets 180,224
and 270,336. They are separate texture allocations attached to different
`centerlogo` parts, not two replacement keys requiring an invented atlas.
Additional aliases occur in arenas such as `s507.iff`, `s509.iff`, `s512.iff`
and `s714.iff`; the report retains them instead of silently choosing one owner.

All matched descriptors have TEX0 `TFX=MODULATE` and `TCC=RGBA`. Material RGBA
and mesh-part references are recorded separately. This establishes texture
binding and modulation inputs, not final on-screen colour.

Standalone TXTRs do not embed equivalent draw-consumer links. The executable
contains named lookup templates such as `logo%s`, `%s_teamlogo` and `%s_mlogo`,
but these strings alone do not prove which screens consume each resource.
Runtime bindings, complete UI consumers, UV/VIF interpretation, TEX1/clamp,
filtering, blend state and LOD thresholds remain untraced. No emulator run or
claim of a complete renderer reverse engineering is part of this investigation.

## Relationship to the existing generator and workspace

`gen_logo_replacements.py` accepts mode-A reference-window matches for the
NBA slots occupied by ProA, excluding the existing partial reference frames.
These 90 historical targets each have one mode-A metadata row.

Its normalized `x/y/w/h` window describes composition in a reference-logo frame;
it is **not a native storage rectangle, scene UV range, or patch address**.
Keep that legacy composition recipe separate from the exact native destination.
Mode-B embedded-sign matches are not silently included in this cohort.

For ISO migration:

1. Keep the existing manually editable logo/master concept and workspace IDs.
2. Associate generated windows and legacy aliases with explicit native sources.
3. Compose split pieces from one consistent reference frame; do not independently
   fit the entire ProA logo into each half.
4. Regenerate complete native mip chains and coordinate shared palette writes.
5. Collect all writes to an arena scene before recompressing it, so court controls,
   manual floor edits and generated logos cannot overwrite one another.
6. Preserve every content alias as evidence, but approve intended publication
   scope explicitly, especially non-ordinary teams/arenas and shared collections.

There is no remaining human pixel-identification question for these 90 targets.
Future human checks should be one bounded sharing/quality/in-game review batch
with a question catalogue, not repeated requests to identify individual dumps.
The three contact sheets and source/consumer CSVs provide the evidence for that
later scope review; this investigation does not change generator behaviour.

At investigation time all 90 existing replacement PNGs were present, and keys
with identical original pixels also had identical replacement pixels. This was
a separate desired-output consistency check, not source-matching evidence.

## Reproduce and inspect the evidence

From the repository root, using an interpreter with the project's NumPy/Pillow:

```powershell
python scripts\inspect_logo_iso.py `
  --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" `
  --out cache\texture_iso\logo-storage-final
```

Choose a **new output directory** on subsequent runs. The script validates the
pristine Europe source through the existing archive reader, rechecks its SHA256
after inspection, and verifies all target original PNGs against the frozen
baseline. Candidate resource selection covers every supported mip geometry for
the target sizes; every descriptor in a shared resource remains available for
span boundaries.

Outputs:

- `summary.json`: cohort, exact coverage, native families and explicit exceptions.
- `logo_coverage.csv`: all 90 old keys, equal-content aliases and all source IDs.
- `native_sources.csv`: matching mip provenance, upload bounds, GS addresses,
  source ownership, material context and context errors if any.
- `mip_chains.csv`: complete stored mip chains for each matching descriptor.
- `material_consumers.csv`: material RGBA and native mesh-part/stream references.
- `asset_contexts.csv`: all matched archive assets and native resource structure.
- `generator_reference_windows.csv`: unchanged reference-window metadata.
- `resource_inspection.csv`: decoded candidates and explicit unsupported reasons.
- `logo_originals_001.png` through `003.png`: clean original-image contact sheets;
  alpha is normalized **for display only**.

Reports are ignored cache outputs, not approved patch plans. GS TBP/CBP values
are addresses inside an upload's GS layout. Decoded offsets refer to decompressed
resource data; none can be treated as a direct ISO write offset.

The milestone-one snapshot, existing uniform findings, original dumps, artist
files, generated replacements, labels and pristine ISO are preserved.

Validation: 67 targeted texture/VC-LZ/workspace tests pass, editor diagnostics
are clean, and the shared material reader was also checked against all 278
native high/low body-material records in the two common bundles.
