# NBA 2K5 (PCSX2, SLES-53022) – POC findings

Status: **name replacement and texture replacement both verified on screen** on the
QuickGame > Start Game (starters) screen (76ers at Hawks).

## 1. Attaching / memory access

| Item | Value |
|---|---|
| Process | `pcsx2-qt.exe` |
| PS2 RAM (32 MB) in host process | contiguous; host base changes **every PCSX2 launch** |
| Find base | `python scripts/full_scan_ps2_base.py` (anchor `0800e0038000bd27b0ffbd273000b17f` at PS2 `0x201000`; only works once the game runs, not during loading). Writes `docs/ps2_ram_base.txt` |
| Read/write | `scripts/fast_scan.py` (`read_ps2_ram`, `write_ps2_ram(ps2_addr, bytes)`) via `ReadProcessMemory`/`WriteProcessMemory` at `base + ps2_addr` |
| PINE | enabled, port 28011 (`scripts/pine_client.py`); request `[u32 len][cmd][args]`, reply `[u32 len][status 0=ok/0xFF=fail][data]`. Fine for single reads, too slow for bulk |
| Screenshot | `python scripts/pcsx2_capture.py --out docs/x.png` (BitBlt; `PrintWindow` returns black) |
| Input | `python scripts/pcsx2_controller.py "left l1 cross"` – `SendInput`, **PCSX2 must be foreground** (script focuses it each press). Keys: arrows=D-pad, Z=Cross, X=Circle, C=Triangle, V=Square, Enter=Start, Backspace=Select, Q/W/E/R=L1/L2/R1/R2, F1=save state, F3=load state, F10=reload texture replacements |

## 2. Text (names) – verified

* All strings are **UTF-16LE**. No ASCII copies.
* The lineup/starters screen reads the player-name strings in RAM live; patching them
  changes the screen immediately (no reload needed) and survives save-state load.
* Team names ("76ers", "Hawks"...) are plain UTF-16 strings in several copies.
* A replacement must not be longer than the original (pad with `\0\0`).
  First name ≈ 15 chars, last name ≈ 16 chars.
* `python scripts/patch_names.py Iverson AAAAAAA McKie BBBBB Drobnjak CCCCCCCC 76ers 76XXX`
  patches **every** whole-word occurrence. Verified results:
  * "A. Iverson" → "A. AAAAAAA", "A. McKie" → "A. BBBBB", "P. Drobnjak" → "P. CCCCCCCC"
  * "76ers at Hawks" header → "76XXX at Hawks", Team Select label "76ERS" → "76XXX"
    (the game upper-cases for display).

Known occurrences (PS2 addresses, stable between runs):

| String | Addresses |
|---|---|
| Iverson | `0x755f48 0x756036 0xb02808 0xb08c1c 0xb0912e` |
| McKie | `0xb02848` (+ `0xa6f916` as record in stats table) |
| Drobnjak | `0x7fa756 0x8e3f1a 0x9786d6 0x978a76 0x978ae6 0x98c3de 0xa70216 0xb03d9c` |
| 76ers | `0x755686 0x755726 0x755768 0x7797e0 0xafe970 0xafed9e 0xaffc22 0xaffc50 0xaffc6c` |
| Philadelphia | `0xafd17c 0xafe01e 0xafedba 0xafeddc` |
| Hawks | `0x779910 0x787c9a … 0xafeaa0 0xaff060` |

Tables: profile table around `0xb02xxx–0xb1xxxx` (last, first, nick, birthday) and a stats/roster
table `0xa6fxxx–0xa71xxx` (8-byte header, 30-byte first name, 32-byte last name, stat bytes).
See `docs/roster_addresses.json`. Re-scan after every game load; data is rebuilt when a
new roster is loaded so patches must be re-applied after leaving/entering a game.

## 3. Textures – verified

* Texture keys are PCSX2 texture-replacement hashes (`hash-hash-family`), **not** in PS2 RAM.
  `…-00001dd3` = 128x128 player face, `…-00002213` = team logo.
* Replacement = drop a PNG named exactly like the dump into
  `Documents\PCSX2\textures\SLES-53022\replacements\` (same size, RGBA).
  `LoadTextureReplacements = true` is already set.
* Verified: `336d3eccf0e668f5-43ba0221943876ba-00001dd3.png` (K. Thomas) and
  `c3a55f457f58ff69-e39984b39648c466-00001dd3.png` (A. Iverson) replaced with tinted
  "POC"/"POC2" banners; both show on the Start Game screen.
* New files are only picked up after a reload: **F10** (`ReloadTextureReplacements`, added to
  `[Hotkeys]` in PCSX2.ini) and re-entering/redrawing the screen (loading the save state
  works). An already-cached texture on the current screen does not change on its own.

## 4. Workflow to reproduce the lineup screen

1. QuickGame > Team Select. Arrow-left puts the controller on the home/away slot (shows
   "User1"), then L1/R1 cycles teams (L1 ×? from Mavericks → 76ers).
2. Cross → Start Game (starters) screen. Press **F1** there to save state (slot 1).
3. After restarts: launch ISO, wait for game, **F3** to land back on the screen.
4. Apply `patch_names.py`; edit replacement PNGs; F10 + F3 to refresh.

## 5. Next

* Build the per-player map: player record index → (name addresses, face texture key).
  Face keys are found by hovering rosters on this screen and diffing the dump folder.
* Generate all replacement PNGs from the ProA data and batch-patch names from the roster
  (field-width limited), then restore SDL pad config (`docs/pad1_sdl_backup.txt`) when
  automation is no longer needed (`[Pad1]` in PCSX2.ini is currently keyboard-only).
