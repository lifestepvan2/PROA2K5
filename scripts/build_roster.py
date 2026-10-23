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
from rating_map_2k5 import ATTR_OFFSETS, DUNK_FLAG, EXTRA_BYTE_COLS, NEUTRAL_BYTES, dunk_flag, read_attrs  # noqa: E402
from overall_model import predict_overall  # noqa: E402
import skin_brighten  # noqa: E402

CARD_DIR = "/BESLES-53022Roster1/"
DEFAULT_CARD = r"C:\Users\Sebastian\Documents\PCSX2\memcards\Mcd001.ps2"

# --- payload layout (see docs/roster_payload_format.md) -------------------
PLAYER_BASE, PLAYER_STRIDE, PLAYER_COUNT = 0x64F4, 0x94, 0x318
P_LAST, P_FIRST, P_NICK, P_BDAY = 0xC, 0x10, 0x24, 0x28
P_JERSEY, P_POS, P_HEIGHT, P_WEIGHT, P_YEARS = 0x16, 0x17, 0x31, 0x34, 0x41  # weight is u16
P_PID = 0x4  # u16 player-model id (p<ID>h/a.iff: face, body, ...), duplicated at +6
P_SKIN = 0x69  # skin tone 0-5: selects the legs00-05 texture (face/neck/arm follow the pid instead)

# Accessories (verified in game, see docs/player_record_layout.md): record bytes holding an item index, 0 = none.
# column -> (offset, {preset: item index}); presets 1/2 are the looks found best, any other number >= 3 is used as a raw item index
ACC_COLS = {
    "wrist_l": (0x75, {1: 7, 2: 3}),   # wristband / long forearm tape
    "wrist_r": (0x76, {1: 7, 2: 3}),
    "arm_l": (0x77, {1: 11, 2: 6}),    # small band above the elbow / large elbow brace
    "arm_r": (0x78, {1: 11, 2: 6}),
    "knee_l": (0x7E, {1: 14, 2: 6}),   # small knee tape / knee brace
    "knee_r": (0x7F, {1: 14, 2: 6}),
}
ACC_HEADBAND = {1: 0, 2: 2}  # headband (0x67 = 0 switches it on) -> style byte 0x62 (2 = slightly larger)
ACC_NONE = {0x61: 255, 0x62: 0, 0x64: 255, 0x65: 255, 0x66: 255, 0x67: 255, 0x75: 0, 0x76: 0, 0x77: 0, 0x78: 0,
            0x79: 0, 0x7A: 0, 0x7E: 0, 0x7F: 0}  # every accessory byte "off"
ACC_FIELDS = ["proa_id", "team", "first", "last", "headband"] + list(ACC_COLS)
P_HAND, P_SIZE_INT, P_FAME = 0x2E, 0x30, 0x32  # right-handed flag, height-correlated trait, fame (10-44)
TEAM_BASE, TEAM_STRIDE = 0x11F0, 0x124
ROSTER_SLOTS = 15
T_NICK, T_ABBR, T_CITY_A, T_CITY_B = 0x48, 0x4C, 0x74, 0x7C
T_STARTERS = 0x90
ARENA_BASE, ARENA_STRIDE = 0xC8, 0x30  # venue table: name ptr, +8 venue city ptr, +0xC "sNNN" (NBA slot number) ptr
A_NAME, A_CITY, A_ID = 0, 8, 0xC
GAP = (0x6663C, 0x675DC)  # zero gap before the string pool
POOL_MIN = 0x675DC
FACE_CSV = ROOT / "data/texture_map/record_faces.csv"
MIN_FACE_SCORE = 0.87
NBA_RECORDS = 395  # records 0-394 are NBA-team players; 395+ are legend-team players and unused dummies
LEGEND_TEAMS = range(32, 50)
FIRST_FREE_TEAM = 30  # NBA slots 0-29; ProA teams sit on the slots of data/team_slots.csv, the others donate players if needed

REF_YEAR = 2026  # "years pro" is not in the data: estimated from the birth year
POS = {"PG": 0, "SG": 1, "SF": 2, "PF": 3, "C": 4}
TRANSLIT =  {"Ã¤": "ae", "Ã¶": "oe", "Ã¼": "ue", "Ã„": "Ae", "Ã–": "Oe", "Ãœ": "Ue", "ÃŸ": "ss"}


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
        if name.startswith("_"):  # helper sheets such as _Overall_Model
            continue
        rows = list(wb[name].iter_rows(values_only=True))
        hdr, rows = rows[0], rows[1:]
        players = []
        for r in rows:
            if not r[1]:
                continue
            rowd = dict(zip(hdr, r))
            attrs = read_attrs(rowd)
            pos = POS.get(str(r[2]), 2)
            ovr = predict_overall(pos, attrs, _num(rowd.get("Height"), 1.96), _num(rowd.get("Weight"), 92))
            players.append({
                "attrs": attrs, "rowd": rowd,
                "first": str(r[0] or ""), "last": str(r[1] or ""), "pos": pos,
                "jersey": r[4], "ovr": ovr if ovr is not None else sum(attrs.values()) / len(attrs),
                "proa_id": r[hdr.index("ProA ID")] if "ProA ID" in hdr else None,
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
    buf[off + DUNK_FLAG] = dunk_flag(p["attrs"]["Dunk"])
    for col, o in EXTRA_BYTE_COLS.items():
        if isinstance(row.get(col), (int, float)):
            buf[off + o] = int(max(0, min(99, row[col])))


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


def load_skin_tones():
    """{pid: skin tone byte (record +0x69)} of the original NBA records; legs follow this byte, so a cast player needs the tone of
    the model he borrows. Pids of the light-arm reserve (skin_brighten.py) are recoloured light, so they get the light tone."""
    tones = {int.from_bytes(b[4:6], "little"): b[P_SKIN]
             for b in (bytes.fromhex(r["hex"]) for r in csv.DictReader(open(ROOT / "data/nba_defaults/players_unknown.csv", encoding="utf-8"))
                       if r["team_slot"] and int(r["team_slot"]) < 39)}
    tones.update({p: skin_brighten.LIGHT_TONE for p in skin_brighten.reserved_pids()})
    return tones


def load_accessories(path):
    """{proa_id: csv row} from data/accessories.csv (hand-edited; blank/0 = none)."""
    if not Path(path).exists():
        return {}
    return {r["proa_id"]: r for r in csv.DictReader(open(path, encoding="utf-8-sig")) if r.get("proa_id")}


def _acc_val(row, col):
    v = (row.get(col) or "").strip()
    if not v:
        return 0
    try:
        return int(float(v))
    except ValueError:
        raise SystemExit(f"accessories.csv: bad value {v!r} in column {col} (proa_id {row.get('proa_id')})")


def apply_accessories(buf, off, row):
    """No accessories by default; the csv row of the player switches items on."""
    for o, v in ACC_NONE.items():
        buf[off + o] = v
    if not row:
        return
    hb = _acc_val(row, "headband")
    if hb:
        buf[off + 0x67] = 0
        buf[off + 0x62] = ACC_HEADBAND.get(hb, hb)
    for col, (o, presets) in ACC_COLS.items():
        v = _acc_val(row, col)
        if v:
            buf[off + o] = presets.get(v, v)


def write_accessories_csv(path, existing, players):
    """Appends rows for players that are not in the csv yet; existing rows (hand edits) are never touched."""
    new = [{"proa_id": str(pid), "team": team, "first": first, "last": last} for pid, team, first, last in players
           if pid is not None and str(pid) not in existing]
    if not new and Path(path).exists():
        return 0
    rows = list(existing.values()) + new
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, ACC_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(new)


def load_pids(path):
    """{proa_id: pid} from the face_match map: override_pid if set, else the automatic pid. Pids must be NBA player
    models that exist on the disc (the ones of NBA-team records in data/nba_defaults/players_unknown.csv)."""
    if not Path(path).exists():
        return {}
    safe = set()
    for r in csv.DictReader(open(ROOT / "data/nba_defaults/players_unknown.csv", encoding="utf-8")):
        if r["team_slot"] and int(r["team_slot"]) < 39:
            safe.add(int.from_bytes(bytes.fromhex(r["hex"])[4:6], "little"))
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        v = (r.get("override_pid") or "").strip() or (r.get("pid") or "").strip()
        if not v:
            continue
        if int(v) not in safe:
            raise SystemExit(f"{path}: pid {v} of {r['first']} {r['last']} is not a known NBA player model")
        out[r["proa_id"]] = int(v)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(ROOT / "data/roster_test/payload_current.bin"))
    ap.add_argument("--proa", default=str(ROOT / "proa_scraped.xlsx"))
    ap.add_argument("--pids", default=str(ROOT / "data/face_match/proa_pid_map.csv"),
                    help="csv from face_match.py: proa_id, pid (automatic), override_pid (manual, wins) -> player model")
    ap.add_argument("--teams", default=str(ROOT / "data/proa_teams.csv"))
    ap.add_argument("--slots", default=str(ROOT / "data/team_slots.csv"), help="csv: sheet,nba_slot (final ProA team -> NBA slot mapping)")
    ap.add_argument("--arenas", default=str(ROOT / "data/proa_arenas.csv"), help="csv: sheet,arena (home arena names)")
    ap.add_argument("--overrides", default=str(ROOT / "data/overrides.csv"),
                    help="csv: sheet,orig_last,first,last (manual name overrides)")
    ap.add_argument("--accessories", default=str(ROOT / "data/accessories.csv"),
                    help="csv: proa_id, headband, wrist_l/r, arm_l/r, knee_l/r (hand-edited; new players are appended)")
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

    pid_of = load_pids(a.pids)
    skin_of = load_skin_tones()
    acc_of = load_accessories(a.accessories)
    acc_seen = []
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
            apply_accessories(pl.d, rec_off(r), acc_of.get(str(p["proa_id"])))
            acc_seen.append((p["proa_id"], tr["sheet"], p["first"], p["last"]))
            pid = pid_of.get(str(p["proa_id"]))
            if pid is None:
                notes.append(f"{tr['sheet']}: '{p['first']} {p['last']}' has no pid in {Path(a.pids).name}, keeps the model of record {r}")
                pid = struct.unpack_from("<H", pl.d, rec_off(r) + P_PID)[0]
            struct.pack_into("<HH", pl.d, rec_off(r) + P_PID, pid, pid)
            if pid in skin_of:
                pl.d[rec_off(r) + P_SKIN] = skin_of[pid]
            player_rows.append({"team_slot": k, "proa_team": i_team, "sheet": tr["sheet"], "slot": i, "record": r, "offset": hex(rec_off(r)),
                                "first": first, "last": last, "orig_first": p["first"], "orig_last": p["last"],
                                "pos": p["pos"], "jersey": p["jersey"], "ovr": round(p["ovr"], 1), "proa_id": p["proa_id"],
                                "starter": i < 5, "pid": pid, "note": note})
            if note:
                notes.append(f"{tr['sheet']}: '{p['first']} {p['last']}' -> '{first} {last}' ({note})")

    n_new = write_accessories_csv(a.accessories, acc_of, acc_seen)
    if n_new:
        notes.append(f"{Path(a.accessories).name}: {n_new} new players appended (no accessories until edited)")

    # home arenas: venue rows are keyed by the "sNNN" string (NBA team slot), not by row index
    venue_row = {}
    for r in range(70):
        f = ARENA_BASE + ARENA_STRIDE * r + A_ID
        if f + 4 > POOL_MIN:
            break
        try:
            tag = pl.str_at(f)
        except struct.error:
            break
        if re.fullmatch(r"s\d{3}", tag):
            venue_row[int(tag[1:])] = r
    arenas = {}
    if Path(a.arenas).exists():
        arenas = {r["sheet"]: r["arena"] for r in csv.DictReader(open(a.arenas, encoding="utf-8")) if r["arena"].strip()}
    arena_out = []
    for tr in team_rows:
        name = arenas.get(tr["sheet"])
        if not name:
            notes.append(f"{tr['sheet']}: no arena in {a.arenas}, keeping original")
            continue
        row = venue_row[tr["nba_slot"]]
        base = ARENA_BASE + ARENA_STRIDE * row
        old = pl.str_at(base + A_NAME)
        assignments.append((base + A_NAME, name))
        assignments.append((base + A_CITY, tr["city"]))
        arena_out.append({"slot": tr["nba_slot"], "row": row, "sheet": tr["sheet"], "old_arena": old, "arena": name})

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
    for name, rows in (("player_map.csv", player_rows), ("team_map.csv", team_out), ("arena_map.csv", arena_out)):
        if not rows:
            continue
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
