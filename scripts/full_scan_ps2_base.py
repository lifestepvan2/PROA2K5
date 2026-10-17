"""full_scan_ps2_base.py — Exhaustive scan of all PCSX2 committed memory for PS2 RAM anchor."""
import sys, struct, ctypes, ctypes.wintypes as W, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from pine_client import PineClient

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT     = 0x1000
PAGE_NOACCESS  = 0x01
PAGE_GUARD     = 0x100

k32 = ctypes.windll.kernel32

class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress",       ctypes.c_void_p),
        ("AllocationBase",    ctypes.c_void_p),
        ("AllocationProtect", W.DWORD),
        ("RegionSize",        ctypes.c_size_t),
        ("State",             W.DWORD),
        ("Protect",           W.DWORD),
        ("Type",              W.DWORD),
    ]

def main():
    with PineClient() as p:
        # Build 16-byte anchor from PS2 addr 0x201000
        anchor = b"".join(struct.pack("<I", p.read32(0x00201000 + off)) for off in range(0, 16, 4))
        # Also get a second anchor at 0x200000 for double-check
        anchor2 = b"".join(struct.pack("<I", p.read32(0x00200000 + off)) for off in range(0, 4, 4))
    print(f"Anchor @ PS2 0x201000: {anchor.hex()}")
    print(f"Anchor @ PS2 0x200000: {anchor2.hex()}")

    r = subprocess.run(["tasklist","/FI","IMAGENAME eq pcsx2-qt.exe","/FO","CSV","/NH"],
                       capture_output=True, text=True)
    pid = int(r.stdout.strip().split(",")[1].strip('"'))
    print(f"PCSX2 PID: {pid}")
    h = k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)

    mbi  = MBI()
    addr = 0
    hits = []
    total_scanned = 0
    while addr < 0x7FFFFFFFFFFF:
        ret = k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if not ret: break
        base = mbi.BaseAddress or 0
        size = mbi.RegionSize or 0
        if size == 0: break

        skip = (mbi.State != MEM_COMMIT
                or (mbi.Protect & PAGE_NOACCESS)
                or (mbi.Protect & PAGE_GUARD)
                or size < 0x10000)   # skip tiny regions

        if not skip:
            read_sz = min(size, 0x4000000)  # cap at 64MB per read
            buf   = (ctypes.c_char * read_sz)()
            nread = ctypes.c_size_t(0)
            ok = k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, read_sz, ctypes.byref(nread))
            if ok and nread.value:
                data = bytes(buf[:nread.value])
                idx  = data.find(anchor)
                if idx >= 0:
                    found_host  = base + idx
                    ps2_ram_base = found_host - 0x201000
                    hits.append((ps2_ram_base, base, size, idx))
                    print(f"  FOUND in region {base:016x} at offset {idx:x} -> PS2 RAM host base: {ps2_ram_base:016x}")
                total_scanned += nread.value

        addr += max(size, 1)

    k32.CloseHandle(h)
    print(f"Total scanned: {total_scanned // 1024 // 1024} MB")

    if hits:
        best = hits[0][0]
        out = Path(__file__).parent.parent / "docs" / "ps2_ram_base.txt"
        out.write_text(f"{best:016x}\n")
        print(f"PS2 RAM host base: {best:016x}")
        print(f"Saved to {out}")
        # Quick verify
        h2 = k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        probe_host = best + 0x200000
        buf2 = (ctypes.c_char * 4)()
        nread2 = ctypes.c_size_t(0)
        k32.ReadProcessMemory(h2, ctypes.c_void_p(probe_host), buf2, 4, ctypes.byref(nread2))
        val = struct.unpack_from("<I", bytes(buf2))[0]
        k32.CloseHandle(h2)
        print(f"Verify: host[base+0x200000] = {val:08x}  (expected: {struct.unpack('<I',anchor2)[0]:08x})")
    else:
        print("ANCHOR NOT FOUND anywhere in process memory.")

if __name__ == "__main__":
    main()
