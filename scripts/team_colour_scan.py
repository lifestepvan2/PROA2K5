"""Inspect RGB-like fields in saved NBA 2K5 team records; never writes the payload.

    python scripts/team_colour_scan.py
    python scripts/team_colour_scan.py --payload data/roster_test/payload_current.bin --slot 20

The two RGB triplets are candidates, not confirmed jersey lettering controls.
"""
import argparse
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEAM_BASE, TEAM_STRIDE, TEAM_COUNT = 0x11F0, 0x124, 54
PAYLOAD_SIZE = 0xB1040


def read_string(payload, field):
    target = field + struct.unpack_from("<i", payload, field)[0] - 1
    if not 0 <= target < len(payload) - 1:
        raise ValueError(f"Invalid string pointer at 0x{field:X}: 0x{target:X}")
    end = target
    while end + 1 < len(payload):
        if payload[end:end + 2] == b"\0\0":
            return payload[target:end].decode("utf-16le")
        end += 2
    raise ValueError(f"Unterminated string at 0x{target:X}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, default=ROOT / "data" / "roster.bin")
    parser.add_argument("--slot", type=int, choices=range(TEAM_COUNT),
                        help="Also hex-dump one complete team record (NBA Pacers = 20)")
    args = parser.parse_args()
    payload = args.payload.read_bytes()
    if len(payload) != PAYLOAD_SIZE:
        parser.error(f"Expected {PAYLOAD_SIZE} bytes, got {len(payload)}")
    print("RGB candidates only; home/away, fill/outline and rendering use are unverified.")
    print("Slot  Record    Team                      +62 RGB   +65 RGB")
    for slot in range(30):
        base = TEAM_BASE + slot * TEAM_STRIDE
        name = read_string(payload, base + 0x48)
        first = payload[base + 0x62:base + 0x65].hex().upper()
        second = payload[base + 0x65:base + 0x68].hex().upper()
        print(f"{slot:4}  0x{base:06X}  {name:24}  #{first}  #{second}")
    if args.slot is not None:
        base = TEAM_BASE + args.slot * TEAM_STRIDE
        print(f"\nSlot {args.slot}: payload 0x{base:X}, triplets at 0x{base + 0x62:X} / 0x{base + 0x65:X}")
        for offset in range(0, TEAM_STRIDE, 16):
            chunk = payload[base + offset:base + min(offset + 16, TEAM_STRIDE)]
            print(f"+0x{offset:03X}  {chunk.hex(' ')}")


if __name__ == "__main__":
    main()
