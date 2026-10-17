"""dump_roster_table.py — Dump the raw player table starting from a known address.
Shows the sequential player records to reveal record structure."""
import sys, struct
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fast_scan import read_ps2_ram, scan

def dump_region(ram, start, length=0x800, cols=16):
    """Hex+ASCII dump of a RAM region."""
    for row in range(0, length, cols):
        addr  = start + row
        chunk = ram[addr:addr + cols]
        hex_  = " ".join(f"{b:02x}" for b in chunk)
        asc_  = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
        print(f"  {addr:#010x}:  {hex_:<47}  {asc_}")

def find_utf16_strings(ram, start, length=0x500):
    """Extract all UTF-16 LE strings from a region."""
    data = ram[start:start + length]
    strings = []
    i = 0
    while i < len(data) - 1:
        # Try reading a UTF-16 string
        j = i
        chars = []
        while j + 1 < len(data):
            cp = data[j] | (data[j+1] << 8)
            if cp == 0:
                break
            if 0x20 <= cp < 0x7F:
                chars.append(chr(cp))
            else:
                chars = []
                break
            j += 2
        if len(chars) >= 3:
            strings.append((start + i, "".join(chars)))
            i = j + 2  # skip past null terminator
        else:
            i += 2
    return strings

def main():
    print("Reading PS2 RAM...")
    ram = read_ps2_ram()

    # Starting from ~before McKie to see context
    # McKie first name at 0xa6f8f6, let's start 0x200 before that
    start = 0x00a6f600
    print(f"\n=== Wide dump around 76ers roster block @ {start:#010x} ===")
    dump_region(ram, start, length=0x800)

    print(f"\n=== UTF-16 strings extracted ===")
    strings = find_utf16_strings(ram, start, length=0x800)
    for addr, s in strings:
        print(f"  {addr:#010x}: {s!r}")

    # Also dump around Iverson full-profile table
    start2 = 0x00b02790
    print(f"\n=== Full profile table around Iverson @ {start2:#010x} ===")
    dump_region(ram, start2, length=0x300)

    print(f"\n=== UTF-16 strings (full profile) ===")
    for addr, s in find_utf16_strings(ram, start2, length=0x300):
        print(f"  {addr:#010x}: {s!r}")

if __name__ == "__main__":
    main()
