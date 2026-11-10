# Native archive sector pooling (experimental)

The original per-resource compressed length is **not** a hardcoded texture
budget. It is possible to redistribute disc storage across native packages
without changing texture dimensions, moving a team to another roster slot, or
growing the ISO. This does **not** pool PS2 runtime RAM or VRAM.

## Evidence from the pristine Europe executable

Source ISO SHA256:
`4cdad2339dbe2828b440ca222f869f234b15c0321c8dcdeac016a30b10678fb7`.
EE addresses below are virtual addresses in `SLES_530.22`; IOP addresses are
module-relative offsets in `VC_53022/DATA/IOP.IRX`, before relocation.

| Reader | Evidence |
|---|---|
| IOP `0x53E4` initialization | Reads the 156-byte archive header, then `entry_count * 12` directory bytes. Records are hash, byte size, logical sector. |
| IOP `0x3FA8` indexed reads | Requests identify a directory ordinal. Bounds are checked against that entry's size, and reads use its sector plus the requested byte offset. |
| IOP `0x4598` segmented reads | Divides logical sectors by header word `+0x0C`, selects the physical segment, and caps the run at its boundary. |
| IOP `0x4F04` | Splits a crossing read between adjacent physical segments. |
| IOP `0x4AEC` | The stock header's strategy zero selects `0x4598`; the alternative sector-scan path at `0x47D4` is not used by this image. |
| EE `0x122480` | Skipping an unhandled resource advances by its stored-size field before requesting the next header. |
| EE `0x128AA8` TXTR/HITX allocation | Reads system/video/stored/scratch from resource headers; allocates system + video + scratch at `0x128B44`. |
| EE `0x128BF0` | Places compressed input at allocation base + system + video + scratch - stored size. |
| EE `0x129DF4` SCNE allocation | Uses the same header-driven allocation and compressed-input placement. |
| EE `0x128870` decompressor | Reads the stream's distance-bit count, flags and tokens. Match copies run backwards. |
| EE `0x124A28` heap allocation | Does not clear the returned user allocation. New match tokens must not assume unwritten output contains zeros. |

These observations support relocating packages and changing compressed resource
lengths. Directory order/ordinals are preserved, so filename-to-ordinal lookup
does not need to be changed. They do not prove every gameplay load path.

## Allocation contract

The logical archive occupies the existing four contiguous file extents:
three 1 GiB files and a final 187,199,488-byte file, **3,408,424,960 bytes total**.
The image remains 3,439,427,584 bytes. No filesystem extent, executable instruction,
UDF anchor, or ISO9660/UDF directory metadata is rewritten.

1. Encode edited pixels into the original dimensions, PSM, descriptor and mip
   structure. Artist masters are never modified.
2. Recompress the complete decoded resource, rather than retaining a potentially
   inefficient original token prefix. Preserve the stream's first eight bytes.
3. Align stored bodies and scratch to 16 bytes. Verify full decoded readback,
   unread-input protection, and backwards copies in a shared buffer initialized
   with nonzero bytes. Emit only matches entirely within already-written output.
4. Update resource stored size/scratch, retaining system/video sizes and other
   header fields. Preserve all unedited sibling chunks and opaque package tails.
5. Apply **all** archive edits in original coordinates before relocating anything.
   This includes roster, lettering, player skin and combined court/logo writes.
6. Pack assets in original directory order on 2,048-byte sector boundaries, update
   index sizes/sectors, and reject aggregate overflow. Packages are conservatively
   limited to one segment's size; starts can cross a segment boundary.
7. Stream unchanged data from the pristine source, avoiding a multi-gigabyte
   before/after patch. Verify the complete source and output before atomic,
   no-overwrite publication, retaining the existing adjacent manifest.

Sector padding is still required. Reducing a compressed body only frees pooled
storage when its containing package loses whole sectors. Extra zero bytes after
the original archive are **not** included in the pool.

Extra scratch is temporary decoded-heap demand, not extra VRAM. A palette cap
saves compressed storage but does not reduce a fixed PSMT8/PSMT4 allocation.
The codec rejects an individual decoded-plus-scratch allocation above 32 MiB;
that hardware ceiling is not a guarantee of available heap during a match.

## Commands

The old fixed-span path remains the default. Opt into the experimental allocator:

```powershell
python scripts\texture_iso_workspace.py check --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --repack-archive
python scripts\season_iso.py check --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "C:\Tools\isos\ProA-repack.iso" --repack-archive
```

Both standalone builders and `update_season.py` accept `--repack-archive`.
`update_season.py` forwards it to preflight and final composition; it cannot be
used in card-only/build-only mode. Always select a new output path and boot fresh.

For read-only class-policy trials, the native standalone command additionally
accepts `--palette-colors 128` (or 64/32/16). This is a default for encoded logo
and centerlogo output from edited masters, not an edit to masters or saved policy.
Untouched stock references are not requantized. Explicit per-master caps take
precedence; PSMT4 remains limited to 16. No lower class default and no non-ProA
simplification are automatically enabled.

Fixed-span and resized compression caches have new versioned filenames: earlier
streams could depend on zero-filled unwritten memory and must not be reused.

## Measured budgets

The combined season preflight includes 237 lettering sources, court controls,
121 native logo resources and executable edits. It fits in the original extents
with **636,928 bytes (311 sectors / 622 KiB) free**, zero logo capacity failures
and 60 edited packages. Native-logo-only changes edit 58 packages; packing shifts
1,642 package starts in either case.

Essen's large logos re-encode from 15,536 to **9,456 bytes each**. Its floor scene
grows from 269,680 to **288,432 bytes**, with no extra scratch, using savings from
other edited packages. The largest scratch increase elsewhere is **16 bytes**.
The safe fixed-span codec now fits 120 resources and still blocks that one floor
scene; original stored spans are not reliable measurements of minimal encoding.

Class trials retain the ten already-approved explicit per-master caps:

| Default colors for edited logo masters | Pooled free bytes after packing | Mean visible RGB RMSE |
|---|---:|---:|
| 256 (current default) | 636,928 | 4.42 |
| 128 | 651,264 | 4.87 |
| 64 | 825,344 | 7.54 |
| 32 | 1,107,968 | 14.51 |

These are encoding-error measurements, not perceptual approval. There is no need
to impose a lower class default for this POC.

Separately, 24 large home/away logo resources belonging to the 12 non-ProA teams
were measured without changing any master or publication policy:

| Optional donor treatment | Compressed bytes saved | Additional pooled sectors / bytes |
|---|---:|---:|
| Stock artwork, lossless recompression | 0 | 0 / 0 |
| Two-level grayscale, retaining original alpha | 416,352 | 202 / 413,696 |
| Flat opaque gray, including native mip levels | 788,512 | 385 / 788,480 |

The flat trial deliberately discards the original silhouette/alpha. Both
destructive treatments preserve dimensions, PSM and decoded allocation. They
remain measurements only; applying them would require a reviewed donor policy.

Offline verification covered all **3,670 unedited assets byte-for-byte**, all
**1,092 unedited sibling chunks** in edited packages, and all **121 resized
resources**, including scratch-safe decoded fingerprints and unchanged opaque
tails. A complete no-op copy plan reproduces the pristine ISO SHA256 exactly.
Eight stock donor streams were also reproduced byte-for-byte by the encoder;
all 24 reproduce their original stored lengths. Three planned package extents
cross physical archive-segment boundaries.

All **987 artist masters remained unchanged**. No ISO was published during these
checks. Reproducible local evidence is in `cache/texture_iso/archive-budget.json`,
`archive-donor-budget.json`, `archive-repack-verification.json` and
`season-repack-check.json`; cache files are generated reports, not build inputs.

## Batched runtime review gate

Offline parsing/readback is not a runtime certification. Keep this opt-in until
one consolidated cold-boot review covers the following catalogue:

| Check | Question / pass condition |
|---|---|
| Unchanged-artwork relocation control | Can a relocated, visually unchanged package load after a cold boot? |
| Frontend | Do Essen and two control teams display correct large/small logos, team-selection UI and preview models? |
| Grown scene | Does Essen's home court load with its center badge, floor, court controls, arena and both teams intact? |
| Unrelated package preservation | Do a non-ProA team and a second arena load with their original artwork? |
| Resource lifetime | Do away/home rematches and repeated frontend-to-match transitions remain stable? |
| Boundary streaming | Does an actual package crossing an archive segment boundary read correctly? |

Disable legacy logo replacements, do not load a savestate/old roster, and record
all answers together. A future native uniform importer can reuse the allocator,
but this implementation does not itself migrate uniform artwork.
