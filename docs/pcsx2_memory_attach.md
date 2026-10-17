# PCSX2 NBA 2K5 memory attach plan

## Goal
Attach to the running PCSX2 process, inspect NBA 2K5 memory, and confirm a safe path for live manipulation before writing anything back to the emulated game state.

## Key fact
The target is not the PS2 game binary directly; it is the emulator process (`PCSX2.exe` or the launcher variant in use). The actual guest memory lives inside the emulator's process space and must be read via the emulator process, not by targeting a separate game executable.

## What to inspect first
1. Confirm the emulator is running a NBA 2K5 ISO or disc image.
2. Check the Windows process list for the PCSX2 executable.
3. Confirm process architecture (x64 vs x86), permissions, and whether access is available.
4. Identify whether the title uses:
   - direct emulator memory hooks,
   - guest memory pages mapped into the host process,
   - or a custom plugin/debug interface that exposes the emulated PS2 memory more cleanly.

## Windows attach approach
The working model for the phase-1 investigation is the same as the earlier 2K26 live-memory work:
- open the PCSX2 process handle with `OpenProcess`
- read the target memory with `ReadProcessMemory`
- locate known values / strings / integer patterns
- build pointer chains and memory table maps

For Python, the reference implementation to adapt is already in the copied 2K26 code under:
- `nba2k_editor/memory/game_memory.py`
- `nba2k_editor/memory/win32.py`
- `nba2k_editor/memory/scan_utils.py`

The code is useful as a reference for Win32 process access and scanning flow, even though the PS2 emulator is not the same process model as a PC game.

## Emulator-specific considerations
For PCSX2, the memory is emulated rather than live physical game memory. That means the usual direct game-memory assumptions are slightly different:
- addresses are in the emulator's process, not PS2 hardware addresses
- guest memory is mirrored into the host process in one or more windows
- pointer chains will need to be checked against the emulator's memory map, not the normal PC game layout
- the most stable path is usually a search against a known static string or value, then a pointer chain to the record of interest

## Investigation order
1. Build a minimal Python process-list script that enumerates PCSX2 instances and their PIDs.
2. Attach to the live emulator and dump a small memory region around the expected game data.
3. Search for known player names or obvious constants from the cached roster data.
4. Confirm if the values are stored as UTF-16 strings, ints, or enum-coded data.
5. Map the observed data back to the gameplay structure and record the offsets for future write logic.

## Recommended tools
- Process Explorer / Process Hacker for PID and module inspection
- Cheat Engine or a small ctypes-based scan script for memory verification
- PCSX2 built-in memory or debug tooling, if available in the emulator build
- The cached roster workbook data as the known-good value source for target searches

## Why this is the correct first step
The 2K26 project proved that the fastest path is to work from cached data and then reverse-engineer the live layout. For NBA 2K5 on PCSX2, the same sequence still applies: start with the frozen roster data, confirm process attach, then map memory and patch only after the emulator-side structure is understood.
