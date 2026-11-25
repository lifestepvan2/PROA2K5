import csv
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_roster import (PLAYER_BASE, PLAYER_COUNT, PLAYER_STRIDE, T_COUNT, T_UI_COLOURS, TEAM_BASE, TEAM_STRIDE,
                          Payload, apply_team_colours, read_roster, write_roster)
from create_baseline_jersey import load_teams
from team_palettes import DEFAULT_WS, team_colours


class TeamMetadataTests(unittest.TestCase):
    def test_ui_colours_are_independent_of_jersey_colours(self):
        buf = bytearray([0xAA] * 0x200)
        original = bytes(buf)
        row = {"sheet": "Test", "colorjersey1": "#ff0000", "colorjersey2": "#0000ff",
               "colorui1": "#00ff00", "colorui2": "A102F3"}
        apply_team_colours(buf, 0x30, row)
        self.assertEqual(buf[0x92:0x98], bytes.fromhex("00ff00a102f3"))
        self.assertEqual(buf[:0x92], original[:0x92])
        self.assertEqual(buf[0x98:], original[0x98:])

    def test_invalid_or_missing_colour_is_rejected_without_partial_write(self):
        for value in ("", "fff", "#12345g", "##123456", "12345678", None):
            with self.subTest(value=value):
                row = {"sheet": "Test", "colorui1": "#123456"}
                if value is not None:
                    row["colorui2"] = value
                buf = bytearray(0x124)
                with self.assertRaisesRegex(ValueError, "Test: colorui2"):
                    apply_team_colours(buf, 0, row)
                self.assertEqual(buf, bytearray(0x124))

    def test_roster_writes_count_byte_and_respects_record_capacity(self):
        class Stub:
            set_ptr, target = Payload.set_ptr, Payload.target

        pl = Stub()
        team = 3
        base = TEAM_BASE + team * TEAM_STRIDE
        pl.d = bytearray(PLAYER_BASE + PLAYER_COUNT * PLAYER_STRIDE)
        pl.d[base + 0x48:base + 0x4C] = b"NICK"
        pl.d[base + T_COUNT] = 13
        for recs in (list(range(10, 27)), [5, 6, 7]):
            with self.subTest(players=len(recs)):
                write_roster(pl, team, recs)
                self.assertEqual(pl.d[base + T_COUNT], len(recs))
                self.assertEqual(read_roster(pl, team), recs)
                self.assertEqual(pl.d[base + 4 * len(recs):base + 0x48], bytes(0x48 - 4 * len(recs)))
                self.assertEqual(pl.d[base + 0x48:base + 0x4C], b"NICK")
        with self.assertRaisesRegex(SystemExit, "18 players exceed"):
            write_roster(pl, team, list(range(18)))
        self.assertEqual(read_roster(pl, team), [5, 6, 7])

    def test_combined_csv_and_jersey_consumer(self):
        with (ROOT / "data" / "proa_teams.csv").open(encoding="utf-8") as file:
            reader = csv.DictReader(file)
            self.assertEqual(reader.fieldnames, [
                "sheet", "city", "nickname", "abbr", "arena", "verified",
            ])
            rows = list(reader)
        self.assertEqual(len({row["sheet"] for row in rows}), len(rows))
        jerseys = {row["sheet"]: row for row in load_teams()}
        self.assertEqual(set(jerseys), {row["sheet"] for row in rows})
        with (ROOT / "data" / "team_slots.csv").open(encoding="utf-8") as file:
            slots = {row["sheet"]: int(row["nba_slot"]) for row in csv.DictReader(file)}
        for row in rows:
            row.update(team_colours(DEFAULT_WS, slots[row["sheet"]]))
            with self.subTest(team=row["sheet"]):
                self.assertTrue(row["arena"].strip())
                self.assertIn(row["verified"], ("yes", "no"))
                for field, key in (("colorjersey1", "c1"), ("colorjersey2", "c2")):
                    self.assertEqual(bytes(jerseys[row["sheet"]][key]), bytes.fromhex(row[field].lstrip("#")))
                buf = bytearray(0x124)
                apply_team_colours(buf, 0, row)
                for field, offset in T_UI_COLOURS.items():
                    self.assertEqual(buf[offset:offset + 3], bytes.fromhex(row[field].lstrip("#")))


if __name__ == "__main__":
    unittest.main()
