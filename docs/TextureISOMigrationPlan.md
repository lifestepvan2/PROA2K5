# Texture workspace to portable ISO: migration plan

## Goal and boundaries

Make the ISO sufficient for every supported visual mod. Keep the existing
`texture_workspace` concept: export editable images, organise them, edit MASTERs,
generate COPY/LOD children, validate, and build. Normal season updates must
eventually need neither PCSX2 dumps nor its replacement directory.

This includes generated portraits/icons/logos, automatic and manual complexion
changes, uniforms, lettering, arena/court images, signs, UI, atlases, and the
sources behind runtime-generated textures. It does not mean replacing every
original image, recolouring untouched NBA teams, or treating movie frames and
render targets as ordinary static textures.

Preserve the pristine ISO, artist originals, existing labels and team folders,
roster/card functionality, and the established team-palette controls. Do not
silently omit unsupported edits or use PCSX2 replacements as a production fallback.
The inventory/bridge below is implemented. The first
[native logo/centerlogo POC](./NativeLogoWorkflow.md) now implements master export,
mip/palette encoding and verified publication wiring using `texture_workspace_ISO`.
Its initial defaults still have fixed-span capacity blockers; other texture
categories remain on the legacy workflow. Historical audit counts below are
snapshots, not the current native export inventory.

## Milestone 1: implemented inspection workflow

Run with the project's Python environment (NumPy and Pillow required):

```powershell
python scripts\texture_catalogue.py --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --out cache\texture_iso\catalogue.sqlite
python scripts\texture_iso_audit.py --catalogue cache\texture_iso\catalogue.sqlite --out cache\texture_iso\milestone1
```

Both output paths must be new; choose another path to regenerate. The catalogue
requires the pristine Europe source fingerprint and checks the full ISO again
before publication. The SQLite database includes decoded original pixels and is
an ignored inspection cache, not a patch manifest. Compressed-resource pixel
offsets refer to **decoded data**, not writable ISO byte offsets. Metadata-only
resource body hashes are null; owning asset hashes cover their original bytes.

The full-disc implementation inventories:

- All 3,728 assets and 30,738 resource headers.
- 32,344 explicit descriptors, including 3,303 inside all 1,058 TSETs and
  descriptors/material names inside SCNE/HiSn containers.
- 19,820 size-accounted standalone linear textures, producing 23,258 images
  including known seven-level mip chains; 10,882 dimension-aware pixel digests.
- 12,524 descriptors whose pixels require a shared/packed transfer decoder,
  15 scene resources with unsupported material pointers, and 63 opaque asset
  tails. These remain visible blockers, not successful image exports.

The audit covers every manifest entry plus the union of managed keys and live
replacement PNGs, not just conveniently decoded images. The current snapshot has
17,157 manifest entries, 1,379 replacement PNGs, 493 managed keys, 146 manual
sources and 745 generated workspace children: 639 seed targets and 1,384 active
targets including the five missing managed outputs. All 17,642 union keys receive
a status. There are 4,243 exact content mappings, including 444 active targets.
The remaining 940 active targets have explicit blockers; no successful native
texture build is claimed.

### New source and ownership findings

The native portrait collection is archive hash `35cb8d72` (822 TXTRs, each
128x128 PSMT8); its original filename has not been recovered. Numeric descriptor
names can be cross-checked against PID. Of 254 current portrait keys, 248 exactly
match their PID-named native descriptor, one instead matches the shared `nophoto`
image, and five disagree with the expected PID image. Portraits are **not** the
model-local `face` UV textures in home/away player bundles. Do not patch a shared
placeholder globally or silently turn those five conflicts into PID mappings.
All native content aliases, including numeric portrait variants, are retained.

Separately, five managed outputs lack their ProA headshot inputs. These are not
the same set as the five PID/dump conflicts; inspect the two reports independently.
The first contact sheet makes the latter conflicts concrete: legacy "portrait"
keys show sponsor logos, wood or a model-face UV atlas, alongside photographic
native PID candidates. This is evidence of old-key misattribution, not a reason
to edit those non-portrait assets. Existing generator maps are preserved pending
batch review and later native migration.
Native bundle ownership, material names and texture names are kept separate from
old folder/filename labels. An identical image in several team/model bundles
does not establish exclusive ownership or permission to change every consumer.
Filename-based COPY/LOD inheritance is recorded as a **candidate relationship**,
not independent proof of a child's ISO source.

### Reports and batched review

The audit output contains:

- `summary.json`: counts, active blockers, warnings and workspace integrity result.
- `assets.csv`, `resources.csv`, `textures.csv`: native provenance and layout status.
- `workspace_mapping.csv`: the complete union, exact aliases, source dimensions,
  original-pixel fingerprints, candidate inheritance, old labels and separate
  evidence-based role suggestions.
- `seed_targets.csv`, `active_targets.csv`: explicit seed/expanded coverage.
- `portrait_sources.csv`, `missing_managed.csv`: PID conflicts/shared placeholders
  and missing generator inputs.
- `review_questions.csv`: stable workspace IDs, evidence, scope/label questions
  and editable answer fields; no answers are automatically applied.
- `review_batch_001.png`, etc., and `review_instructions.txt`: 20 items per sheet,
  40 pictured items by default (`--review-limit` changes this bound). The CSV keeps
  the complete queue. Original/native and current artist images are shown together;
  PID-conflict cards also show the unconfirmed native PID candidate.

  The current queue has 262 questions, including 226 rows with old-label/sharing
  warnings. The five PID conflicts and the shared placeholder appear in batch one.
  The 940 active blockers break down into 834 uniform transfer/inheritance cases,
  90 logo variants/scene transfers, nine scene/atlas images, five portrait-key
  conflicts and two unidentified sources. These are a measured research backlog,
  not requested edits that may be silently dropped.

Questions concern identification, old labels and intended sharing. They do not
ask a human to solve compression/transfer formats. No native encoding-quality
preview is claimed in this milestone. Missing/duplicate IDs, unsupported sources
and stale ownership stay explicit; artist images, IDs, folders, manifest and sync
state are never rewritten. The audit hashes workspace files before and after.
Existing `export`/`sync` and season deployment behavior remain unchanged.

### Follow-up: packed uniforms identified

The [uniform storage/rendering investigation](./UniformISOFormat.md) now
reconstructs the GS32-upload/PSMT8/CSM1 layout and matches **all 834 previously
blocked uniform targets** exactly against original dumps. NBA warmups also have
their `whNNN`/`waNNN`/`wxNNN` filenames recovered. The milestone-one snapshot and
artist files remain unchanged; the new inspection report adds source evidence,
not encoded patches or an approved alias fan-out policy. Milestone 2 still needs
encoding, no-op/writeback validation and capacity work.

### Follow-up: all 90 blocked logo variants identified

The [logo storage/rendering investigation](./LogoISOFormat.md) now matches all
90 historical blocked logo keys exactly against current original dumps.
Thirty-eight map to standalone TXTRs and 52 to embedded floor-scene uploads.
Reading descriptor `+0x18` as a raw video-relative offset exposes those scene
allocations; material/mesh links identify misleading `wood`/`ball` labels as
center-logo artwork. The 90 keys represent 76 distinct images, with all native
aliases retained. This adds source evidence and complete mip-chain context,
not encoding, workspace changes or approval to edit every shared consumer.

## 1. Findings from read-only inspection

The survey used the pristine European ISO, not emulator navigation.

| Evidence | Finding and consequence |
|---|---|
| Archive index | 3,728 entries. The logical archive is split across `VC_53022/0.` through `3.`; the first three files are each 1 GiB. |
| Explicit texture descriptors | 22,497 parsed TXTR/HITX resources: 21,966 TXTR and 531 HITX. Descriptor PSMs: 15,757 PSMT8, 6,738 PSMT4, two PSMCT32. This is not a complete count of scene-embedded/generated textures. |
| Compression | 17,638 TXTR resources are compressed; 4,328 TXTR and all 531 HITX resources are uncompressed. The current bounded VC-LZ codec is useful but not a general image importer. |
| Other containers | 2,917 SCNE and 1,058 TSET chunk headers were encountered. Known court images live inside SCNE, not only named TXTR objects. HiSn, FONT and opaque stream assets also require classification. |
| Non-resource streams | 63 entries stopped ordinary resource walking at a non-resource boundary. These are explicit investigation items, not missing textures to ignore; some contain multimedia data. |
| Existing workspace | 17,157 entries, with 146 manually edited sources after excluding generated COPY/LOD changes. Of these, 130 are uniforms; the rest cover arena props, broadcast/sponsors, courts, parts, skin, wordmarks, logos, UI and faces. |
| Generated ownership | 493 currently pipeline-managed dump keys, disjoint from the 146 manual source edits: 639 seed keys before expanding derived outputs. These are keys, not distinct native resources, and counts will change with the roster. |
| Actual replacement directory | 1,379 PNGs: 488 current managed outputs plus 891 non-managed workspace outputs. Workspace state records 745 automatic outputs, in addition to the 146 edited sources. No PNG is outside the current managed/workspace key sets. Five managed keys have no current output and need an explicit missing-source/disposition check. |
| Exact static matching | Native frontend flipchip icons 000-002, the Pistons home preview `unif`, and PID 235's face/arm/neck each matched an existing dump exactly in RGBA, without gameplay. |
| Packed image evidence | Pistons game `unif`/`short` have 180,224 video bytes for 512x256 descriptors; its 256x256 `logo` has 90,112. They are not the simple base-image-plus-CLUT layout used by the preview/player helper. |
| Sharing | Identical dump content can correspond to several independently editable native resources. Conversely, several dump images may derive from one native atlas, mip chain or runtime generator. |

Important qualifications:

- The portrait generator follows the final **PID**, not simply the roster record.
  The native source path for the existing lineup-portrait replacements has not
  yet been proved by this survey. It is an early research gate, not a solved map.
- Executable UTF-16 strings expose naming templates including `p%03d%c.iff`,
  `p%03d%c2.iff`, `sel%s.iff`, `bh%03d.iff` and arena filenames. The index contains
  two home/away alternate-model pairs, for PIDs 35 and 404; variants must be
  inventoried rather than assuming only one home and one away file.
- Old documentation saying hashed/compressed assets cannot be mapped statically
  is too strong. Exact native-to-dump matching now works for demonstrated layouts.
  It does not establish a universal decoder or ownership map.
- Arena asset IDs are not roster slots. Reuse `court_sources.csv/json`.

### Capacity is a first-class problem

The total gaps between indexed assets are only 3,872,952 bytes; no individual
gap exceeds 2,044 bytes. These are predominantly sector alignment, not a useful
general replacement pool. Arbitrary new artwork cannot be promised to fit each
old compressed span and scratch budget.

There are 20,977,664 bytes after the final archive segment's file extent, but the
last 2,048-byte sector is a **UDF anchor**, not disposable padding. The intervening
20,975,616 bytes read as zero; this is only a candidate allocation area.
The image has both ISO9660 and UDF metadata. UDF anchors at sectors 256 and
1,679,407 reference descriptor sequences at sectors 32 and 48.

Therefore, do not append bytes, enlarge a segment, or change index sectors without
understanding both filesystem views and the game's segmented-archive reader.
Keep the final anchor, non-texture files and opaque streams intact.

The subsequent [native archive investigation](./ArchiveRepacking.md) proves the
reader's header-driven size/sector and allocation contract. An opt-in streaming
repacker now pools sectors **inside the unchanged four extents**, preserving
directory ordinals and unsupported asset bytes. The complete logo POC fits
offline without disc growth or non-ProA simplification; cold-boot certification
is still a separate gate.

## 2. Target design

### A. One native source catalogue

Identify a texture by the pristine-source fingerprint, archive hash, logical
resource identity/ordinal and descriptor or subimage identity. Physical offsets
are locations in a particular build, not the permanent editing identity.

Catalogue fields should include:

- Asset/chunk identity, type, offsets, compression, decoded sizes and scratch.
- Name, dimensions, PSM, CLUT representation, alpha rules, transfer layout,
  mip levels, atlas rectangles and any material modulation.
- Team/arena/PID/variant ownership, all aliases and shared consumers.
- Original native-byte and decoded-pixel fingerprints.
- Legacy dump keys and workspace IDs, with exact/derived/ambiguous/unresolved
  mapping status and evidence.
- Supported editing operations and explicit unsupported reasons.

Use filenames, descriptors, resource references and exact pixels first. Use
structural/visual matching only to produce review candidates, never to silently
choose a patch destination. Cache extraction by source hash. Preserve unknown
chunks verbatim rather than attempting to reinterpret arbitrary stream data.

### B. Preserve the workspace, change its backend

Keep folders, editable images, team subfolders and filename-based
`MASTER__LABEL__RES__ID` inheritance. Retain every existing artist file and ID.
Folder moves must not change targets. Extend the manifest to connect each ID to
native sources; retain old dump keys as migration/debug aliases.

Recommended workflow, with proposed CLI names:

1. `texture_workspace.py export --iso-source PRISTINE`: native-first export;
   never overwrite an edit or require that a texture has appeared in a dump.
2. `texture_workspace.py check`: ownership, mappings, dimensions, alpha, palette
   limits, inheritance, atlas overlaps and capacity preflight.
3. `texture_workspace.py sync --target iso`: resolve edits and generate a
   texture recipe/cache, not another independently patched ISO.
4. `update_season.py ... --iso-out NEW`: publish one combined output.

An explicit `--target pcsx2` may remain a development/legacy preview option.
Its state must be separate from native export state. F10 is not an ISO refresh;
ISO changes require fresh resource loading, normally a cold boot.

Store immutable native baselines separately from edits and generated previews.
Restoring an image removes its edit intent; each build starts from the pristine
source, so no reverse-patching of a previously modified ISO is needed.
Existing non-role manual images, resize/fit options and RGB-with-original-alpha
behaviour need compatibility tests, not just MASTER-only migration.

### C. One image codec and one asset composer

The codec must cover PSMT4, PSMT8 and observed PSMCT32, CLUT ordering, packed GS
uploads, alignment, alpha and complete mip chains. Extend the existing proven
decoder rather than inventing a second incompatible image path.

Keep artist masters at their chosen resolution. Show the actual native-size,
palette-constrained encoded result alongside them. Indexed PS2 assets cannot
necessarily reproduce high-colour/high-resolution PCSX2 replacements exactly.
Do not silently reduce quality: report quantization and alpha differences and
obtain batch approval for affected classes/examples. Do not default to larger
native textures or true-colour conversion: VRAM, transfers and descriptors constrain
those changes too.

Collect all edit intents before encoding. Decode an affected resource once,
apply compatible operations, encode once, and rebuild its owning asset once.
Only the final asset spans go to `season_iso.py`/the publisher.

This is necessary because:

- Court controls and manual court-image edits may touch the same SCNE.
- Generated complexion changes and manual face/arm/neck edits may share a player
  asset.
- Lettering palettes, glyph artwork and generated name/number results are related.
- Several logo variants may be rectangles of one atlas or mips of one source.

Keep pipeline ownership over its current managed targets by default. Allow
deliberate exceptions only through explicit manifest ownership, not filesystem
order. Reject competing writes to the same pixels/palette/material field.
Group atlas edits into one composition; preserve untouched regions.

### D. Recompression and archive capacity

Prefer in-place fixed-span edits when they fit and preserve decoder safety.
For general artwork, add a verified growth path rather than asking artists to
choose worse pictures until the old compressor budget happens to fit.

Investigate in this order:

1. Better bounded recompression, preserving unedited decoded data.
2. Rebuilding an affected IFF with correct stored sizes, scratch and internal
   references, then relocating that asset through the archive index.
3. Safe use of verified free allocation space, or deterministic repacking of the
   segmented logical archive if append-only relocation cannot fit the active set.

Prove relocation first with **unchanged** asset bytes, then a resized resource.
Validate sector units, segment crossings, alignment, directory extents, UDF file
entries/allocation metadata/checksums and both filesystem views. Preserve
unmodified opaque/video/audio payloads byte-for-byte. Report projected budgets
before publication. If the existing image cannot accommodate the approved set,
image growth is a separate verified filesystem/loader task, not automatic padding.

The current fixed-size publisher can still handle an equal-size image with changed
index/filesystem spans. General image-size changes would need an explicit publisher
extension. Preserve ELF/game CRC behaviour and the completed roster milestone.

## 3. Migration sequence and acceptance gates

| Milestone | Work | Acceptance gate |
|---|---|---|
| 1. Native catalogue and legacy bridge | Production inventory, descriptor/layout classification, exact matching, alias graph, ownership and current-workspace audit. Resolve the portrait source path and distinguish source images from generated results. | Account for all 1,379 current replacement PNGs, all 639 seed keys and their derived outputs, and the five missing managed outputs. Every active target has a verified native/derived mapping or a specific blocker; all 17,157 workspace entries have a recorded mapping status. Artist files/IDs survive. No ISO is published or edit silently dropped. |
| 2. Codec and capacity foundation | PSMT4/8/32, alpha, mips, packed transfers; no-op round trips; representative encoding; archive-reader/ISO9660/UDF growth investigation and relocation proof. | Representative UI, uniform, model and scene resources pass encode/decode checks. Unchanged relocated assets load correctly. The real active edit set has a measured fit/growth report. |
| 3. Manual workspace parity | Migrate the 146 current manual sources, beginning with uniform MASTER/COPY/LOD groups, then arena props, floors, signs, wordmarks, skin and UI. Add atlas masks and scene-backed sources. | Every active manual edit has an explicit native outcome; preview and game uniforms agree, children/mips are complete, no edits are overwritten, and court controls compose correctly. |
| 4. Generated visual parity | Move portrait/icon/logo/skin generation to native recipes; use final roster/PID assignments and existing headshot/logo inputs. Include all home/away/alternate assets and logo atlases/embedded signs. | No current pipeline-managed visual needs replacement PNGs. Automatic reserve recolouring and manual Skin Tone work together; donor/legend effects and sharing are reported. |
| 5. Remaining source classes | Resolve generated jerseys/text, font/atlas derivatives, HiSn/TSET/scene cases, animated materials and any edited movie-backed textures. Add the actual upstream converter where required. | Every requested edit in every workspace category has a supported source path or an explicit reviewed disposition. No production output depends on dump-time/frame-specific substitution. |
| 6. ISO-only default and release | Integrate all recipes into the season composer; remove dump dependencies from normal generation, keep legacy preview explicit, update documentation and coverage reporting. | Cold boot with cards, replacements, cheats and savestates disabled; zero unresolved requested edits; offline invariants and the review matrix below pass. |

Milestones 2 and 4 can involve separate bounded research, but neither should bypass
milestone 1's source evidence. Migrate easy known formats first; do not make a
generic exporter appear complete by exporting only named TXTRs.

### Specific generated-pipeline changes

- Refactor `gen_replacements.py`, `gen_logo_replacements.py` and
  `gen_skin_replacements.py` into image/recipe production plus optional backend
  output. Reuse crop, logo-fit and recolour helpers where correct.
- Replace dump-dependent logo variant discovery with native source/atlas coverage,
  including sign composites and split wordmarks, not just today's accepted matches.
- Keep ProA ID, Headshot ID, final PID, roster slot and arena asset identity distinct.
  Preserve `player_database.py`/override semantics; do not key a portrait by filename
  order or introduce player-schema changes solely to deploy textures.
- Replace runtime name/number images at their source glyph atlas/palette/generator
  inputs, not by assuming each generated PNG exists as a disc image.
- Once native skin migration is complete, remove the legacy replacement-key donor
  exclusions from the ISO-only path. Keep collision protections while mixed mode
  exists; do not drop those guards prematurely.
- A movie-backed tile requires a movie/frame-sequence source workflow preserving
  timing/audio, not one IFF texture patch per dumped frame. Unedited movies remain
  untouched. Edited render targets require finding their upstream source first.

## 4. Human review: batches, not continuous handoffs

Generate self-contained review packs after machine analysis. Each pack contains
numbered contact sheets, a short question catalogue, a CSV answer template and
an impact/coverage summary. Group 20-40 ambiguous or representative items by
category; allow decisions for a whole class where appropriate.

Each card shows original native rendering, matching dump/crop if relevant, artist
edit, encoded native preview, affected owners/aliases and the reason for review.
Do not ask humans to navigate every team, identify hashes, or inspect all 22,497
resources. Batch unresolved/low-confidence cases and representative quality checks.

| Batch | Question catalogue |
|---|---|
| A. Identity and sharing | What does this image/atlas region represent? Is it shared intentionally? Apply to every current consumer or only the listed team/PID/variant? Protect donor/legend usage? Which proposed crop/target is correct? |
| B. Uniforms, logos and atlases | Are these COPY/LOD/preview relationships correct? Which split regions form one logo/wordmark? Which signs should retain sponsors? Which variants should inherit the home/away design? |
| C. Native quality | Is this native-size, 16/256-colour result acceptable? Are alpha edges, gradients, thin text, seams and mip appearance correct? Which flagged examples need mask/palette revisions? |
| D. Unusual sources | Is this movie/animated/render-target image intentionally edited? Replace the complete upstream clip/atlas, preserve the original, or supply a suitable source asset? A preserved original is not an implemented replacement. |
| E. Integrated game review | Does the prepared matrix show correct portraits/crops, preview/game uniforms, skin continuity, floor/sign/logo coverage and no unintended donor/legend changes? Return all failures together with item IDs. |

Answers should be machine-readable, for example:
`item_id, decision, target_scope, region, quality_approved, notes`.
Accept approved items together, rerun checks, and return only remaining/newly
affected exceptions in the next pack. Missing answers remain visible blockers.
No implementation-time question is needed for something the ISO or an existing
source map can settle.

## 5. Verification and definition of done

Offline checks do most of the work:

- Full-source fingerprint; bounded inventory and explicit opaque resources.
- Original-image decode fixtures, exact static dump matches and edited-image
  encode/decode comparisons for every supported storage class.
- Byte-identical no-op output; immutable geometry, descriptors and unrelated
  content unless an operation explicitly owns the relevant field.
- All mip levels/aliases/atlas regions accounted for; deterministic palette and
  compression results, alpha preservation where required, measured quality loss.
- Workspace migration idempotence; moves/renames, restored originals, edited COPY
  compatibility, stale state, duplicate IDs and missing sources tested.
- Duplicate/shared-image cases and compositing conflicts tested.
- Capacity/scratch failures explicit; overlap-free final patches; full output
  read-back; both ISO9660/UDF file views consistent; unaffected streams unchanged.
- Roster/PID, team and skin recipes bound to the same final season build.

Then use a small deliberate in-game matrix, not repeated exploratory runs:

- Team-select preview, Start Game portraits/icons and player cards.
- One home/away game with both heavily edited teams, alternate uniform and a
  low-detail/distant view; expand only where layout differences require it.
- Representative arena/court/atlas families, boards/signs, warm-ups and accessories.
- Skin overrides plus automatic-reserve players, and donor/legend controls.
- Loading/animated sources only where changed.
- Card-free cold boot and Reset Roster still pass the roster milestone checks.

Release only when there are **zero unresolved requested edits**, every applicable
category has a documented native source path, and the game works with the entire
replacement system disabled. There must be no "successful ISO" with unexplained
unmapped PNGs, missing portraits or a hidden dependency on local dumps.

## Recommended next implementation step

Review the milestone-1 identity/sharing batches, then begin milestone 2:
verify packed game-uniform and shared scene/set transfer layouts, build no-op
codec round trips, and investigate archive capacity/relocation without publishing
an edited ISO. Keep portrait PID conflicts and missing headshot inputs explicit.
Do not treat the inspection cache or exact pixel aliases as an approved patch plan.
