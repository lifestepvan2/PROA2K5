"""Re-find the host address of PS2 RAM after a PCSX2 restart (chunked scan; writes docs/ps2_ram_base.txt)."""
import ctypes
import ctypes.wintypes as W
import struct
import subprocess
from pathlib import Path

from pine_client import PineClient

k32 = ctypes.windll.kernel32
CHUNK = 0x1000000


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", W.DWORD),
                ("RegionSize", ctypes.c_size_t), ("State", W.DWORD), ("Protect", W.DWORD), ("Type", W.DWORD)]


def main():
    with PineClient() as p:
        anchor = b"".join(struct.pack("<I", p.read32(0x201000 + o)) for o in range(0, 16, 4))
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq pcsx2-qt.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    pid = int(out.strip().split(",")[1].strip('"'))
    h = k32.OpenProcess(0x1F0FFF, False, pid)
    mbi, addr = MBI(), 0
    while k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        base, size = mbi.BaseAddress or 0, mbi.RegionSize or 0
        if mbi.State == 0x1000 and not mbi.Protect & 0x101:  # RAM pages get split into tiny regions by the recompiler's write protection
            for off in range(0, size, CHUNK):
                n = min(CHUNK + 16, size - off)
                buf = (ctypes.c_char * n)()
                got = ctypes.c_size_t(0)
                if k32.ReadProcessMemory(h, ctypes.c_void_p(base + off), buf, n, ctypes.byref(got)) and got.value:
                    i = bytes(buf[:got.value]).find(anchor)
                    if i >= 0:
                        ram = base + off + i - 0x201000
                        Path(__file__).parent.parent.joinpath("docs/ps2_ram_base.txt").write_text(f"{ram:016x}\n")
                        print("PS2 RAM host base", f"{ram:016x}")
                        return
        addr = base + max(size, 1)
    print("anchor not found")


if __name__ == "__main__":
    main()
