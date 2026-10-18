# Roster payload format (NBA 2K5 PS2, `BESLES-53022Roster1`)

The roster file on the memory card is an uncompressed **heap snapshot** (size `0xB1040`, CRC32 stored
in the `EXTRA` blob). After loading, payload offset `X` lives at PS2 RAM `0xA95B80 + X`
(the loader rewrites the pointers to absolute addresses; the on-card form is self-relative).
Tooling: `scripts/mc_inspect.py` (extract), `scripts/mc_write.py` (write in place + ECC),
`scripts/build_roster.py` (build the ProA payload).

## Pointers

Self-relative with a tag: `target = field_offset + signed_i32(value) - 1` (low bit set).
Always use signed `<i`. Only pointer fields below `POOL_MIN` (0x675DC) are rewritten; "pointers"
inside the string pool are false positives.

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
`build_roster.py` reads `data/proa_arenas.csv` (`sheet,arena,verified`) and writes `data/roster_build/arena_map.csv`.
Live tools: `scripts/arena_table.py` (list rows from RAM), `scripts/ram_write_str.py` (in-place patch, max original length),
`scripts/find_ps2_ram.py` (re-find RAM base after every PCSX2 restart).

## String pool handling (build_roster.py)

Best-fit allocator over the pool plus free gap. Strings are ref-counted through a map of referrers;
freed strings are zeroed and merged. Replacement strings **may be longer than the original** (verified
in-game, experiment E1) because the string is relocated and the pointer rewritten.

## Display limits

* Lineup caption shows `F. Lastname`, ellipsis at ~11-12 characters; default `--max-first/--max-last 12`.
* Umlauts are transliterated (ae/oe/ue/ss) unless `--keep-umlauts` is given (glyph support untested).

## Verified

* Card roster built by `build_roster.py` (18 ProA teams, 269 players) loads in-game and plays:
  scoreboard shows the new abbreviations (HAG, TUE), on-court captions and jerseys show ProA names.
* ECC verify of the written card equals the original (4577 ok, 1 pre-existing bad page); CRC32 is
  always recomputed.

## Not changed by build_roster.py (yet)

Jersey numbers, positions, ratings, birthdays, nicknames, textures, NBA slots 0-11 (still NBA
teams), all-star/legend teams referencing NBA player records.
