"""
fast_scan.py — Scan PS2 RAM for strings using direct ReadProcessMemory (fast path).

Usage:
    python scripts/fast_scan.py <search_term> [<search_term2> ...]
    python scripts/fast_scan.py --all_names
    python scripts/fast_scan.py --texture_keys

Reads the entire 32 MB PS2 RAM in one shot, then searches locally.
"""
import sys, struct, ctypes, ctypes.wintypes as W, subprocess, re
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

PROCESS_ALL_ACCESS = 0x1F0FFF
PS2_RAM_SIZE       = 0x02000000  # 32 MB
k32 = ctypes.windll.kernel32


def get_pcsx2_pid():
    r = subprocess.run(["tasklist","/FI","IMAGENAME eq pcsx2-qt.exe","/FO","CSV","/NH"],
                       capture_output=True, text=True)
    return int(r.stdout.strip().split(",")[1].strip('"'))


def load_ps2_ram_base():
    p = ROOT / "docs" / "ps2_ram_base.txt"
    if p.exists():
        return int(p.read_text().strip(), 16)
    raise RuntimeError("ps2_ram_base.txt not found — run find_ps2_ram.py first")


def read_ps2_ram() -> bytes:
    base = load_ps2_ram_base()
    pid  = get_pcsx2_pid()
    h    = k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    buf  = (ctypes.c_char * PS2_RAM_SIZE)()
    nread = ctypes.c_size_t(0)
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, PS2_RAM_SIZE, ctypes.byref(nread))
    k32.CloseHandle(h)
    if not ok:
        raise RuntimeError(f"ReadProcessMemory failed (error {k32.GetLastError()})")
    return bytes(buf[:nread.value])


def write_ps2_ram(offset: int, data: bytes):
    """Write bytes at PS2 address offset (direct host memory write)."""
    base = load_ps2_ram_base()
    pid  = get_pcsx2_pid()
    h    = k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    buf  = (ctypes.c_char * len(data))(*data)
    nwritten = ctypes.c_size_t(0)
    ok = k32.WriteProcessMemory(h, ctypes.c_void_p(base + offset), buf, len(data), ctypes.byref(nwritten))
    k32.CloseHandle(h)
    if not ok:
        raise RuntimeError(f"WriteProcessMemory failed (error {k32.GetLastError()})")
    return nwritten.value


def scan(ram: bytes, needle: bytes, context_before: int = 32, context_after: int = 64) -> list[dict]:
    hits = []
    pos  = 0
    while True:
        idx = ram.find(needle, pos)
        if idx == -1:
            break
        ctx_start = max(0, idx - context_before)
        ctx_end   = min(len(ram), idx + len(needle) + context_after)
        ctx       = ram[ctx_start:ctx_end]
        printable = bytes(b if 0x20 <= b < 0x7F else ord(".") for b in ctx)
        hits.append({
            "ps2_addr": idx,
            "needle":   needle,
            "context_addr": ctx_start,
            "context": ctx,
            "printable": printable.decode("ascii"),
        })
        pos = idx + 1
    return hits


def print_hit(h: dict):
    print(f"  @ PS2 {h['ps2_addr']:#010x} : {h['printable']}")
    # Also hex dump the context
    ctx = h["context"]
    base = h["context_addr"]
    for row in range(0, min(len(ctx), 96), 16):
        chunk = ctx[row:row + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        ascpart = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
        print(f"    {base + row:#010x}: {hexpart:<47}  {ascpart}")


DEMO_NAMES = [
    b"Miller", b"Lenard", b"LAC", b"DEN",
    b"Clippers", b"Nuggets",
    b"Iverson", b"McKie", b"Robinson", b"Thomas", b"Dalembert",
    b"Billups", b"Hamilton", b"76ers", b"76ERS", b"Pistons",
]

TEXTURE_SUFFIX_PLAYER = b"00001dd3"
TEXTURE_SUFFIX_LOGO   = b"00002213"


def main():
    import time
    t0 = time.time()
    print("Reading PS2 RAM...")
    ram = read_ps2_ram()
    print(f"  Read {len(ram) // 1024 // 1024} MB in {time.time()-t0:.2f}s")

    args = sys.argv[1:]

    if not args or args[0] == "--all_names":
        targets = DEMO_NAMES
    elif args[0] == "--texture_keys":
        targets = [TEXTURE_SUFFIX_PLAYER, TEXTURE_SUFFIX_LOGO]
    else:
        targets = [a.encode() if isinstance(a, str) else a for a in args]

    total_hits = 0
    for needle in targets:
        hits = scan(ram, needle)
        if hits:
            print(f"\n[{needle!r}]  {len(hits)} hit(s)")
            for h in hits[:5]:
                print_hit(h)
            if len(hits) > 5:
                print(f"  ... and {len(hits)-5} more")
        else:
            print(f"\n[{needle!r}]  (not found)")
        total_hits += len(hits)

    print(f"\nTotal: {total_hits} hits across {len(targets)} search terms")


if __name__ == "__main__":
    main()
