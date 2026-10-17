#!/usr/bin/env python3
"""Find known PCSX2 texture keys in the live emulator memory.

This is an extension of the earlier string-probe. It is intended to answer the
question: do the known dumped texture keys appear directly in the live PCSX2
memory, and if so, where?
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as w
import subprocess

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_ALL = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
MEM_COMMIT = 0x1000

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
OpenProcess.restype = w.HANDLE
VirtualQueryEx = kernel32.VirtualQueryEx
VirtualQueryEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
VirtualQueryEx.restype = ctypes.c_size_t
ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [
    w.HANDLE,
    w.LPCVOID,
    w.LPVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
ReadProcessMemory.restype = w.BOOL
CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [w.HANDLE]
CloseHandle.restype = w.BOOL


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", w.DWORD),
        ("__alignment1", w.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", w.DWORD),
        ("Protect", w.DWORD),
        ("Type", w.DWORD),
    ]


def find_pcsx2_pid() -> int | None:
    out = subprocess.check_output(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'pcsx2' } | Select-Object -ExpandProperty ProcessId",
        ],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    ids = [int(line.strip()) for line in out.splitlines() if line.strip()]
    return ids[0] if ids else None


def iterate_committed_regions(handle: int):
    base = 0
    while True:
        mbi = MEMORY_BASIC_INFORMATION()
        nb = VirtualQueryEx(handle, ctypes.c_void_p(base), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if nb == 0:
            break
        start = int(mbi.BaseAddress or 0)
        size = int(mbi.RegionSize)
        if mbi.State == MEM_COMMIT and size > 0:
            yield start, size
        base = start + size
        if base > 0x7FFFFFFFFFFF:
            break


def read_memory(handle: int, address: int, size: int) -> bytes | None:
    if size <= 0:
        return b""
    buf = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t()
    ok = ReadProcessMemory(handle, ctypes.c_void_p(address), buf, size, ctypes.byref(read))
    if not ok:
        return None
    return bytes(buf.raw[: read.value])


def find_pattern(data: bytes, pattern: str) -> int | None:
    pat_ascii = pattern.encode("ascii", errors="ignore")
    if pat_ascii:
        pos = data.lower().find(pat_ascii.lower())
        if pos != -1:
            return pos
    pat_utf16 = pattern.encode("utf-16le")
    pos = data.lower().find(pat_utf16.lower())
    if pos != -1:
        return pos
    return None


def format_context(data: bytes, offset: int, extra: int = 96) -> bytes:
    start = max(0, offset - extra)
    end = min(len(data), offset + extra)
    return data[start:end]


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe specific texture keys in the running PCSX2 process.")
    parser.add_argument(
        "--patterns",
        nargs="*",
        default=[
            "336d3eccf0e668f5-43ba0221943876ba-00001dd3",
            "c3a55f457f58ff69-e39984b39648c466-00001dd3",
            "bc8a0c3c2468cc58-8d51603fc90a99a6-00002213",
            "bd859887167be8fc-8218e5904033c8cf-00002213",
            "00001dd3",
            "00002213",
        ],
        help="Texture-key strings to search for in the PCSX2 memory.",
    )
    args = parser.parse_args()

    pid = find_pcsx2_pid()
    if pid is None:
        print("No PCSX2 process found.")
        return 1

    handle = OpenProcess(PROCESS_ALL, False, pid)
    if not handle:
        print(f"OpenProcess failed for PID {pid}.")
        return 2

    try:
        hits = []
        for region_start, region_size in iterate_committed_regions(handle):
            chunk = min(0x10000, region_size)
            addr = region_start
            while addr < region_start + region_size:
                block = min(chunk, region_start + region_size - addr)
                data = read_memory(handle, addr, block)
                if data is None:
                    addr += block
                    continue
                for pattern in args.patterns:
                    pos = find_pattern(data, pattern)
                    if pos is not None:
                        hits.append((pattern, addr + pos))
                        print(f"MATCH {pattern!r} at 0x{(addr + pos):X}")
                        print(f"  context={format_context(data, pos)!r}")
                addr += block

        if not hits:
            print("No matches found for the provided patterns.")
        return 0
    finally:
        CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
