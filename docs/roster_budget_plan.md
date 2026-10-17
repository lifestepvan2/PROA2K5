# Plan: fitting ProA names into NBA 2K5 name slots ("budgeting & mapping")

Goal: replace the 30 NBA teams / ~790 players of ESPN NBA 2K5 (PS2, SLES-53022, PCSX2) with
the 18 ProA teams / ~250 players, although in-RAM replacement strings **cannot be longer than the
original** (see `poc_findings.md`). Must be fully re-runnable for every new ProA roster
(`proa_rosters.xlsx`: 18 sheets, 13-15 players each, columns `First Name`, `Last Name`, ...).

Status: **plan only** + card-file analysis (section 1). Nothing below section 1 is implemented yet.

---------------------------------------------------------------------------------------------------

## 1. What the roster save on the memory card is (analysed, verified)

Card: `Documents\PCSX2\memcards\Mcd001.ps2` (8 MB, 512+16 byte pages with ECC, cluster = 1024 B).
Reader: `python scripts/mc_inspect.py <card.ps2> [--extract DIR]`.

| File in `/BESLES-53022Roster1/` | Size | Content |
|---|---|---|
| `BESLES-53022Roster1` | 725 056 (0xB1040) | the roster payload (below) |
| `EXTRA` | 4 | **CRC32 of the payload**, little-endian (`E9 51 B8 7F` == `zlib.crc32(payload)=0x7FB851E9`, verified) |
| `TYPE` | 8 | UTF-16 `"ROS"` |
| `icon.sys`, `VIEW.ICO` | 964 / 33 956 | cosmetic, leave alone |

Payload (`ROST` file): **uncompressed, no encryption.**
* Header: `"ROST"`, `0x000B1020` (= size-0x20), `0x256D4`, `0x872E0`, zeros, `"ROST"` again at `0x2C`,
  then a small section table at `0x38..0xDB` (not yet decoded; pairs of count/size-like values).
* Record tables from `0xDC` (team records are `0x30` bytes: starts with 5 string pointers
  — arena, city, abbreviation, state, ... — then flags such as `0x43AF0000`, `0x1`, ids).
  Player/other record tables follow up to ~`0x66xxx`.
* **String pool `0x675DC … 0xAB000+`**: UTF-16LE, NUL-terminated (2-byte `\0\0`), packed without
  headers, no length prefix. Order for players: `Last, First, Nickname, Birthday(m/d/yy)`
  (e.g. `AAAAAAA, Allen, The Answer, 6/7/75`) – the same format as the RAM table at `0xB02xxx`.
  Teams: arena, city, `sNNN`, abbr, state, nickname... (`Wachovia Center, Philadelphia, s000, PHI, PA`).
  ~788 player entries, alphabetical name dictionaries (Isham, Torris, ... "Iversen") for
  generated players also live after the player block (`0x80000+`).
* **The file contains our RAM patches** (`AAAAAAA` instead of Iverson, `BBBBB` instead of McKie,
  `CCCCCCCC` instead of Drobnjak) – the game serialises its live roster heap, so a name edit in
  RAM → "Save Roster" → persisted in the file. This confirms the file is a heap snapshot.
* **RAM mapping:** after loading, the payload sits in RAM at `0xA95B80 + file_offset`
  (verified: pool region `0x67000-0xAB000` is byte-identical; `Iverson` RAM `0xB02808` ==
  file `0x6CC88`). RAM base of the heap is therefore `0xA95B80` (constant so far; re-verify per
  build/session with the `ROST`/string anchor).
* **Pointers in the file are self-relative with a tag:**
  `target_file_offset = address_of_pointer_field + value - 1`
  (verified on all team-record pointers; 3 556 of 3 933 pointer-like words fit, the other 377 are
  other data or a second pointer kind – to be classified). In RAM the loader rewrites them to
  absolute addresses (`0xAFD1A8` ...).
  → The file is **position independent**, which means strings can in principle be repacked in the
  file (new offsets + recomputed relative pointers) – i.e. **longer names are possible on the card
  side** as long as the loader only needs `size` fields from the header and every consumer reads the
  string through the pointer. This is *unverified* and is the single most valuable experiment
  (see 5, E1).
* In-place overwrite on the card is straightforward: same payload size ⇒ no FAT/dir change.
  Only write the payload clusters (follow the FAT chain from dir entry cluster `1539`), then
  the 4-byte `EXTRA` (cluster `2249`), then recompute page ECC (PCSX2 tolerates stale ECC, but do
  it anyway) and optionally update the dir entry mtime. If the size changes the FAT chain and
  directory `length` must be updated too – avoid that.

Names also exist **outside** the heap snapshot (and will not come from the card):
`0x755f48/0x756036` (Iverson, other UI string tables), and the fixed-width *stats/roster table*
`0xA6Fxxx-0xA71xxx` (30-byte first / 32-byte last name per record, built at load time from the
roster). These are rebuilt from the roster during load, so they must be handled by the
RAM-patch step (section 4) or turn out to be derived automatically (to be tested, E2).

---------------------------------------------------------------------------------------------------

## 2. Constraint model

Per NBA player slot `p` we record:

* `cap_last(p)`, `cap_first(p)`, `cap_nick(p)` in UTF-16 chars = original string length
  (the RAM-patch route; null-padded).  Practical hard limits from the fixed-width stats table:
  first ≤ 15, last ≤ 16 chars.
* Display limits: lineup card shows `F. Lastname` (first initial + last, width ~16 chars at the
  screen font); other screens use other widths. Use the tighter of RAM cap and display cap.
* slot ID = index in the roster table (and the texture key of the face, see `pcsx2_texture_mapping.md`).
  Team slot `t`: `cap_city(t)`, `cap_nick(t)`, `cap_abbr(t)` (3 chars), arena, ...

Per ProA player `q`: `need_last(q)`, `need_first(q)` (after allowed shortening: truncation rules
below). Per ProA team: `need_city`, `need_nick`, `need_abbr`.

If E1 shows the card route can repack strings, none of this matters for names and only the display
limits stay; keep the budgeting as the fallback.

---------------------------------------------------------------------------------------------------

## 3. Offline tooling (all pure Python, no emulator needed)

1. **`roster_slots.json` – inventory of replaceable slots.**
   Parse the payload (and/or a RAM dump) → for every player record: record index, address/offset of
   last/first/nick/birthday strings, capacities, jersey, position, NBA team index. For teams: all
   string fields + capacities. Source of truth = a **pristine** payload; save one *unmodified* roster
   from the untouched game as `data/roster_pristine.bin` (current file already contains AAAAAAA
   etc. – do not use it as pristine; a clean copy can also be rebuilt by restoring those 3 names).
   Also store which NBA player/face texture key belongs to the slot.
2. **`budget_assign.py` – the assignment.**
   Input: `roster_slots.json`, `proa_rosters.xlsx`. Output: `assignment.json`:
   `proa_player -> nba_slot_id`, plus `team_map: proa_team -> nba_team_slot`, plus the final strings.
   Algorithm:
   * Teams first (few, easy): sort ProA teams by `len(city)+len(nick)` desc, NBA team slots by
     capacity desc, greedy match; if a name does not fit apply the shortening ladder
     (below); the 12 unused NBA teams become "filler" teams (see 3.4).
   * Players: it is a bipartite matching with a *two-dimensional* weight (first, last). Per
     ProA team, choose the NBA team slot, then within the team assign by position (PG/SG/SF/PF/C
     so starters stay in the right on-court slots; the roster order and starting five are part of
     the NBA team's record) – solve each team as a small assignment (Hungarian algorithm,
     `scipy.optimize.linear_sum_assignment`) with cost = infeasible if `need>cap`, else penalty
     for wasted capacity and for position mismatch.
     Pre-sort as you proposed: ProA teams with the longest total names are mapped onto the NBA
     teams whose slots hold the longest names (compute `sum(cap)` per NBA team and rank).
     Because only 18 of 30 NBA teams are used, we can pick the 18 NBA teams with the *largest*
     total budget – the remaining 12 hold the short names and become fillers.
   * Fallback when a player still does not fit (long compound names, e.g. `Schoenfeldt-Mueller`):
     shortening ladder: (1) drop nickname field → keep as is, (2) first name → initial
     (the game prints `F. Last` anyway, so the first name capacity rarely matters),
     (3) strip diacritics (`ü→u`, `ß→ss`; the font probably lacks them: **test glyph set**),
     (4) last-name compound → first part / hyphen drop, (5) truncate with `.`; every rung logged
     to `assignment_report.md` for manual override via `overrides.csv` (hand-edited, wins over the
     algorithm and is re-applied on every run).
   * Surplus players: an NBA team has 12-15 slots; ProA teams have 13-15 players. When a team has
     fewer players than slots, the empty slots receive generic fillers; when more, the extras go to
     free agents (free-agent pool slots exist in the roster; if the budget allows, otherwise
     cut the lowest-rated).
   * Filler NBA teams (12): either rename to short names ("FA 1", "Draft") or *keep the NBA
     names as an Easter-egg all-star pool*. Prefer the second – no edit needed; but make sure the
     schedule/season mode is not used with them (quick game only for the POC).
3. **`build_roster.py` – write a roster payload** (works on bytes, no emulator):
   take pristine payload → for every slot write the assigned strings
   * *RAM-compatible mode*: overwrite in place, null-padded to the original capacity
     (always safe, same size, no pointer changes).
   * *Repack mode (needs E1)*: regenerate the whole string pool with the exact strings, then
     recompute relative pointers and size fields.
   plus numeric attributes from the xlsx (ratings, height/weight, jersey, position – need
   the 2K26-pipeline column → 2K5 record-field mapping, see 6) and, if wanted, new birthdays.
   Then CRC32 → `EXTRA`.
4. **`card_write.py`** – inject payload + `EXTRA` into `Mcd001.ps2` in place (FAT chain walk,
   cluster rewrite, page ECC fix), with automatic timestamped backup of the card. PCSX2 must be
   closed (or at least no game running), or the emulator overwrites the file at exit.
   `mc_inspect.py` already contains the reader half.
5. **`texture_map` generation** – independent of names: per NBA slot the face texture key and the
   team-logo/jersey keys (from `docs/pcsx2_texture_mapping.md`); `build_textures.py` renders the
   ProA face/logo PNGs named with the slot's dump key into `replacements/`.

All of these read **one** `assignment.json` so names, textures and attributes can never disagree.

---------------------------------------------------------------------------------------------------

## 4. In-game procedure (per roster update)

1. Offline: `python build_all.py` ⇒ `Mcd001.ps2` with `Roster1` replaced, `replacements/*.png`
   regenerated, `assignment_report.md` written. (PCSX2 closed.)
2. Start PCSX2, boot game, `Options > Load Roster > Memory Card 1 > Roster1`
   (scripted with `pcsx2_controller.py`; save-state at the menu if it makes startup quicker –
   but **save-states contain the old roster heap**, so load the state *before* loading the roster).
3. After load: `apply_ram_patches.py` – for everything the roster file does *not* control:
   * team-name strings used by menus (`0x7797e0`, `0x779910`, team select ...),
   * the fixed-width stats table `0xA6Fxxx` if it is not rebuilt from the loaded roster (E2),
   * `0x755xxx` UI tables.
   Verify by reading the same addresses back and by a screenshot of Team Select, Lineup,
   Start Game and a short game (scoreboard `PHI`/`ATL` abbreviation graphics are textures – see
   the texture map).
4. F10 (reload replacements), re-enter the screen.
5. Optional: `Save Roster` in-game again to persist everything the game itself rewrote
   (consistent snapshot, CRC valid) and use *that* as the next pristine/template.

Team names (simple scale of the same idea): 30 slots × (city, nickname, abbr, arena): the
ProA names are usually longer ("Crailsheim Merlins"). Order: choose which NBA team slot gets
which ProA team by cap; shorten ladder `City Nick → Nick → City → 3-letter code`; menus show
only the **nickname** (Team Select: `76ERS`, `HAWKS`) so the nickname budget matters most
(≤ 8-9 chars at that banner width; `MAVERICKS` is the widest observed). Abbreviations: 3 chars,
unique. Team logos/jerseys/floors/courts are textures (separate).

---------------------------------------------------------------------------------------------------

## 5. Experiments needed before building (ordered, each small)

| # | Question | How | Decides |
|---|---|---|---|
| E1 | Does the loader accept a payload whose strings were moved/lengthened (repack)? | take the current card payload, move one name string to the end of the pool with a longer text, fix the one pointer + CRC, load it | whether the budget is a hard limit at all |
| E2 | Which table feeds the lineup/start-game names: heap pool (`0xB02xxx`) or the stats table (`0xA6Fxxx`)? Is the latter rebuilt on roster load? | patch one copy at a time and look at the screen (the AAAAAAA test touched all copies); load a modified card roster and read `0xA6Fxxx` | whether `apply_ram_patches.py` is needed for players |
| E3 | Does the card loader check `EXTRA` (CRC)? ECC? | flip a payload byte without fixing CRC → load | whether CRC fix is mandatory |
| E4 | Is `0xA95B80` stable (heap base) across sessions/rosters? | find `ROST`/anchor strings after each launch | keep the base hard-coded or search |
| E5 | Glyph set (umlauts, `ß`, `-`, `'`, `.`) | write a test string, look | ladder rung 3 |
| E6 | Pointer kinds: classify the 377 pointer-like words that do not fit `addr+val-1` | compare file vs RAM for all words in tables | needed for repack mode |
| E7 | Section table at `0x38-0xDB` (counts, sizes) and header words `0x256D4`, `0x872E0` | vary record counts in a copy | repack / count changes |
| E8 | Does the loaded roster reference the stats-table rows by index (`player id`)? And how do player IDs map to face textures? | continue `pcsx2_texture_mapping.md` | texture linkage |

### Results

**E1 – DONE, PASSED (repack works).** `scripts/repack_test1.py` rewrote K. Thomas' last name
`Thomas` -> `Thomasberger` and first name `Kenny` -> `Zebediah`, placing the new UTF-16LE strings in
the zero gap at payload `0x67000` (the gap `0x6663b-0x675dc` is unused) and changing only the two
self-relative pointers at `0x66bc` / `0x66c0` (`value = target - field + 1`). Payload size stayed
the same, CRC32 in `EXTRA` was recomputed (`ab2ca167`), both files were written into
`Mcd001.ps2` with `mc_write.py` (PCSX2 closed, ECC recomputed; `--verify` clean).
Result in game: Options > Load/Save lists `Roster1 751 KB Roster`, loading reports
*"Successfully loaded Roster Roster1"*, the heap holds `Thomasberger` at `0xAFCB80` and `Zebediah`
at `0xAFCB9C` (pointers rewritten to absolute addresses), and the Start Game lineup shows
**"Z. Thomasb…"**. So:

* Strings can be moved and lengthened on the card; **the per-slot length budget is not a hard
  limit.** Only free space matters (4001-byte gap, plus any slots we free by shortening/relocating).
* The real limit is the **on-screen label width**: the lineup caption truncates with an ellipsis
  (~11 chars at that size). The budget model therefore becomes a *pixel/char display budget per
  screen*, not a byte budget per slot. Fine-tune by screen (lineup captions are the tightest).
* The loaded roster also overwrote the earlier RAM patches: the card payload (with AAAAAAA/BBBBB and
  `76XXX`, which were baked into the card when it was saved) is what is shown. The in-RAM
  `76ers` -> `76XXX` header and AAAAAAA names came from the card, not from a live patch.
* The pool region `0x67000-0xAB000` is byte-identical in RAM at `0xA95B80 + offset` after load.
* The mc_write round-trip is byte-identical (fix: preserve the slack bytes after the end of a file
  in the last page instead of zero-padding).

**E2 (partial).** The lineup/Start Game screen follows the *heap payload* strings (changing the
pointer on the card changed the screen), so card-side editing is sufficient for lineup names.

**E3 (partial).** Not tested negatively; we always write a correct CRC32 and ECC, and the game
accepts it.

Next: build the full pool-repack (`build_roster.py`): rewrite every player/team string pointer from
the ProA data, append all new strings to a rebuilt pool (reclaiming old string space for
space), keep size constant (or test whether the payload size/header words may change), then update
CRC and write to the card.

Notes for the experiments: PCSX2 is currently sitting on the in-game *Save Roster* screen; load/save
cycles can be driven with `pcsx2_controller.py`; remember the PS2 RAM host base changes per launch
(`full_scan_ps2_base.py`).

---------------------------------------------------------------------------------------------------

## 6. Open items / risks

* Player attribute mapping (ratings etc.) between the 2K26 pipeline columns and the 2K5 record
  fields has not been investigated; the record layout (stride, fields) must be decoded from the
  player table in the payload (find a table with 788 entries; compare to the in-game ratings of
  known players, e.g. Iverson).
* `0x43AF0000` (float 350.0?) and the flag words in team records are undecoded.
* If the heap is rebuilt when starting a game (it appears to be) the in-RAM patches must be done
  after the final "load roster" and before the game starts; the pause/start screens re-read strings
  live so patches after load are visible immediately (verified for the Start Game screen).
* Season/franchise modes use schedules keyed by team index; quick game first.
* Keep a pristine copy of the original card and of the game's default roster. Never write to the card while PCSX2 runs.
* Restore the SDL pad bindings in `PCSX2.ini` (`docs/pad1_sdl_backup.txt`) when automation is finished.

**E4 (full build).** scripts/build_roster.py output (18 ProA teams / 269 players, 75 name adjustments) loaded from the card and a quick game ran with ProA abbreviations and names (HAG vs TUE). Layout details: docs/roster_payload_format.md.
