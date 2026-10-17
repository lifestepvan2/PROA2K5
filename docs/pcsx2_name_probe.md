# PCSX2 NBA 2K5 name-replacement probe

## Objective
Attempt the first live-memory edit on the PS2 emulator by validating that the running PCSX2 process exposes the team/player names in memory and can be read safely before any write-back.

## Host findings
- Emulator process detected: `pcsx2-qt.exe`
- PID observed during the probe: `32456`
- Windows handle opened successfully via `OpenProcess` with read access.
- `VirtualQueryEx` confirms that the process has live committed memory regions and is not simply idle or frozen.

## First probe result
We ran a memory scan across committed regions against the target strings:
- `76ers`
- `Philadelphia`
- `Iverson`
- `Billups`
- `Allen`
- `Miller`
- `Jordan`

Result: no direct, reliable match for the 76ers-specific strings in the current live snapshot.

## Important nuance
The read operation works, and the process is definitely active. However, the first raw scan produced false matches in unrelated memory content — especially font licensing / system text — which means the memory is crowded with non-game strings and not yet mapped to a meaningful roster layout.

A representative example from the scan was a UTF-16LE `Allen` hit inside a font license block, not a roster record. That tells us the emulator process is alive and readable, but the game state is not yet exposed in a simple, direct string table that we can write to without a pointer chain or memory map.

## Relevance for the next step
This means the phase-1 plan should be:
1. Keep the target strings as search values, but do not assume they are stored as plain UTF-16 or ASCII strings in the host process.
2. Use the live emulator process as the read layer, while building a pointer-chain / structure map around the current roster screen.
3. Look for team-name and player-name records near the loaded lineup UI memory, not in random loaded font or system strings.
4. Only after a stable address or chain is found should we try a write-back such as replacing `76ers` or `Iverson` with a test string.

## Current offset / structure status
At this stage we have:
- process-level access confirmed
- live memory read confirmed
- memory scan route confirmed
- no trusted offset for team/player names in the current snapshot

This is the correct state to be in before the first write. We do not yet have a reliable target offset, so a direct replacement attempt would be blind and unsafe.

## Recommended next action
The next targeted probe should be done from the actual 76ers starting-lineup screen with a tighter memory search around the rendered player names and team name area, using repeated patterns and a pointer-ladder scan. Once one valid address is found, we can document exact offsets and write a controlled test replacement such as:
- team: `76ers` -> `PHILA`
- player: `Iverson` -> `IVA`
- player: `Billups` -> `BILL`

Only then should we consider a live write of the actual string payload.

## Summary
The memory attach step succeeded, but the exact in-game roster text offset has not been identified yet. The next phase is not a direct write; it is a structured memory-map and pointer-chain search anchored to the currently loaded 76ers starting lineup.
