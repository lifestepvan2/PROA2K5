# PCSX2 NBA 2K5 texture-to-ID mapping plan

## Goal
Determine how to connect:
- player records / player IDs to their face / portrait textures
- team records / team IDs to their logo or jersey textures

The working assumption is that the game contains a texture table or resource map that links a specific game object ID to a specific texture resource. The files in the dump directory are the raw evidence for that mapping.

## Evidence from the current texture dump folder
The dump directory at `C:\Users\Sebastian\Documents\PCSX2\textures\SLES-53022\dumps` contains 307 PNGs.

The most important observation is that the files are not all the same size. They cluster by dimensions:

- 128x128: 70 files
- 256x256: 56 files
- 512x512: 6 files
- 64x64: 28 files
- 64x32: 32 files
- 32x32: 28 files
- other small UI/marker textures also exist

This strongly suggests multiple asset classes are being dumped together:

1. player headshots / portraits
   - likely 128x128 textures

2. team logos / main badge art
   - likely 256x256 and 512x512 textures

3. small UI helper textures
   - text, jersey markers, overlays, numbers, small icons

## Most likely asset classification
### Player textures
The screened image shows a lineup with 10 active players, each with a portrait and jersey number. The current dump set includes about 70 128x128 textures. That is a realistic count for a roster portrait pool and is a much better fit than the 256x256 / 512x512 area, which is more likely to be logo art.

So the working hypothesis is:
- 128x128 PNGs = player face / portrait textures
- 256x256 PNGs = team main art or logo textures
- 512x512 PNGs = larger logo or banner variants

## Naming pattern
The names look like this:

- `<hash1>-<hash2>-00001dd3.png`
- `<hash1>-<hash2>-00002213.png`
- `<hash1>-<hash2>-00002653.png`

The trailing numeric token is very likely a resource/category identifier, not the player ID itself. The two hash-like parts look like texture or object keys, and the trailing value likely identifies the asset family or resource type.

The observed major families include:

- `00001dd3`: dominant 128x128 set
- `00002213`: dominant 256x256 set
- `00002653`: 512x512 set
- many other smaller suffixes correspond to small UI/icon textures

That means a direct filename-to-player-id mapping is not yet visible; instead, it is likely a two-step process:
1. identify the resource family (face, logo, UI)
2. resolve the actual player/team record ID using memory or hash lookup

## How to map player IDs to textures
### Option A: memory-driven mapping (preferred)
This is the cleanest method.

1. Attach to the running PCSX2 process and identify the currently visible lineup structure.
2. Find the roster/player table in emulated memory.
3. Resolve the current lineup slot ordering and associated player IDs.
4. For each visible player slot, follow a pointer chain or object reference to the texture id / texture pointer associated with that player portrait.
5. Compare that value to the dump filename ID family (the trailing numeric token / hash pair).
6. Record the mapping as:
   - `player_id -> texture_resource_key`

This is the exact form we want for a future automated patcher.

### Option B: brute-force / reverse-engineering mapping
When memory is not yet stable enough, use the dump set as a reference corpus.

1. Collect all 128x128 face textures and normalize them into a small hash / fingerprint.
2. For each player in the visible lineup, capture the live portrait from the emulated UI.
3. Compare the live portrait to the dump fingerprints and find the nearest match.
4. Record the corresponding file name / hash pair.
5. Repeat across other roster entries until the entire list is matched.

This is slower and less robust, but it works well when the data is static and the roster is complete.

## How to map team IDs to textures
Use the same approach, but on the team/logo side:

- 256x256 / 512x512 textures are the strongest logo candidates
- build a list of candidate team textures
- compare them against the visible team nest / scoreboard / logo regions in the UI
- associate each team with its resource fingerprint
- then resolve the team ID through the game memory or roster table

## Concrete findings from the live emulator (2026-10-17)
The exact texture keys are present in PCSX2 memory, which is the important breakthrough.

Observed matches in the live emulator process:

- `336d3eccf0e668f5-43ba0221943876ba-00001dd3` found at:
  - `0x1798E632C30`
  - `0x1798E8A33A4`
  - `0x1798E95F670`
  - `0x17AD5986B30`

- `c3a55f457f58ff69-e39984b39648c466-00001dd3` found at:
  - `0x17993396500`

- `bd859887167be8fc-8218e5904033c8cf-00002213` found at:
  - `0x1798E97E0B0`

- `bc8a0c3c2468cc58-8d51603fc90a99a6-00002213` also appears in the same memory area, and the live scan confirms the 00002213 family is present.

These strings are not random; they are adjacent to file-path metadata such as:

- `C:\Users\Sebastian\Documents\PCSX2\textures\SLES-53022\replacements\336d3eccf0e668f5-43ba0221943876ba-00001dd3.png`
- `C:\Users\Sebastian\Documents\PCSX2\textures\SLES-53022\dumps\336d3eccf0e668f5-43ba0221943876ba-00001dd3.png`

This means the game runtime is explicitly referencing the replacement/dump texture filenames, and the actual resource key is living in live memory. That gives us the exact identity we need for the next phase.

## Interpretation
The memory does not yet expose a simple `player_id -> texture_id` pointer chain in one line, but it does expose the texture key strings directly in the emulator process. This is enough to proceed with a practical mapping layer:

1. treat the dumped file ID as the canonical asset key
2. search the live memory for that key string
3. read the surrounding memory object to find the owning roster or team entry
4. backtrack from that object to the actual in-game player/team record

This is a direct and reliable approach because the replacement path is already in memory.

## Best practical algorithm
The most robust implementation is:

1. classify dump files by image size and suffix
2. isolate the 128x128 set as player candidates
3. isolate the 256x256+ set as team candidates
4. compute a normalized perceptual hash for each candidate texture
5. when a roster screen is open, capture the live texture region of each visible player/team
6. compare live captured images to the dump fingerprints
7. use the memory-resident file key to anchor the real record in the emulated game state
8. record exact `player_id/team_id -> texture_key` mappings and save them as JSON

This gives a stable bridge between:
- `player_id` / `team_id` in memory
- `texture_resource_key` in the dump set
- actual rendered UI texture in the game

## Expected first result
The highest-confidence mapping hypothesis is:
- 128x128 cluster = player portrait textures
- 256x256 / 512x512 cluster = team logo textures
- trailing numeric suffix = resource family / asset id, not the final player ID
- the exact dump filename is the live reference key, and it can be found directly in PCSX2 memory

## Next phase after this discovery
The next concrete task is:

1. scan the live PCSX2 memory for the full texture-key list for the visible lineup
2. resolve each key to its owning roster entry / team entry nearby in memory
3. confirm the relationship between the key and the visible player/team slot
4. then build the `texture_key -> player_id/team_id` data table

Once that is done, the mapping is no longer a guess; it becomes a real live-memory association between the emulated game data and the texture dump set.
