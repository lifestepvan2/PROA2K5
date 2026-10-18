"""Build a ProA roster payload for NBA 2K5 (PS2) from the cached ProA data.

Takes the roster-save payload (extracted from the memory card), replaces team
names and the player names/rosters/starters of the 18 NBA team slots in data/team_slots.csv (12-29) with
the 18 ProA teams, repacks the string pool (ref-counted, first/best-fit
allocator, size unchanged), recomputes CRC32 into EXTRA and optionally writes
the result into the virtual memory card (PCSX2 must be closed).

Usage:
  python scripts/build_roster.py                      # dry run: payload + reports only
  python scripts/build_roster.py --card CARD          # also write the card
Reports: data/roster_build/{payload_proa.bin,extra_proa.bin,player_map.csv,team_map.csv,report.md}
Payload layout: see docs/roster_payload_format.md
"""
import argparse
import collections
import csv
import re
import struct
import sys
import unicodedata
import zlib
from pathlib import Path

import openpyxl

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from rating_map_2k5 import ATTR_OFFSETS, DUNK_FLAG, NEUTRAL_BYTES, convert, dunk_flag  # noqa: E402

CARD_DIR = "/BESLES-53022Roster1/"
DEFAULT_CARD = r"C:\Users\Sebastian\Documents\PCSX2\memcards\Mcd001.ps2"

# --- payload layout (see docs/roster_payload_format.md) -------------------
PLAYER_BASE, PLAYER_STRIDE, PLAYER_COUNT = 0x64F4, 0x94, 0x318
P_LAST, P_FIRST, P_NICK, P_BDAY = 0xC, 0x10, 0x24, 0x28
P_JERSEY, P_POS, P_HEIGHT, P_WEIGHT, P_YEARS = 0x16, 0x17, 0x31, 0x34, 0x41  # weight is u16
P_HAND, P_SIZE_INT, P_FAME = 0x2E, 0x30, 0x32  # right-handed flag, height-correlated trait, fame (10-44)
TEAM_BASE, TEAM_STRIDE = 0x11F0, 0x124
ROSTER_SLOTS = 15
T_NICK, T_ABBR, T_CITY_A, T_CITY_B = 0x48, 0x4C, 0x74, 0x7C
T_STARTERS = 0x90
GAP = (0x6663C, 0x675DC)  # zero gap before the string pool
POOL_MIN = 0x675DC
FACE_CSV = ROOT / "data/texture_map/record_faces.csv"
MIN_FACE_SCORE = 0.87
NBA_RECORDS = 395  # records 0-394 are NBA-team players; 395+ are legend-team players and unused dummies
LEGEND_TEAMS = range(32, 50)
FIRST_FREE_TEAM = 30  # NBA slots 0-29; ProA teams sit on the slots of data/team_slots.csv, the others donate players if needed

REF_YEAR = 2026  # "years pro" is not in the data: estimated from the birth year
POS = {"PG": 0, "SG": 1, "SF": 2, "PF": 3, "C": 4}
RATING_COLS = range(11, 45)
TRANSLIT = {"Ã¤": "ae", "Ã¶": "oe", "Ã¼": "ue", "Ã„": "Ae", "Ã–": "Oe", "Ãœ": "Ue", "ÃŸ": "ss"}


def clean(text, keep_umlauts):
    text = str(text or "").strip()
    if not keep_umlauts:
        text = "".join(TRANSLIT.get(c, c) for c in text)
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip()


SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def fit_names(first, last, max_first, max_last):
    """Shortening ladder. Returns (first, last, note)."""
    note = ""
    if len(first) > max_first:
        tok = first.split(" ")[0]
        first = tok[:max_first]
        note += "first-trunc "
    if len(last) > max_last:
        toks = [t for t in last.split(" ") if t.lower() not in SUFFIXES] or last.split(" ")
        cand = " ".join(toks)
        i = 0
        while len(cand) > max_last and i < len(toks) - 1:
            i += 1
            cand = " ".join(toks[i:])
        last = cand[:max_last]
        note += "last-shortened "
    return first, last, note.strip()


class Payload:
    def __init__(self, data):
        self.d = bytearray(data)
        self.refs = collections.defaultdict(set)  # string target -> referrer field offsets
        for o in range(0, len(self.d) - 3, 4):
            v = struct.unpack_from("<i", self.d, o)[0]
            if v & 1:
                t = o + v - 1
                if POOL_MIN <= t < len(self.d) - 2 and t % 2 == 0 and o < POOL_MIN:
                    rel = o - PLAYER_BASE
                    if 0 <= rel < PLAYER_COUNT * PLAYER_STRIDE and rel % PLAYER_STRIDE not in (P_LAST, P_FIRST, P_NICK, P_BDAY):
                        continue  # stat bytes that merely look like pointers
                    self.refs[t].add(o)
        self.free = [GAP]
        assert not any(self.d[GAP[0]:GAP[1]]), "gap not zero"

    def target(self, field):
        return field + struct.unpack_from("<i", self.d, field)[0] - 1

    def set_ptr(self, field, target):
        struct.pack_into("<i", self.d, field, target - field + 1)

    def read_str(self, off):
        e = off
        while e + 2 <= len(self.d) and self.d[e:e + 2] != b"\0\0":
            e += 2
        return self.d[off:e].decode("utf-16-le", "replace")

    def str_at(self, field):
        return self.read_str(self.target(field))

    def snapshot(self):
        return {f: self.read_str(t) for t, fs in self.refs.items() for f in fs}

    def release(self, field):
        t = self.target(field)
        self.refs[t].discard(field)
        return t

    def free_string(self, t):
        n = len(self.read_str(t)) * 2 + 2
        if n == 2:
            return 0  # empty strings may alias another string's terminator
        if self.refs[t] or any(t < r < t + n and self.refs[r] for r in range(t + 2, t + n, 2) if r in self.refs):
            return 0
        self.d[t:t + n] = bytes(n)
        self.free.append((t, t + n))
        self.free.sort()
        merged = []
        for s, e in self.free:
            if merged and merged[-1][1] >= s:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        self.free = merged
        return n

    def alloc(self, n):
        best = None
        for i, (s, e) in enumerate(self.free):
            if e - s >= n and (best is None or e - s < self.free[best][1] - self.free[best][0]):
                best = i
        if best is None:
            raise MemoryError(f"string pool exhausted (need {n})")
        s, e = self.free[best]
        self.free[best] = (s + n, e)
        return s

    def free_bytes(self):
        return sum(e - s for s, e in self.free)


def load_proa(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    teams = {}
    for name in wb.sheetnames:
        rows = list(wb[name].iter_rows(values_only=True))
        hdr, rows = rows[0], rows[1:]
        players = []
        for r in rows:
            if not r[1]:
                continue
            rt = [v for v in r[11:45] if isinstance(v, (int, float))]
            rowd = dict(zip(hdr, r))
            players.append({
                "attrs": convert(rowd), "rowd": rowd,
                "first": str(r[0] or ""), "last": str(r[1] or ""), "pos": POS.get(str(r[2]), 2),
                "jersey": r[4], "ovr": sum(rt) / len(rt) if rt else 0, "proa_id": r[hdr.index("ProA ID")] if "ProA ID" in hdr else None,
                "row": r,
            })
        teams[name] = players
    return teams


def _num(v, default):
    return v if isinstance(v, (int, float)) else default


def birthday_text(row):
    y, m, d = (_num(row.get(k), None) for k in ("Birth Year", "Birth Month", "Birth Day"))
    if None in (y, m, d):
        return "1/1/95"
    return f"{int(m)}/{int(d)}/{int(y) % 100:02d}"


def write_record_fields(buf, off, p):
    """Jersey, position, size, years pro and the 19 ratings (see docs/player_record_layout.md)."""
    row = p["rowd"]
    buf[off + P_JERSEY] = int(_num(p["jersey"], 0)) & 0xFF
    buf[off + P_POS] = p["pos"]
    buf[off + P_HEIGHT] = int(round(_num(row.get("Height"), 1.96) * 39.3701))
    struct.pack_into("<H", buf, off + P_WEIGHT, int(round(_num(row.get("Weight"), 92) * 2.20462)))
    by = _num(row.get("Birth Year"), 1995)
    buf[off + P_YEARS] = max(1, min(21, REF_YEAR - int(by) - 19))
    hand = row.get("Right Handed")  # optional manual column; default right-handed
    buf[off + P_HAND] = 0 if hand in (0, False, "0", "L", "l", "left", "Left") else 1
    buf[off + P_SIZE_INT] = max(60, min(95, int(round(0.9856 * buf[off + P_HEIGHT] + 0.70))))
    buf[off + P_FAME] = p.get("fame", 20)
    for k, o in ATTR_OFFSETS.items():
        buf[off + o] = p["attrs"][k]
    for o, v in NEUTRAL_BYTES.items():
        buf[off + o] = v
    buf[off + DUNK_FLAG] = dunk_flag(p["attrs"]["dunk"])


def order_roster(players):
    """Starters (one per position, best overall) first, then the rest by overall."""
    left = sorted(players, key=lambda p: -p["ovr"])
    starters = []
    for pos in range(5):
        c = next((p for p in left if p["pos"] == pos), None)
        if c:
            starters.append(c)
            left.remove(c)
    while len(starters) < 5 and left:
        starters.append(left.pop(0))
    return starters + left


def read_roster(pl, team):
    base = TEAM_BASE + team * TEAM_STRIDE
    recs = []
    for i in range(ROSTER_SLOTS):
        if not struct.unpack_from("<I", pl.d, base + 4 * i)[0] & 1:
            break
        recs.append((pl.target(base + 4 * i) - PLAYER_BASE) // PLAYER_STRIDE)
    return recs


def write_roster(pl, team, recs):
    base = TEAM_BASE + team * TEAM_STRIDE
    for i in range(ROSTER_SLOTS):
        struct.pack_into("<I", pl.d, base + 4 * i, 0)
    for i, r in enumerate(recs):
        pl.set_ptr(base + 4 * i, PLAYER_BASE + r * PLAYER_STRIDE)


def face_pool(pl):
    """Records that own an individual face texture (data/texture_map/record_faces.csv): the dump key is
    not shared with another record (placeholder / duplicated portraits) and the record is not used by a
    legend team (those stay untouched)."""
    ok = {int(r["record"]) for r in csv.DictReader(open(FACE_CSV)) if int(r["record"]) < NBA_RECORDS
          and r["shared"] == "1" and float(r["score"]) >= MIN_FACE_SCORE}
    legend = {r for t in LEGEND_TEAMS for r in read_roster(pl, t)}
    return ok - legend


def allocate_records(pl, team_players, slots):
    """Choose one face-owning player record per ProA player.
    A team first uses the records of its NBA slot; missing ones are taken from the bench of the remaining NBA
    teams (round-robin), which receive the unused records of the ProA teams in exchange (or shrink).
    Returns {team index: [record per player]}."""
    pool = face_pool(pl)
    n = len(team_players)
    own = {k: read_roster(pl, slots[k]) for k in range(n)}
    donors = {}
    for t in range(FIRST_FREE_TEAM):
        if t in slots:
            continue
        base = TEAM_BASE + t * TEAM_STRIDE
        starters = {(pl.target(base + T_STARTERS + 4 * i) - PLAYER_BASE) // PLAYER_STRIDE for i in range(5)}
        donors[t] = [r for r in reversed(read_roster(pl, t)) if r in pool and r not in starters]
    queue = []
    while any(donors.values()):
        for t in sorted(donors, reverse=True):
            if donors[t]:
                queue.append((t, donors[t].pop(0)))
    alloc, leftover, taken = {}, [], collections.defaultdict(list)
    for k in range(n):
        need = len(team_players[k])
        mine = [r for r in own[k] if r in pool]
        alloc[k] = mine[:need]
        leftover += [r for r in own[k] if r not in alloc[k]]
        while len(alloc[k]) < need:
            if not queue:
                raise SystemExit("not enough face-owning records for all ProA players")
            t, r = queue.pop(0)
            alloc[k].append(r)
            taken[t].append(r)
    for t, gone in taken.items():
        roster = read_roster(pl, t)
        for r in gone:
            roster[roster.index(r)] = leftover.pop(0) if leftover else None
        write_roster(pl, t, [r for r in roster if r is not None])
    return alloc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(ROOT / "data/roster_test/payload_current.bin"))
    ap.add_argument("--proa", default=str(ROOT / "proa_scraped.xlsx"))
    ap.add_argument("--teams", default=str(ROOT / "data/proa_teams.csv"))
    ap.add_argument("--slots", default=str(ROOT / "data/team_slots.csv"), help="csv: sheet,nba_slot (final ProA team -> NBA slot mapping)")
    ap.add_argument("--overrides", default=str(ROOT / "data/overrides.csv"),
                    help="csv: sheet,orig_last,first,last (manual name overrides)")
    ap.add_argument("--out", default=str(ROOT / "data/roster_build"))
    ap.add_argument("--card", help="write result into this memory card (PCSX2 closed!)")
    ap.add_argument("--keep-umlauts", action="store_true")
    ap.add_argument("--max-first", type=int, default=12)
    ap.add_argument("--max-last", type=int, default=12)
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pl = Payload(Path(a.base).read_bytes())
    base_snapshot = pl.snapshot()
    proa = load_proa(a.proa)
    allp = sorted((p for t in proa.values() for p in t), key=lambda p: p["ovr"])
    for i, p in enumerate(allp):
        p["fame"] = 10 + round(30 * i / max(1, len(allp) - 1))  # u32: overall percentile -> 10..40
    team_rows = list(csv.DictReader(open(a.teams, encoding="utf-8")))
    slot_of = {r["sheet"]: int(r["nba_slot"]) for r in csv.DictReader(open(a.slots, encoding="utf-8"))}
    for tr in team_rows:
        tr["nba_slot"] = slot_of[tr["sheet"]]
    slots = [tr["nba_slot"] for tr in team_rows]  # team index -> NBA slot
    assert len(set(slots)) == len(slots) and max(slots) < FIRST_FREE_TEAM, "bad data/team_slots.csv"
    overrides = {}
    if Path(a.overrides).exists():
        for r in csv.DictReader(open(a.overrides, encoding="utf-8")):
            overrides[(r["sheet"], r["orig_last"])] = (r["first"], r["last"])

    assignments = []  # (field offset, text)
    player_rows, team_out, notes = [], [], []
    rec_off = lambda i: PLAYER_BASE + i * PLAYER_STRIDE

    team_players = [order_roster(proa[tr["sheet"]][:ROSTER_SLOTS]) for tr in team_rows]
    alloc = allocate_records(pl, team_players, slots)

    for i_team, tr in enumerate(team_rows):
        k = tr["nba_slot"]
        base = TEAM_BASE + k * TEAM_STRIDE
        players = team_players[i_team]
        recs = alloc[i_team]

        # team strings: replace every referrer of the old strings
        old = {f: pl.target(base + f) for f in (T_NICK, T_ABBR, T_CITY_A, T_CITY_B)}
        new_text = {T_NICK: tr["nickname"], T_ABBR: tr["abbr"], T_CITY_A: tr["city"], T_CITY_B: tr["city"]}
        old_names = {f: pl.read_str(t) for f, t in old.items()}
        for f, t in old.items():
            for fld in sorted(pl.refs[t]):
                assignments.append((fld, new_text[f]))
        team_out.append({"slot": k, "old_nick": old_names[T_NICK], "old_abbr": old_names[T_ABBR], "old_city": old_names[T_CITY_A],
                         "nick": tr["nickname"], "abbr": tr["abbr"], "city": tr["city"], "sheet": tr["sheet"], "players": len(players)})

        # roster list + starters (pointers to player records)
        for i in range(ROSTER_SLOTS):
            struct.pack_into("<I", pl.d, base + 4 * i, 0)
        for i, r in enumerate(recs):
            pl.set_ptr(base + 4 * i, rec_off(r))
        for i in range(5):
            pl.set_ptr(base + T_STARTERS + 4 * i, rec_off(recs[i]))

        for i, (p, r) in enumerate(zip(players, recs)):
            f0, l0 = clean(p["first"], a.keep_umlauts), clean(p["last"], a.keep_umlauts)
            first, last = overrides.get((tr["sheet"], p["last"]), (None, None))
            note = "override" if first else ""
            if not first:
                first, last, note = fit_names(f0, l0, a.max_first, a.max_last)
            assignments.append((rec_off(r) + P_LAST, last))
            assignments.append((rec_off(r) + P_FIRST, first))
            assignments.append((rec_off(r) + P_NICK, ""))
            assignments.append((rec_off(r) + P_BDAY, birthday_text(p["rowd"])))
            write_record_fields(pl.d, rec_off(r), p)
            player_rows.append({"team_slot": k, "proa_team": i_team, "sheet": tr["sheet"], "slot": i, "record": r, "offset": hex(rec_off(r)),
                                "first": first, "last": last, "orig_first": p["first"], "orig_last": p["last"],
                                "pos": p["pos"], "jersey": p["jersey"], "ovr": round(p["ovr"], 1), "proa_id": p["proa_id"],
                                "starter": i < 5, "note": note})
            if note:
                notes.append(f"{tr['sheet']}: '{p['first']} {p['last']}' -> '{first} {last}' ({note})")

    # pass 1: unlink every field we are about to rewrite, free strings that lost all referrers
    free_before = pl.free_bytes()
    olds = {}
    for fld, _ in assignments:
        olds[fld] = pl.release(fld)
    freed = sum(pl.free_string(t) for t in sorted(set(olds.values())))
    # pass 2: allocate new strings (longest first, deduplicated)
    texts = sorted({t for _, t in assignments}, key=lambda s: (-len(s), s))
    placed = {}
    for t in texts:
        b = t.encode("utf-16-le") + b"\0\0"
        off = pl.alloc(len(b))
        pl.d[off:off + len(b)] = b
        placed[t] = off
    for fld, t in assignments:
        pl.set_ptr(fld, placed[t])
        pl.refs[placed[t]].add(fld)

    # integrity: every untouched pointer field still resolves to the same string
    after = {}
    for f in base_snapshot:
        if f in olds:
            continue
        after_text = pl.read_str(pl.target(f))
        if after_text != base_snapshot[f]:
            raise SystemExit(f"integrity failure at field {f:#x}: {base_snapshot[f]!r} -> {after_text!r}")
    for p in player_rows:
        o = int(p["offset"], 16)
        assert pl.str_at(o + P_LAST) == p["last"] and pl.str_at(o + P_FIRST) == p["first"]
    assert len(pl.d) == Path(a.base).stat().st_size

    data = bytes(pl.d)
    crc = struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF)
    (out / "payload_proa.bin").write_bytes(data)
    (out / "extra_proa.bin").write_bytes(crc)
    for name, rows in (("player_map.csv", player_rows), ("team_map.csv", team_out)):
        with open(out / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    long_last = sorted((len(p["last"]), p["last"], p["sheet"]) for p in player_rows)[-8:]
    rep = [
        "# build_roster report", "",
        f"- payload: {len(data)} bytes, CRC32 `{crc[::-1].hex()}`",
        f"- teams: {len(team_out)}, players: {len(player_rows)}",
        f"- string pool: free before {free_before} B, freed {freed} B, free after {pl.free_bytes()} B",
        f"- records: face-owning pool only (see player_map.csv, record_faces.csv); donor NBA teams: {FIRST_FREE_TEAM - len(team_rows)}",
        f"- longest last names: {long_last}", "",
        "## Name adjustments", *[f"- {n}" for n in notes],
    ]
    (out / "report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep[:6]))
    print(f"{len(notes)} name adjustments (see report.md)")

    if a.card:
        from mc_write import write_file, verify_card
        write_file(a.card, CARD_DIR + "BESLES-53022Roster1", data)
        write_file(a.card, CARD_DIR + "EXTRA", crc)
        print("written to", a.card)


if __name__ == "__main__":
    main()
