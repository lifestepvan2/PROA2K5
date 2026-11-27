# Approved created-player low-detail hair

These are the fixed native VIF streams and executable selector approved in
PCSX2 on 2026-11-27. `manifest.json` identifies the reviewed ISO, source head,
stream hashes and renderer budgets. Normal builds verify every binary before
using it; `--basic-meshes` bypasses this set entirely.

- Custom styles: 2, 5, 10, 11, 13, 16, 18, 19, 21, 22, 23.
- Stock geometry reused at runtime: short for 1, afro for 7.
- Sources: European `hihead05NN.iff` hair, aligned to the shared
  `locreatehead` face; original UV/normal attributes are retained across seams.
- Cornrows: the approved 780-triangle version, including 272 protected
  lower-rear source triangles and the accepted bounded scalp-clearance offset.
- Styles 2, 13 and 16 include the approved rear-corner clearance correction.

`selector.bin` is the exact tested 268-byte replacement for EE
`0x18BF58..0x18C064`, including its selection table and UTF-16 stock-material
names. It uses the game's material lookup/visibility helpers and existing
`hair` texture bindings. It does not force high LOD. The stock material names
are disambiguated in both scenes and the three corresponding executable
binding pointers are patched together with this code.

`scripts/created_hair_lod.py` builds both extended scenes from the pristine
disc, preserves all stock streams, and supplies original-coordinate archive
and executable patches. `season_iso.py` combines them with normal texture and
roster edits before archive relocation and composes one ELF CRC compensation.
No experimental roster, private session scripts, mesh simplifier, SciPy or
Unicorn is needed for normal builds.

Do not replace a binary or update its hash merely to silence a mismatch.
Mesh changes need native geometry/UV/normal roundtrip and in-game review;
selector changes need corresponding scene/binding checks. See
[the investigation and review history](../../docs/player_record_layout.md#created-player-hairstyle-level-of-detail).
Original PS2 hardware and unreviewed appearance combinations remain unvalidated.
