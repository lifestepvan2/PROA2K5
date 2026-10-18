"""List the team/arena record table in live PS2 RAM (heap base 0xA95B80, records 0x30 bytes, string pointers absolute)."""
import struct

from fast_scan import read_ps2_ram

STRIDE, SEED = 0x30, 0xA96038  # SEED = address of a known arena pointer
ram = read_ps2_ram()


def u32(a):
    return struct.unpack_from("<I", ram, a)[0]


def s16(a):
    e = a
    while ram[e:e + 2] != b"\0\0" or e % 2:
        e += 1
    return ram[a:e].decode("utf-16-le", "replace")


def is_str(p):
    return 0xA95B80 < p < 0xBF0000 and 32 <= ram[p] < 127 and ram[p + 1] == 0


def rec_ok(a):
    return is_str(u32(a)) and is_str(u32(a + 8)) and is_str(u32(a + 12))


if __name__ == "__main__":
    first = SEED
    while rec_ok(first - STRIDE):
        first -= STRIDE
    a, k = first, 0
    while rec_ok(a):
        w = [u32(a + o) for o in (-0xC, -8, -4)] + [u32(a + 4)]
        print(f"{k:3d} ptr@{a:#x} hdr={w[0]:08x} {w[1]:08x} {w[2]:08x} int={w[3]:08x} | {s16(u32(a))} | {s16(u32(a + 8))} | {s16(u32(a + 12))} | {s16(u32(a + 16))} | {s16(u32(a + 20))}")
        a += STRIDE
        k += 1
