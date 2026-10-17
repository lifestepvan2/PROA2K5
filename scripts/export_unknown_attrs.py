"""Export all teams/players of the loaded NBA 2K5 roster with the still-undecoded record bytes.

Source: live PCSX2 RAM over PINE (default; pointers are absolute after load) or a card payload
file (--payload, self-relative pointers). Output (data/nba_defaults/):
  players_unknown.csv  one row per player record: identity + decoded fields + every undecoded byte
  teams_unknown.csv    one row per team record: names + roster + raw non-pointer bytes
  payload_live.bin     raw dump (gitignored)
Layout: docs/roster_payload_format.md, docs/player_record_layout.md
"""
import argparse
import csv
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

RAM_BASE, SIZE = 0xA95B80, 0xB1040
PLAYER_BASE, PLAYER_STRIDE, PLAYER_COUNT = 0x64F4, 0x94, 0x318
TEAM_BASE, TEAM_STRIDE, TEAM_COUNT = 0x11F0, 0x124, 54
PTR_FIELDS = {0x0C, 0x10, 0x24, 0x28}  # last, first, nickname, birthday
KNOWN = set()
for o in (0x16, 0x17, 0x31, 0x41, *range(0x45, 0x4B), 0x4D, 0x4E, 0x51, 0x52, 0x53, 0x54, 0x56, 0x57, 0x58, 0x59, 0x5B, 0x5D, 0x5E):
    KNOWN.add(o)
KNOWN |= {0x34, 0x35}  # weight u16
for f in PTR_FIELDS:
    KNOWN |= set(range(f, f + 4))
UNKNOWN_BYTES = [o for o in range(PLAYER_STRIDE) if o not in KNOWN]


def read_live():
    from pine_client import PineClient
    out = bytearray()
    with PineClient() as p:
        for o in range(0, SIZE, 0x10000):
            out += p.read_bytes(RAM_BASE + o, min(0x10000, SIZE - o))
    return bytes(out)


class View:
    def __init__(self, data, absolute):
        self.d, self.abs = data, absolute

    def target(self, field):
        v = struct.unpack_from("<I", self.d, field)[0]
        if not v:
            return None
        if self.abs:
            return v - RAM_BASE if RAM_BASE <= v < RAM_BASE + SIZE else None
        v = struct.unpack_from("<i", self.d, field)[0]
        return field + v - 1 if v & 1 else None

    def string(self, field):
        t = self.target(field)
        if t is None or not 0 <= t < len(self.d) - 2:
            return ""
        e = t
        while e + 2 <= len(self.d) and self.d[e:e + 2] != b"\0\0":
            e += 2
        return self.d[t:e].decode("utf-16-le", "replace")

    def record(self, field):
        t = self.target(field)
        if t is None or (t - PLAYER_BASE) % PLAYER_STRIDE or not 0 <= (t - PLAYER_BASE) // PLAYER_STRIDE < PLAYER_COUNT:
            return None
        return (t - PLAYER_BASE) // PLAYER_STRIDE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", help="read a card payload file instead of live RAM")
    ap.add_argument("--out", default=str(ROOT / "data/nba_defaults"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    data = Path(a.payload).read_bytes() if a.payload else read_live()
    v = View(data, absolute=not a.payload)
    (out / "payload_live.bin").write_bytes(data)

    owner = {}  # player record -> (team slot, roster index)
    team_rows = []
    for t in range(TEAM_COUNT):
        b = TEAM_BASE + t * TEAM_STRIDE
        roster = []
        for i in range(15):
            r = v.record(b + 4 * i)
            if r is None:
                break
            roster.append(r)
            owner.setdefault(r, (t, i))
        starters = [v.record(b + 0x90 + 4 * i) for i in range(5)]
        raw = {f"b{o:02x}": data[b + o] for o in range(0x3C, TEAM_STRIDE) if o not in range(0x48, 0x54)
               and o not in range(0x74, 0x78) and o not in range(0x7C, 0x80) and o not in range(0x90, 0xA4)}
        team_rows.append({"slot": t, "nickname": v.string(b + 0x48), "abbr": v.string(b + 0x4C), "id": v.string(b + 0x50),
                          "city": v.string(b + 0x74), "roster_records": " ".join(map(str, roster)),
                          "starter_records": " ".join(str(s) for s in starters), "n_players": len(roster),
                          **raw, "hex": data[b:b + TEAM_STRIDE].hex()})

    rows = []
    for r in range(PLAYER_COUNT):
        b = PLAYER_BASE + r * PLAYER_STRIDE
        rec = data[b:b + PLAYER_STRIDE]
        t, i = owner.get(r, ("", ""))
        row = {
            "record": r, "team_slot": t, "team": team_rows[t]["nickname"] if t != "" else "", "roster_idx": i,
            "first": v.string(b + 0x10), "last": v.string(b + 0x0C), "nickname": v.string(b + 0x24),
            "birthday": v.string(b + 0x28), "jersey": rec[0x16], "pos": rec[0x17], "height_in": rec[0x31],
            "weight_lb": struct.unpack_from("<H", rec, 0x34)[0], "years_pro": rec[0x41],
        }
        row.update({f"u{o:02x}": rec[o] for o in UNKNOWN_BYTES})
        row["hex"] = rec.hex()
        rows.append(row)

    for name, rs in (("players_unknown.csv", rows), ("teams_unknown.csv", team_rows)):
        with open(out / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rs[0]))
            w.writeheader()
            w.writerows(rs)
    ref = sum(1 for r in rows if r["team_slot"] != "")
    print(f"{len(rows)} player records ({ref} on a team), {len(team_rows)} teams, {len(UNKNOWN_BYTES)} unknown byte columns -> {out}")


if __name__ == "__main__":
    main()
