# Uniform storage and rendering investigation

## Result

The original clean PCSX2 dumps verify the missing game-uniform layout.
All **834 uniform targets** blocked in the milestone-one snapshot now have exact
native pixel matches: **110 manual sources and 724 generated COPY/LOD children**.
No labels or artist files were changed, and no texture ISO was published.

The key distinction is **upload format versus sampling format**:

1. Decompress the native resource with VC-LZ where indicated by its header.
2. Interpret the video tail as consecutive **64x32 PSMCT32 upload pages**.
3. Use the descriptor's **PSMT8** addresses to read the indexed texture and mips
   from the resulting GS memory layout.
4. Read the **PSMCT32 / CSM1 CLUT**, applying its index permutation.
5. Preserve every RGBA byte, including native alpha, when matching clean dumps.

This reconstruction is byte-exact against original in-game texture dumps.
It establishes the stored representation and its correspondence to GS sampling.
It does **not** substitute for tracing the actual uploader's instructions or
observing draw-time sampler/blending registers.

## Native files and roles

Names are verified against the archive's uppercase UTF-16LE CRC32 hashes.
Slots are native NBA uniform slots, not the current ProA ordering.

| Bundle | Role |
|---|---|
| `uhNNN.iff`, `uaNNN.iff`, `uxNNN.iff` | Game home, away and alternate uniform resources. |
| `seluhNNN.iff`, `seluaNNN.iff`, `seluxNNN.iff` | Team-selection preview resources; do not substitute these for game textures. |
| `whNNN.iff`, `waNNN.iff`, `wxNNN.iff` | NBA/other warmup home, away and alternate resources. These were missing from the first filename resolver. |
| `wuhNNN.iff`, `wuaNNN.iff` | Additional observed warmup naming, including the 600-series bundles; retain both naming families. |

Game jersey bundles contain more than clothing. For example, `uh021.iff` includes
coach textures/model, small logos, `logo`, `names`, `numbers`, `unif`, `short`,
uniform attributes, bands, cheerleader/mascot assets and crowd TSET data.
Being inside that bundle does not make an image jersey artwork.

The verified clothing texture names are:

- `unif`: game jersey artwork.
- `short`: game shorts artwork.
- `top`: warmup torso.
- `slv`: warmup sleeves.
- `pnt`: warmup trousers.

For example, the old Mavericks warmup torso dump matches `top` in both
`wh017.iff` and `wx017.iff`. Its identical pixels do not imply that changing only
one bundle will affect both variants. Preserve all aliases and intended scope.

## Descriptor and pixel storage

TXTR resources have the existing 32-byte resource header and independently
compressed system/video data. Self-relative pointers locate the descriptor;
do not assume its offset is always `0x30`.

The descriptor contains:

| Offset | Meaning used by the decoder |
|---|---|
| `+0x00` | TEX0: base pointer, buffer width, PSM, dimensions, palette and texture-function fields. |
| `+0x08` | MIPTBP1: pointers/buffer widths for levels 1-3. |
| `+0x10` | MIPTBP2: pointers/buffer widths for levels 4-6. |
| `+0x2C` | Explicit 16-bit width and height. |

The observed packed clothing is PSMT8 with a 256-entry RGBA palette:
CPSM=PSMCT32, CSM=CSM1, CSA=0. GS base pointers are in **256-byte blocks**.
They are not file offsets, and the video tail is not a linear RGBA image or a
concatenation of conventional indexed mip images.

### Representative 512x256 jersey/shorts layout

`uh021.iff` `unif` and `short` each have 112 system bytes and 180,224 video bytes.
The latter is 22 complete 8,192-byte pages: equivalently a 64x704 PSMCT32 upload.

| Level | Dimensions | TBP, in 256-byte blocks | TBW, in 64-pixel units |
|---|---|---:|---:|
| 0 | 512x256 | 0 | 8 |
| 1 | 256x128 | 512 | 4 |
| 2 | 128x64 | 640 | 2 |
| 3 | 64x32 | 672 | 2 |
| 4 | 32x16 | 692 | 2 |
| 5 | 16x8 | 694 | 2 |

CBP is **688**. The palette sits between the small mip allocations, in space
not addressed by the larger mip. The remaining MIPTBP entry is zero: there are
**six stored levels**, not a guessed seven-level chain.

The 256x256 `logo` example has 90,112 video bytes (11 pages, 64x352 upload),
CBP=336 and mip TBPs 0, 256, 320, 340, 344, 345. Warmup `slv`/`pnt` use this
same observed size/layout class; `top` uses the 512x256 class.

By contrast, the preview `seluh021.iff` `unif` has 132,096 video bytes:
one linear 512x256 indexed image plus a 1,024-byte palette, with no addressed
lower mips. The game and preview therefore need separate native edit intents.

### Why earlier attempts failed

Reading the bytes at `system + CBP*256` as an ordinary palette reads **upload
ordering**, not the intended GS palette. Likewise, a single familiar image
unswizzle cannot reconstruct both the GS32 upload and the subsequent GS8 read.
Assuming nearly every palette alpha must be 128 is also invalid; the verified
jersey palette contains other alpha values.

The new decoder composes both hardware address mappings and the CLUT mapping.
It never uses visual similarity or regenerates a mip to claim an exact match.
The previously generated workspace children match pixels **already stored on
disc**, including lower-resolution mips and full-resolution copies.

## Rendering structure: what is established

Shared `hi_body` and `low_body` SCNEs exist in `frontend.iff` and
`gamedataextra.iff`, with other game-mode copies also visible in the catalogue.
The inspected high-body scene has 80 materials; the low-body scene has 59.
Both have zero embedded texture descriptors/video bytes, and the inspected
material texture-reference fields are zero on disc.

Material names include `uniform`, `m_uniform_uneck`, `shorts`, `shorts_shadow`,
`pants`, `jacket`, `sleeve`, `full_collar`, `name_mat`, `back_number` and several
chest/shorts-number variants. This supports a shared-mesh, runtime-bound material
path rather than a separate complete textured body in every team's archive.
Geometry LOD (`hi_body`/`low_body`) and texture mip level are separate concepts.

The representative clothing TEX0 uses TFX=MODULATE and TCC=RGBA. If used unchanged
at draw time, texture values combine with the incoming vertex colour/alpha.
This does not establish final lighting, blending or opacity by itself.
Separate name/number materials and native `names`/`numbers` resources must not be
silently treated as jersey pixels; their generation remains a separate trace.

Not yet established: the exact binding function, draw-time TEX1/clamp/blending
state, filtering/LOD thresholds, full UV/VIF stream interpretation, or all
`UnAD/unidata` fields. The inspected uniform attributes are 80-byte objects, but
their integer fields are not assigned speculative meanings.

## Reproduce the investigation

```powershell
python scripts\inspect_uniform_iso.py --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --out cache\texture_iso\uniform-storage-verified --all-assets
```

Choose a new output directory when rerunning. The source must have the verified
pristine Europe fingerprint. The default scope is named uniform bundles;
`--all-assets` also finds packed artwork under other archive names.
The script uses the milestone-one database/snapshot and verifies matching PNGs
against the **current original dump files**, never artist/replacement images.

Outputs include `summary.json`, `resources.csv`, `images.csv`,
`active_matches.csv`, `uniform_coverage.csv`, `body_materials.csv` and
`native_uniform_mips.png`. The sheet shows original native RGB for visibility;
the exact comparisons also include alpha. GS pointer values in reports are
addresses within the upload's GS layout, **not writable ISO offsets**.

The full packed-resource pass examined 2,576 descriptors, decoded 2,568 and
explicitly rejected eight whose dimensions differ from TEX0. Of 14,577 decoded
images, 3,152 have matches in the original-dump snapshot, covering 1,875 unique
keys. Lack of a dump for another image is not independent validation of it.

Of the old active blockers, 875 keys now have exact native content matches:
834 uniform targets, 38 logo variants, one scene/atlas edit and two falsely
classified portrait inputs. The latter actually match `s009.iff` materials
`sts_2`/`sts_4`; **they remain portrait-ownership conflicts**, not valid headshot
patch targets. Content identification is not approval to edit every alias.

The subsequent [logo investigation](./LogoISOFormat.md) accounts for all 90
historical blocked logo variants, including the remaining 52 through isolated
scene uploads. It records full mip chains and material/mesh-part consumers;
the packed-resource totals above remain the original investigation snapshot.

The old milestone-one audit remains frozen. This investigation adds source
evidence; it does not mark encoding, palette quantization, recompression,
capacity/relocation, preview/game parity or ISO publication complete.

Hardware-address cross-check:
[PCSX2 GS format tables](https://github.com/PCSX2/pcsx2/blob/master/pcsx2/GS/GSTables.cpp).
The decoder implements bit-address equations independently, validated by synthetic
address/permutation tests and exact original-dump comparisons.
