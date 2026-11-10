# Roster payload format (NBA 2K5 PS2, `BESLES-53022Roster1`)

The roster file on the memory card is an uncompressed **heap snapshot** (size `0xB1040`, CRC32 stored
in the `EXTRA` blob). After loading, payload offset `X` lives at PS2 RAM `0xA95B80 + X`
(the loader rewrites the pointers to absolute addresses; the on-card form is self-relative).
Tooling: `scripts/mc_inspect.py` (extract), `scripts/mc_write.py` (write in place + ECC),
`scripts/build_roster.py` (build the ProA payload), `scripts/card_patch.py` (versioned `data/roster.bin` <-> card).

## Hex-editing workflow

`data/roster.bin` is the versioned payload (0xB1040 bytes). Edit it with a hex editor, then, with PCSX2 closed:

```
python scripts/card_patch.py              # roster.bin -> card: CRC32 into EXTRA, page ECC, timestamped card backup in data/roster_test/, verify + read-back
python scripts/card_patch.py --diff       # byte ranges that differ between roster.bin and the card, labelled player/team record + offset
python scripts/card_patch.py --pull       # card -> roster.bin (e.g. after the game saved a roster)
python scripts/card_patch.py --from-build # build_roster.py output (data/roster_build/payload_proa.bin) -> roster.bin
```
`--dry` checks without writing; the script refuses to write while PCSX2 runs (`--force` overrides). The size cannot change.
`git diff --stat data/roster.bin` / `--diff` show what an experiment changed; `git checkout data/roster.bin` reverts it.

## Pointers

Self-relative with a tag: `target = field_offset + signed_i32(value) - 1` (low bit set).
Always use signed `<i`. Only pointer fields below `POOL_MIN` (0x675DC) are rewritten; "pointers"
inside the string pool are false positives.

## College / FROM labels

Player `+0x00` is a tagged self-relative pointer to a **college row**, not directly
to text. Payload `+0x60` stores the row count (457), and `+0x64` points to the
table at `0x4F88`. Each row is 12 bytes: `+0x00` points to a NUL-terminated
UTF-16LE display string; `+0x04..+0x0B` is metadata preserved byte-for-byte.
The table ends at the main player-table base `0x64F4`.

Examples from the baseline: Iverson (record 0) points to college row 43 at
`0x5198`, whose text at `0x6A6CA` is Georgetown. Record 269 (Prince/Pildner)
points to Kentucky. Twenty auxiliary player templates follow the 792 main
records; all originally reference row 0, Albany State. Their row pointers
remain valid even when a row's label is replaced.

The builder checks the descriptor and all 812 player/template row pointers,
shares identical workbook College values, reuses existing matching labels, and
assigns other labels deterministically. All 457 rows may be repurposed:
**untouched NBA/legend/template college labels are not protected**. Other
untouched strings and all college-row metadata remain protected. Empty College
values get a valid shared empty-string row.

College strings use the same ref-counted best-fit allocator as names and arenas.
Only selected rows' strings are replaced initially. If that cannot fit, unused
college rows are also repointed to a shared empty string and their old strings
reclaimed; no dangling string pointers are left behind. The baseline college
strings occupy `0x6A300..0x6CC88` (10,632 B), potentially reclaimable subject to
other string owners. This is shared storage, not a separate fixed College budget.
The build report gives distinct labels, UTF-16 bytes including terminators,
remaining rows, reclaimed unused names, free bytes and largest free block,
plus extra bytes still reclaimable from unused college names.
Row exhaustion, byte exhaustion and fragmentation fail before publishing output
or writing a card. Strings are never truncated to force a build to fit.

Scraping expands raw NAT codes to English country names before applying manual
overrides. Actual college names in `data/overrides.csv` remain literal. Printable
BMP text is accepted; control characters, NULs and non-BMP characters are rejected.
Font coverage for non-ASCII text is independent of UTF-16 storage support.

## Historical player statistics

Verified against the original NBA payload, live player-card screenshots and
reversible RAM probes (all modified words independently checked after restoration):

- Player `+0x90` is a tagged, self-relative history pointer on card and an absolute
  pointer in RAM. Zero means no history.
- The baseline's 480 nonempty histories occupy exactly `0x26174..0x50DC4`
  (175,184 bytes), without gaps or shared streams. The other 312 player pointers
  are zero. This pool is independent of the string allocator.
- Payload `+0xA0` is the global count of four-byte entries (`0xAB14` in
  the baseline); `+0xA4` points to the pool base. Live relocation confirms these
  as the roster object's `+0x60/+0x64` count/base, used by the history mutation
  code at EE `0x237D98`. Repacking updates the entry count as well as every player
  pointer, leaves the fixed base unchanged and zeroes unused trailing capacity.
- An entry is little-endian `u16 value, u16 key`. `key & 0x7F` identifies a
  counting stat; bits 7 upward identify the season ordinal, oldest first,
  starting at 1. Bit 15 marks the final entry in the player's entire stream.
  Missing fields read as zero. Bit 14 is reserved by our encoder.

| Field | Value | Field | Value |
|---|---|---|---|
| 0 | GP | 9 | Offensive rebounds |
| 1 | GS | 10 | Defensive rebounds |
| 2 | Whole minutes | 11 | STL |
| 3 | FGM (including threes) | 12 | BLK |
| 4 | FGA (including threes) | 13 | Personal fouls |
| 5 | 3PM | 14 | AST |
| 6 | 3PA | 15 | TO |
| 7 | FTM | 16 | PTS |
| 8 | FTA | | |

The original streams also contain fields 17, 18 and 22 whose meanings are not
verified. Repacking preserves every byte of untouched players' histories,
including those fields. Reassigned ProA players receive only the verified fields.
The game derives averages, percentages, REB and career totals from counts.
For example, the original Tayshaun Prince/Pildner stream at payload `0x4E080`
has seasons of 137 points/42 games and 841 points/82 games: career 978 points,
124 games and 7.9 PPG. Changing `+0x41` from 1 to 2 exposes both rows without
changing the career total.

### Season labels and gaps

There is no explicit calendar year in a season entry. Player `+0x41` ("Years
Pro") controls the displayed ordinal span. Labels count backward from
`2004 + shared season offset`; the live Quick Game offset at EE `0x85FAF0` is 0.
An all-zero season (GP=0) is **omitted**, not printed with zero averages.
Its ordinal still preserves the correct labels of later seasons. A live probe
with offset 22 confirmed a 2026 label and safe omission of a gap season; it also
confirmed that career totals exclude that zeroed season. All probe bytes were restored,
and no card or save slot was written.

The player-card label calculation at EE `0x2F4E18` is
`addiu v1,s0,-2014` (`0x2603F822`). In the verified European `SLES_530.22`,
it maps to ISO offset `0x284F18`. Replacing only this instruction's immediate
with `-(anchor + 10)` shifts the label anchor; 2026 uses `0x2603F80C`.
This does not change birth dates or the global game calendar. The existing
shared offset still advances labels in season/franchise modes; those modes
have not been live-tested.

PCSX2's game CRC is the XOR of the ELF's 32-bit words, so a code change alone
would change `CA37B42E` to `CA37B400` and disconnect the existing texture/settings
folders. A second four-byte patch at ISO `0x900FC` compensates that XOR in verified,
nonloaded ELF header padding (after all six program headers, before the first
load segment). The original padding is zero; the 2026 compensation is `2E000000`.
The patcher checks the header, load-segment boundaries and zero padding before
using it. The game CRC remains `CA37B42E`. Algorithm reference:
[PCSX2 ElfObject::GetCRC](https://github.com/PCSX2/pcsx2/blob/master/pcsx2/Elfheader.cpp).

```powershell
python scripts\build_roster.py --stats data\proa_stats.json
python scripts\lettering_workspace.py check --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --stats-year 2026
python scripts\lettering_workspace.py build --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "<new ISO path>" --stats-year 2026
```

`build_roster.py` now reads schema-v2 `data/proa_stats.json` by default.
`--no-stats` explicitly retains the legacy inherited NBA histories.
Each history's season **start year** determines its label (2026/2027 displays
2026). The builder sets "Years Pro" to the contiguous span through that anchor,
not a birth-year estimate, and inserts GP=0 entries for missing seasons.
No-games players receive a null history pointer.
The game has no verified unknown-value representation: unavailable GS/FLS
fields are omitted, read as zero in game, and are reported explicitly rather
than fabricated as known zeroes in the scraped archive.
For inconsistent published rebound figures, OREB/DREB are preserved and their
sum is the in-game REB (user-selected policy). The archive retains the original
published REB as well and both archive/build reports expose the discrepancy.

The archive retains exact seconds and fractional total MIN. In the game,
season seconds round to the nearest whole minute, half up (at most 30 seconds
loss per season). UInt16 overflows, malformed pointers, unterminated streams,
unowned nonzero pool bytes and insufficient capacity fail before publishing a
payload. `stats_report.json` reports pool capacity and the required ISO anchor.
Without the matching ISO patch, the counts are correct but season labels still
use the original 2004 anchor. Boot a generated ISO fresh, not from a saved state.

## Tables

| Table | Offset | Stride | Count | Notes |
|---|---|---|---|---|
| Team records | `0x11F0` | `0x124` | 54 | see below |
| Player records | `0x64F4` | `0x94` | 792 (0x318) | 575 referenced by team rosters |
| String pool | `0x675DC` | - | - | UTF-16LE, NUL-terminated, packed, ends ~`0xA9240` |

Zero gap `0x6663C-0x675DC` (4001 B) is usable as extra pool space.
The game encodes an apostrophe as char `0x19`.

### Team record (0x124 bytes)
| Off | Meaning |
|---|---|
| +0x00..+0x38 | up to 15 pointers to player records (zero terminated, NBA teams hold 12-15) |
| +0x48 | nickname pointer |
| +0x4C | abbreviation pointer |
| +0x50 | `"NNN"` id string pointer |
| +0x74, +0x7C | city pointers |
| +0x90..+0xA0 | 5 starter pointers (PG, SG, SF, PF, C) |

Slots 0-29 are NBA teams (alphabetical by city/nickname, 0 = 76ers/PHI), 30-31 East/West,
32-49 all-star/legend teams, 50-53 Ballers/Ringers/dummies. ProA uses slots 12-29 (final mapping in
`data/team_slots.csv`: Dragons 12 ... Falcons 21 = Pistons, the default home team of Quick Match, Gottingen 15 = Lakers,
the default visitor); slots 0-11 stay NBA teams and donate players.
Team-name strings are also referenced by a nickname/`pbNN.iff` playbook pointer table at
`0x10E8-0x11E8`; `build_roster.py` rewrites **all referrers** of an old string.

### Team colours / jersey lettering investigation (2026-11-06)

Read-only comparison of the saved NBA baseline (`data/roster_test/payload_current.bin` and
the roster in `Mcd001.original.ps2`) with the edited `data/roster.bin` found two **RGB-like
triplets**, unchanged across all 30 NBA slots:

| Team-relative offset | Encoding candidate | Status |
|---|---|---|
| +0x62..+0x64 | three u8 channels, R/G/B | General team colour: armbands and some UI elements (user-tested) |
| +0x65..+0x67 | three u8 channels, R/G/B | Secondary UI colour, including backgrounds with white text (user-tested) |

These are six consecutive bytes, **not two aligned RGBA words**. Examples:

`build_roster.py` writes them from `team.colorui1` / `team.colorui2` in
`texture_workspace/team_palettes/<slot>/colours.json`. The independent
`team.colorjersey1` / `team.colorjersey2` settings retain
the old baseline jersey-generator colours. UI defaults were copied exactly, not
darkened: review bright secondary colours for white-text contrast.

| NBA slot / team | First triplet | Second triplet | Absolute payload offsets |
|---|---|---|---|
| 0 / 76ers | `94 0B 2E` (#940B2E, dark red) | `14 14 14` (#141414, near-black) | 0x1252 / 0x1255 |
| 20 / Pacers | `2A 32 5A` (#2A325A, dark blue) | `2D 3D 6E` (#2D3D6E, dark blue) | 0x2922 / 0x2925 |
| 6 / Celtics | #006A3C (green) | #141414 | 0x192A / 0x192D |
| 15 / Lakers | #F5CC08 (yellow) | #7E2C9D (purple) | 0x236E / 0x2371 |
| 25 / Spurs | #141414 | #9C9C9C (grey) | 0x2ED6 / 0x2ED9 |

The colours broadly track NBA team palettes. However, the Pacers have **no yellow in
either triplet**, whereas their away lettering is observed as yellow. Thus these fields
cannot be labelled "home lettering" and "away lettering"; the tests below establish
accessory/UI uses, not lettering controls.
No fill/outline selector or outline colour has been confirmed. Interpreting other
team words as RGB555/RGB565 produces occasional plausible colours but no established mapping.

Re-run the read-only scan:

```
python scripts/team_colour_scan.py
python scripts/team_colour_scan.py --payload data/roster_test/payload_current.bin --slot 20
```

Name and number text comes from player-record fields, not the borrowed model ID (see
`player_record_layout.md`). Custom text working does not rule out glyph atlases or
dynamically assembled textures: existing dumps include `jersey_name_plates` and
`jersey_numbers` groups. Lettering colour may be in a texture palette or uniform asset
instead of the roster.

**User test results (2026-11-06):** changing the first Sixers triplet at 0x1252 to
`00 FF 00` turned armbands and some UI elements green. Changing the second at 0x1255
to `FF 00 FF` produced limited magenta, notably in secondary UI elements combined
with white text. Keep the second colour dark enough for white-text contrast; bright
magenta is a diagnostic value, not a suitable final palette. No jersey-lettering change
was reported. Exact coverage of both fields across screens/accessories remains untested.

**Long-term constraint (user, 2026-11-06):** no manual replacements for each new player.
The desired control is roster-driven; a shared team/uniform template or palette would
also be worth investigating if it automatically applies to future names and numbers.
If no maintainable shared control is found, leave lettering colours unchanged.

The existing workspace contains 2,651 number dumps across four resolutions and 2,262
name-strip dumps across three resolutions. Sample number images contain assembled
`11` and `22`, not full digit atlases; a sample name strip contains `JOHNSON`.
Only 140 number dumps and 956 name-strip dumps have entirely greyscale visible RGB
pixels (alpha > 0). Thus many output textures already contain colour, although this
does not establish where the generator obtains it. No filename-labelled font/palette/
glyph template was found; initial grouping may have put such assets elsewhere.

**Next test: find the shared input to lettering generation.** A one-off replacement
test below is diagnostic only, not the proposed production workflow.

1. Restore the diagnostic team colours. Use Pacers home/away as the control pair
   (blue/yellow lettering), holding player identity and jersey number constant.
2. Find the matching glyph/number and name-strip dumps in
   `texture_workspace/jersey_numbers/` and `texture_workspace/jersey_name_plates/`.
   If ambiguous, capture fresh dumps during a close-up and compare newly created
   or changed textures between variants.
3. Recolour one candidate's opaque fill pixels to green, preserving its alpha and
   outline pixels. Sync using `texture_workspace.py sync`, then reload textures with
   F10 while unpaused. Check whether numbers/names change and whether this affects
   only one uniform or other teams too. Restore after each individual test.
4. If fill changes directly, map the texture keys and isolate the outline separately.
   If a confirmed visible glyph texture contains only white/greyscale coverage, investigate
   uniform material/vertex tinting. Read the loaded TXTR palette first: colour can be baked
   into a generated palette even when a source atlas is monochrome. A replacement having
   no effect alone does not prove tinting; it may be the wrong key or inactive LOD.

Prefer tracing the loaded number/name-strip TXTR back to its uniform asset and
generation inputs. Search for a reusable digit/alphabet atlas, a fill/outline palette,
or a per-uniform style structure. Compare Pacers home and away inputs while keeping
the player constant. A colour-template texture could encode fill/outline colours,
but a palette table or material fields could do the same without appearing as a dump.
Confirm a candidate by changing one shared input and then generating lettering for
at least two players with different names/numbers. Both must inherit the change;
editing already assembled player textures does not satisfy the long-term requirement.

**Follow-up pointer audit:** the 30 NBA team records' consistent tagged pointers
resolve to player records (+0x00..0x38 and +0x90..0xA0), name/abbreviation/id strings
(+0x48, +0x4C, +0x50, +0x74, +0x78, +0x7C), the playbook table (+0x54), and the
venue table (+0x58). No direct texture/palette pointer was identified. Small integer
fields also accidentally pass the tagged-pointer range test; that alone is not evidence
of a pointer. +0x68..0x6F are zero across these teams; +0x84/+0x8C are invariant
floats 1.0/0.4; +0x80 ranges 0..5 and +0x88 ranges 0..4 (+0x89 is always 2).
The small fields might be enums/selectors but their purpose is unknown.
The later +0xE4..0x100 words have not been semantically decoded; interpreting them
as packed colours is possible but has not yielded a convincing uniform-colour mapping.
A readable UTF-16 asset-name scan found playbook `.iff` references, not explicit
uniform/font/palette asset names. This does not exclude numeric asset identifiers or
tables elsewhere in the payload, nor assets loaded outside the roster.

The assistant's initial scan was read-only; the colour edits above were performed and
reported by the user.

#### Live experiment: shared digit atlases found (2026-11-06)

User supplied savestate slot 1: Pacers vs Pacers at team select. The savestate contains
NBA player names despite active ProA texture replacements. No memory card, roster file,
replacement texture, or saved state was written during this experiment.

Four **`numbers` TXTRs, 1024x64**, contain complete digit strips 0..9 with baked fill,
outlines and antialiasing. They belong to preview uniform assets, not individual players:

| Preview asset | Numbers TXTR | Pixels | Palette / CLUT |
|---|---|---|---|
| `seluh021.iff` (Pistons home) | 0xFB4B80 | 0xFB4BF0 | 0xFCA140 |
| `selua021.iff` (Pistons away) | 0x1034B80 | 0x1034BF0 | 0x104A140 |
| `selua020.iff` (Pacers away) | 0x10B4B80 | 0x10B4BF0 | 0x10CA140 |
| `seluh020.iff` (Pacers home) | 0x1134B80 | 0x1134BF0 | 0x114A140 |

Preview ownership was resolved from each UTF-16 file-name address: words at +0x68/+0x6C
give the asset allocation range containing the numbers TXTR. These offsets are observations
for this preview layout, not a general `.iff` parser.

**Decoding correction:** these indexed PSMT8 textures include seven mip levels before
the CSM1-swizzled, 256-entry RGBA palette. Each mip's byte count is rounded up to 16 bytes.
Thus CLUT = pixel + 0x15550 for 1024x64, or pixel + 0x2AC0 for 128x64 / 256x32.
Assuming CLUT follows only the first mip produces misleading colours/empty images.
The decoded Pacers home atlas has blue fill/yellow outline, and away has yellow fill/
blue outline. The generated preview `15` decodes with the matching style.

After game load, buffers `jerseyname00..23` (256x32) and `jerseynum00..23` (128x64)
exist. All 12 home number buffers have a palette **byte-identical (all 1024 bytes)**
to the preview home atlas palette; all 12 away buffers match the away atlas palette.
Name palettes likewise form two groups of 12 identical palettes, but are not identical
to either number palette. Decoded name samples contain `O'NEAL`.
The game has loaded `uh020.iff` and `ua020.iff`; source `numbers` TXTRs from preview
are no longer present as valid named objects in the game snapshot.

**Controlled RAM-only test:** recoloured every non-transparent entry of the preview
home atlas CLUT at 0x114A140 green, without touching assembled number buffers.
After resuming team select, the cached preview number palette did not inherit the edit.
After starting a fresh game, sampled generated home number palettes were restored to
the original palette, not green. Therefore patching this preview atlas alone is **not**
a persistent game-lettering solution. The test does not rule out the separate game
uniform atlas as the real shared generation input.

Next target: generation-time data from `uh020.iff` / `ua020.iff`, including the name
glyph source. A patch to those source assets or their load/generation routine could
apply to future players; ordinary PCSX2 replacement of a CPU-read source atlas cannot
be assumed to affect generated output. No roster-controlled lettering setting is proven.

Reproducible offline inspection:

```
python scripts/inspect_lettering.py snapshot.bin --out OUTPUT_DIRECTORY
```

Exports decoded images and `lettering.json` with addresses, preview asset ownership and
full palette hashes. Addresses above are EE RAM offsets specific to this run, **not**
roster offsets or stable addresses for a future session.

### ISO experiment: shared number source confirmed

The supplied `ESPN NBA 2K5 (Europe) - Kopie.iso` was patched and **fresh-booted**,
without loading a savestate. This establishes a working alternative to per-player
PCSX2 texture replacements: change the uniform's shared number palette on disc, and
the game copies it into every generated player-number texture.

The experiment used an isolated PCSX2 data directory, both memory-card slots disabled,
and texture replacement/dumping disabled. The normal profile, memory cards and slot 1
savestate were not used or overwritten.

#### Archive and source-texture offsets

These are **ISO byte offsets**, not roster/EE addresses, for the verified
3,439,427,584-byte European image:

| Location | Value / interpretation |
|---|---|
| ISO9660 sector size | `0x800` bytes |
| `VC_53022` archive | Four physically contiguous files `0` through `3`; first three are 1 GiB |
| Archive start | LBA 4895 = `0x98F800` |
| Archive entry count | `3728`, u32 at archive start |
| Index start / stride | archive `+0x9C` / `0x0C` |
| Index entry fields | u32 hash, u32 byte length, u32 sector offset relative to archive start |
| Tested uniform bundle | index 2103 (zero-based), hash `0xAD6241D2` |
| Bundle start / length | `0x0DF07800` / `0xB5630` |
| Shared alphabet chunk | `0x0DF2BFA0`, `HITX`, name `names`, 1024 x 32 |
| Alphabet CLUT | `0x0DF36AD0` (last 1024 bytes of this chunk) |
| Shared digit chunk | `0x0DF36F90`, `HITX`, name `numbers`, 1024 x 64 |
| Digit base-mip indices | `0x0DF37020` (chunk `+0x90`) |
| **Patched digit CLUT** | **`0x0DF4C570`, 1024 bytes** |

Bundle chunks advance by `0x20 + u32(chunk+4)`. Some `TXTR` chunks are compressed;
the lettering `HITX` chunks above are not. `HITX` dimensions are u16 at `+0x7C` /
`+0x7E`; the UTF-16 name begins at `+0x40`. Each atlas is followed by a `NAME` chunk
containing glyph-position/width data. The alphabet and digit outlines are baked into
their indexed images/palettes, not independent RGB fields in the roster.

For these two source chunks, the CLUT is the final 1024 bytes of the chunk. Do not
blindly reuse the RAM exporter's seven-mip calculation for the 1024 x 32 alphabet:
that would put its CLUT 16 bytes too late.

The digit indices and entire original palette match the earlier Pacers home RAM
atlas byte-for-byte. The archive's filename hash algorithm has **not** been decoded;
the bundle's literal filename is not yet established. Its role as the in-game Pacers
home number source is established by the controlled patch, not a guessed filename.
Two away-palette matches also exist at `0x122DED70` and `0x143B0D70`; neither was patched.

#### Patch and verified result

[patch_lettering_iso.py](../scripts/patch_lettering_iso.py) changes only the
blue-dominant, nontransparent palette entries to diagnostic bright green. Specifically:
`alpha != 0`, `B > R+12`, `B > G+8`; replace RGB with `00 FF 00`.
It leaves alpha, transparent entries, yellow/neutral palette entries, indices, glyph
metrics and all file sizes unchanged. This is a diagnostic colour selection, not a
production-quality antialiased recolouring algorithm.

* **94 palette entries / 282 RGB bytes** changed, all within the single CLUT.
* The expected full-image SHA-256 was calculated from the original copy with only
  that replacement, then matched against the entire patched ISO.
* Fresh Pacers versus Pacers game: all **12** home `jerseynum00..11` CLUTs match
  the patched source exactly.
* All **12** away-number CLUTs and **24** home/away name CLUTs match the unpatched
  game's snapshot.
* All **48** base-mip index buffers and alpha arrays remain byte-identical.
* Decoded player-number images show green numbers with the yellow outline retained.
* On-court visual check at tip-off: the white home jerseys display green numbers
  (including `10`, `1` and `7`); the blue away jerseys retain yellow numbers. Name
  lettering remains unchanged.
* The team-select jersey preview did **not** visibly turn green. That presentation
  must not be used as the test for the in-game generation source.

| Fingerprint | SHA-256 |
|---|---|
| Original source number CLUT | `308eb4ba3724e3599eeb60ac52cb8ffdcc82191c5c83afdfa1cab97f2e0a2397` |
| Patched source / generated home number CLUT | `c89020f9439f5273b525148652c06be9d9f35ac3983fb45e7893c535422e96f0` |
| First, damaged ISO copy before patch | `96fc033cd3298145fad05901257be9a2000e3ad181c68db52c9af0fd3c09e5f5` |
| First, damaged ISO copy after patch | `3638b9f12fb2b947f66d60d989c58a8f45b153cdd657f8c6504c56e531f02fc7` |

The other ISO in that directory already differed from the supplied copy near the
end of the image **before** this experiment; it was not used as an identical baseline
and was never written.

#### Follow-up: blank warm-ups and intermittent stalls

The user observed completely white/blank player warm-ups and occasional multi-second
hangs during the test. The captured pregame scene also shows blank white warm-ups.
These are tracked observations, **not established side effects of the palette patch**.
The experiment proves number-colour propagation, not general gameplay stability.

A subsequent read-only check identified a serious pre-existing baseline problem:

* From ISO offset `0xC7700000` to EOF, the supplied copy contains **93,421,568 zero
  bytes** (about 89.1 MiB), with no nonzero bytes anywhere in that range.
* The archive index references **306 assets overlapping this range**, beginning
  with entry 3422 at `0xC7663000` (partially affected). This is not solely ISO padding.
* At the same offset, a 1 MiB sample of the other ISO contains nonzero data. The
  pre-patch whole-image comparison already established the difference, before the
  palette write. Our palette modification at `0x0DF4C570` cannot account for it.

This is consistent with an incomplete/damaged supplied copy and is a plausible
confound for missing assets or stalls. It does **not** yet identify which affected
asset is a warm-up texture or prove the cause of either observed symptom.
The isolated profile also differs from the normal profile and uses a separate shader
cache. Its log contains no explicit disc-read failure establishing a cause.

The required follow-up was to recreate a disposable copy, verify identical complete
hashes, then compare unpatched and patched fresh boots under the **same** emulator
profile, renderer and texture-replacement settings. That comparison is recorded below.

#### Intact-copy A/B retest (2026-11-06)

After the user recreated the copy, both ISOs were independently confirmed to have
SHA-256 `4cdad2339dbe2828b440ca222f869f234b15c0321c8dcdeac016a30b10678fb7`.
The original ISO was not modified.

Two fresh boots of the copy were tested in order: unpatched, then patched. Both used
the same isolated PCSX2 2.8.2 profile, Direct3D 12 at native 640 x 512, normal 100%
speed, Pacers versus Pacers with current home/away uniforms, disabled memory-card
slots, and disabled texture replacement/dumping. The profile's four shader/pipeline
cache files were saved before the baseline and restored to that same seed before the
patched boot. A dedicated PINE port (28012) avoided the earlier socket conflict.

| Check | Intact unpatched copy | Intact patched copy |
|---|---|---|
| Warm-ups | Properly textured, with Pacers logos | Properly textured, with Pacers logos; home white/blue/yellow panels and away blue |
| Home jersey numbers | Original navy/yellow | Diagnostic green/yellow |
| Away numbers / player names | Original | Unchanged |
| Sampled gameplay window | 30.28 s, 119 samples | 30.17 s, 118 samples |
| Identical consecutive game-image samples during gameplay | None | None |
| Additional sampled pregame window | 35.16 s, 140 samples | 35.17 s, 138 samples |

Screen sampling hashed only the game image, excluding window/menu/status bars, at
approximately 4 Hz; the largest interval between samples across both runs was 0.344 s.
The baseline pregame sample's longest identical-image run was 0.25 s. The patched
pregame sample contained a **2.25 s** stationary interval on the black
`Pacers vs Pacers` loading/transition screen, followed by normally animated scenes.
The pregame windows began at different points in the sequence, so these numbers are
**not** a matched loading-time benchmark or evidence of a patch-specific loading stall.
No deliberate emulator pauses were used during the sampled windows.

Final RAM snapshots, taken after generation had completed, establish:

* All **12 home-number palettes** equal the original palette with precisely the
  diagnostic `green_fill` transform.
* All **12 away-number** and **24 name** palettes match the intact baseline.
* All **48** alpha arrays and base-mip index buffers match the intact baseline.

The intact copy's patched SHA-256 is
`ce8c037aeaff00735fe94478821c2b71d0a36827f58648dd530fbc080ad82adf`.
It was checked against a complete expected-image hash computed by substituting only
the known palette into the unpatched byte stream: **282 changed RGB bytes**, with no
other byte changes. Neither run's log reported an explicit disc-read/asset error.

**Conclusion:** blank warm-ups are not reproduced with the intact image, either
unpatched or patched. The missing tail in the first copy remains the best-supported
explanation, although individual affected asset hashes have not been mapped to warm-up
textures. No gameplay freeze was detected in the short sampled windows. The stationary
loading transition is recorded, and intermittent stalls remain a longer-run observation
item rather than a proven palette-patch regression or a conclusively resolved issue.
The isolated test processes were closed; the supplied copy remains patched, with its
palette restore manifest beside it. Normal memory cards and savestates were untouched.

#### Shared alphabet patch: toolchain verified

`patch_lettering_iso.py --target names` now applies the same reversible diagnostic
palette edit to the Pacers home alphabet chunk. Default operation still targets
numbers. The alphabet source CLUT is at `0x0DF36AD0`; its original SHA-256 is
`36acca4d2c21626095a2a6a03c395ae0aa65cb88c89bb18d21c260ccf88bfe7f`.

The blue-dominant-entry transform changes **9 entries / 27 RGB bytes** in the source
alphabet, producing SHA-256
`b880f9caf5c70254a1ee0a63c3a6ad0f1c66d6e6c212bfd915a3dd3ad83828b3`.
These glyphs contain mostly gold/brown tones, so this diagnostic changes only blue
accents, not the whole visible fill. No cosmetic result is required: the purpose of
this test is to establish that edits to the shared source reach generated names.

A fresh Pacers-versus-Pacers boot with both patches established:

* All **12 home-name palettes** changed to generated SHA-256
  `befd39783c56ef686b55f1ad9d7e8a8e3b892d4a486fa43e1e91d913d6916864`.
  Decoded glyph images contain the changed green accents for every home player.
* All **12 away-name palettes** match the intact baseline.
* All **24 number palettes** match the preceding successful numbers-only test.
* All **48** base-mip index buffers and palette alpha arrays remain unchanged.

Generated name palettes are processed output, not byte-for-byte copies of the alphabet
CLUT. Validation therefore compared final generated glyphs/palettes against the clean
baseline rather than expecting the source CLUT hash in player textures.

The copy carrying **both** patches has SHA-256
`2513e06df91ae74657cb01a7c56e8d53c9203ba407c545c6869e98f4d90708fd`.
Its full hash was checked against the numbers-patched image with exactly the additional
27-byte name edit. Both targets have independent manifests and can be restored without
undoing the other. The source ISO, normal memory cards and savestates were not written.
An actual name-only restore returned the complete image to the earlier numbers-only
hash `ce8c037aeaff00735fe94478821c2b71d0a36827f58648dd530fbc080ad82adf`;
reapplying names reproduced the combined hash above.

#### Team-select preview source and all-30-slot inventory (2026-11-07)

The preview number is **not baked into the full jersey texture**. A fresh team-select
GS dump contains four frames of draw/transfer evidence:

* Left/Lakers number: PSMT8 128 x 64, TEX0 `8006b6059d30b580`, TBP 13696,
  CBP 13744. The 1024-byte CLUT upload exactly matches RAM `jerseynum01` at
  `0xC31C70` (and the loaded `selua015.iff` number palette).
* Right/Pistons number: PSMT8 128 x 64, TEX0 `80070a059d30b820`, TBP 14368,
  CBP 14416. The CLUT upload exactly matches RAM `jerseynum00` at `0xC2ECF0`.
* These palettes are uploaded in every captured frame. A RAM-only edit to all
  nontransparent entries makes the visible left/right numbers magenta/green,
  without changing jersey artwork or indices. Both palettes were restored and
  read back immediately. Addresses are specific to this process.

The archive filename hash is now established: **CRC32 of uppercase UTF-16LE,
without a trailing null** (`zlib.crc32(name.upper().encode("utf-16le"))`).
Examples verified against runtime file-request records and archive entries:

| Filename | Hash | Entry |
|---|---|---|
| `seluh020.iff` | `0F1821E5` | 178 |
| `selua015.iff` | `43D4368F` | 110 |
| `uh020.iff` | `AD6241D2` | 2103 |
| `ua020.iff` | `70194F0C` | 2211 |

Pacers home preview entry 178 begins at ISO `0x203D800`, length `0x188D0`.
Its first `TXTR` has stored body length `0x3390`, system/video sizes
`0x70` / `0x15950`, sentinel `FEEDBEEF`, and 128 scratch bytes.
The body starts at `0x203D820`; its VC-LZ header declares `0x159C0` decoded
bytes, stream tag `0x5C`, and 10 distance bits. The decoded digit indices and
original palette match the loaded Pacers home atlas exactly. The palette is
the final 1024 decoded bytes, not a directly writable 1024-byte ISO window.

`scripts/vc_lz.py` decodes bounded streams and rebuilds only the edited tail,
retaining earlier tokens. Recompression must fit the original stored span and
the existing in-place loader scratch allowance; a separate-buffer round trip
alone is insufficient. Match tokens copy backwards, including reads of unwritten
zero bytes on overlap. The format was cross-checked with
[the independent NFL 2K5 VC-LZ investigation](https://github.com/cruuz/2k-football-mod-tools/blob/main/tools/nfl_txtr.py)
and then verified against this game's RAM and all 79 preview/game palette pairs.

`scripts/patch_preview_lettering_iso.py` accepts only the pristine Europe hash
`4cdad2339dbe2828b440ca222f869f234b15c0321c8dcdeac016a30b10678fb7`.
Inspection is read-only; `--out` creates a **new** output, verifies the complete
expected output hash and unchanged bytes elsewhere, and publishes after read-back.
Existing outputs, source-as-output and non-pristine sources are refused. Its
manifest is `<output>.preview-lettering-test.json`; the source remains the restore
copy. `--with-game-test` composes the earlier court number/name diagnostics.

```powershell
python scripts\patch_preview_lettering_iso.py "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso"
python scripts\patch_preview_lettering_iso.py "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --out "C:\Tools\isos\ESPN NBA 2K5 (Europe) - Preview Test.iso" --with-game-test
python scripts\inventory_lettering_iso.py "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --out data\texture_map\lettering_sources.csv
```

Fresh-boot verification used isolated PCSX2 2.8.2 at native resolution/normal
speed, both memory-card slots disabled, no texture replacements/dumping:

* Pacers versus Pacers team select: home `15` visibly green with original
  outline; away `15` unchanged. Home generated preview palette equals
  `c89020f9439f5273b525148652c06be9d9f35ac3983fb45e7893c535422e96f0`.
* After a real game start, all 12 home-number palettes equal that same hash;
  all 12 home-name palettes equal the previously verified generated diagnostic
  `befd39783c56ef686b55f1ad9d7e8a8e3b892d4a486fa43e1e91d913d6916864`.
* A second fresh boot of the pristine ISO with the same isolated profile supplies
  the matched baseline. Both rendered preview-number buffers and all 48 generated
  court textures retain every pixel index at all seven mip levels and every alpha
  byte. Only the home preview-number palette and 24 home court palettes change;
  the away preview and all 24 away court palettes match the baseline exactly.
  Thirty-six unused mip-alignment padding bytes differ between the court snapshots;
  they are not mip pixels. Source resource padding remains byte-identical.
* Full combined output hash:
  `72fd84ea17cdddee69d99839bcb59659ca42d66c9a2083c0bc10a0e554a28eb7`.
  Source descriptors, all mip/index bytes and palette alpha are unchanged by
  the verified decode/rebuild; only preview RGB and the two earlier court
  diagnostic palettes change.

The tracked inventory contains **30 NBA slots, 79 uniforms, 237 sources**:
home/away for every slot plus 19 paired `uxNNN.iff` / `seluxNNN.iff` alternates.
Each uniform has game names, game numbers and preview numbers. All game/preview
number palettes match exactly. Seventeen number atlases are 512 x 64, the other
62 are 1024 x 64; all alphabet atlases are 1024 x 32. Metadata includes entry/chunk
identity, stored/decoded offsets, compression, scratch and immutable-data hashes;
it contains no extracted artwork or palette bytes. Broader uniform/surface
visual acceptance remains future work. The editable all-30-slot workspace and
opt-in season stage are implemented; see the
[workspace commands](JerseyTextureWorkflow.md#b-dedicated-editable-palette-workspace).

Team select also preallocates player `jerseyname02..23` / `jerseynum02..23`
objects with null pixel pointers. `inspect_lettering.py` now explicitly reports
and skips these uninitialized buffers; nonzero invalid pointers still fail.

#### Repeat / restore

Stop emulation of this image before writing it. Always operate on a disposable copy:

```powershell
# Read-only inspection of an unpatched copy (the default).
python scripts\patch_lettering_iso.py "C:\Tools\isos\ESPN NBA 2K5 (Europe) - Kopie.iso"
# Apply the diagnostic patch.
python scripts\patch_lettering_iso.py "C:\Tools\isos\ESPN NBA 2K5 (Europe) - Kopie.iso" --apply
# Restore the exact original palette.
python scripts\patch_lettering_iso.py "C:\Tools\isos\ESPN NBA 2K5 (Europe) - Kopie.iso" --restore
# Independently apply or restore the shared alphabet palette.
python scripts\patch_lettering_iso.py "C:\Tools\isos\ESPN NBA 2K5 (Europe) - Kopie.iso" --target names --apply
python scripts\patch_lettering_iso.py "C:\Tools\isos\ESPN NBA 2K5 (Europe) - Kopie.iso" --target names --restore
```

The number restore manifest is written beside the ISO as `<ISO filename>.lettering-test.json`;
names use `<ISO filename>.lettering-names-test.json`. Each is written **before** its
palette is patched. Keep both with the test copy. Operations verify the ISO layout,
bundle index, source chunk and palette fingerprints and read back the write. Applying
twice, using an unknown palette, or restoring over unrelated palette edits is refused.
An already-restored palette is left untouched. Apply/restore and rejection paths were
also tested on a disposable sparse fixture.

**Long-term implication:** no player-specific edits are needed for either tested shared
source. Uniform-level ISO palette edits propagate to generated names and numbers.
Home/away and alternate source mapping for all 30 slots and the Pacers home preview
are now resolved. `lettering_workspace.py` provides `export`, `check`, `build`
and explicit per-slot `reset`; `update_season.py` provides opt-in ISO preflight and
build stages. Each uniform now has `colours.json`: monochrome fill, generic
three-reference outlined recolouring, or legacy palette mode. Reference weights
are derived from the pristine source, not hand-tuned per uniform or refitted against
new colours. Monochrome covers every nonzero-alpha entry, including those used only
by lower mips; source alphabet atlases have six mip levels and number atlases seven.
Black/white/green monochrome passed all 711 source/preset checks and all compressed
preview spans; a real controls-driven build verified all 237 sources.
An all-slot diagnostic build verified all 237 edited sources, including
home/away/alternate and both number-atlas widths: RGB matched the edited swatches,
descriptors/indices/mips and alpha stayed byte-identical, and full-image hashing
verified unchanged bytes outside the patch spans. This is data-level coverage, not
an in-emulator visual test of every uniform. The original ISO and editable user
workspace were left unchanged. Fixed-span compression can reject some RGB edits;
see the [workspace workflow and limits](JerseyTextureWorkflow.md#5-shared-lettering-and-team-select-preview-plan).
No ISO, extracted game texture or emulator RAM dump belongs in Git.

### Player record (0x94 bytes)
| Off | Meaning |
|---|---|
| +0x0C | last-name pointer |
| +0x10 | first-name pointer |
| +0x18 | nickname pointer |
| +0x1C | birthday pointer |
| rest | ratings, position, jersey, size ... **not decoded yet** |

Record 0 = Iverson, 3 = K. Thomas, 100 = Gasol.

### Venue (arena) table

70 records of `0x30` bytes starting with the first name pointer at `0xC8` (`row k` = `0xC8 + 0x30*k`). All fields are
string pointers in the usual tagged form:

| Off | Meaning |
|---|---|
| +0x00 | arena name, e.g. `Palace of Auburn Hills` (this is what the pre-game banner shows) |
| +0x08 | venue city, e.g. `Auburn Hills` |
| +0x0C | `"sNNN"` string: NNN = **NBA team slot** the venue belongs to (`s021` = Pistons) |
| +0x10 | abbreviation |

Row order is **not** slot order (row 28 = `s029`, row 1 = `s028`, rows 30+ are All-Star, legend and street venues),
so always resolve the row by its `sNNN` string. Different teams may share one arena string (Staples Center: Clippers
`s006` and Lakers `s015`); rewrite single fields, not all referrers.
The game uses the heap copy of the payload (RAM `0xA95B80 + file offset`); a second copy of the name in RAM
(e.g. `0x1CE8638`) is irrelevant. Names may be longer than the original (string is relocated).
`build_roster.py` reads `arena,verified` alongside the team names and colours in
`data/proa_teams.csv` and writes `data/roster_build/arena_map.csv`. `verified` describes
the arena name only. The separate arena CSV and `--arenas` argument were removed.
Live tools: `scripts/arena_table.py` (list rows from RAM), `scripts/ram_write_str.py` (in-place patch, max original length),
`scripts/find_ps2_ram.py` (re-find RAM base after every PCSX2 restart).

## String pool handling (build_roster.py)

Best-fit allocator over the pool plus free gap. Strings are ref-counted through a map of referrers;
freed strings are zeroed and merged. Replacement strings **may be longer than the original** (verified
in-game, experiment E1) because the string is relocated and the pointer rewritten.

## Display limits

* Lineup caption shows `F. Lastname`, ellipsis at ~11-12 characters; the scraper limits each name to 12 characters.
* The scraper transliterates umlauts (ae/oe/ue/ss) and other accented letters before generating the workbook. Persistent preferred names go in ID-keyed `data/overrides.csv`; they must already fit the ASCII/12-character constraints. The builder validates names without renaming them again, and `player_map.csv` contains only the final `first,last` names (no redundant `orig_first,orig_last`).

## Verified

* Card roster built by `build_roster.py` (18 ProA teams, 269 players) loads in-game and plays:
  scoreboard shows the new abbreviations (HAG, TUE), on-court captions and jerseys show ProA names.
* ECC verify of the written card equals the original (4577 ok, 1 pre-existing bad page); CRC32 is
  always recomputed.

## Not changed by build_roster.py (yet)

Jersey numbers, positions, ratings, birthdays, nicknames, textures, NBA slots 0-11 (still NBA
teams), all-star/legend teams referencing NBA player records.
