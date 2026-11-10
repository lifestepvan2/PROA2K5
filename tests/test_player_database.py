import contextlib
import csv
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import player_database as db
import scrape_proa_roster as scraper
from build_roster import P_HAND, P_YEARS, apply_accessories, write_record_fields
from crop_headshots import placeholder_hashes, KNOWN_PLACEHOLDERS


def workbook():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Example"
    ws.append(db.PLAYER_COLUMNS)
    row = {**dict.fromkeys(db.SHEET_COLUMNS, 50), **dict.fromkeys(db.ACCESSORIES, 0),
           "First Name": "Test", "Last Name": "Player", "Position": "PG", "Secondary Position": "N/A",
           "Birth Year": 2000, "Birth Month": 1, "Birth Day": 2, "Height": 1.90, "Weight": 85,
           "College": "", "Shooting Hand": 1, "Skin Tone": 0, "ProA ID": 123, "Years Pro": 1}
    ws.append([row[c] for c in db.PLAYER_COLUMNS])
    return wb


class PlayerDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def csv_file(self, columns, rows):
        path = self.root / "manual.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, columns)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_sanitization_transliterates_and_shortens_before_workbook(self):
        self.assertEqual(db.sanitize_names("  Jürgen ", "Groß"), ("Juergen", "Gross"))
        first, last = db.sanitize_names("Verylongfirstname Second", "First Second Verylonglastname Jr.")
        self.assertEqual(first, "Verylongfirs")
        self.assertEqual(last, "Verylonglast")
        self.assertEqual(db.sanitize_names(first, last), (first, last))

    def test_sparse_overrides_zero_clear_team_noop_and_immutable_csv(self):
        path = self.csv_file(db.OVERRIDE_COLUMNS, [
            {"Team": "Not this team", "ProA ID": 123, "First Name": "Preferred",
             "Shooting Hand": "0", "headband": "0", "College": db.CLEAR},
            {"Team": "Future", "ProA ID": 999, "Dunk": "99"},
        ])
        before = path.read_bytes()
        wb = workbook()
        with contextlib.redirect_stdout(io.StringIO()) as log:
            db.apply_overrides(wb, db.load_overrides(path))
        ws = wb["Example"]
        row = dict(zip(db.PLAYER_COLUMNS, next(ws.iter_rows(min_row=2, values_only=True))))
        self.assertEqual(row["First Name"], "Preferred")
        self.assertEqual(row["Last Name"], "Player")
        self.assertEqual(row["Shooting Hand"], 0)
        self.assertEqual(row["College"], "")
        self.assertEqual(ws.title, "Example")
        self.assertIn("999", log.getvalue())
        self.assertEqual(before, path.read_bytes())
        wb.close()

    def test_manual_command_is_idempotent_and_never_rewrites_sources(self):
        wb = workbook()
        book = self.root / "players.xlsx"
        wb.save(book)
        wb.close()
        overrides = self.csv_file(db.OVERRIDE_COLUMNS, [
            {"ProA ID": 123, "Shooting Hand": "0", "Dunk": "99"},
        ])
        blacklist = self.root / "blacklist.csv"
        blacklist.write_text("Team,ProA ID,Reason\n", encoding="utf-8")
        before = (overrides.read_bytes(), blacklist.read_bytes())
        args = ["player_database.py", "--workbook", str(book), "--overrides", str(overrides),
                "--blacklist", str(blacklist)]
        for _ in range(2):
            with patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()):
                db.main()
            check = openpyxl.load_workbook(book)
            ws = check["Example"]
            values = dict(zip([c.value for c in ws[1]], next(ws.iter_rows(min_row=2, values_only=True))))
            self.assertEqual((values["Shooting Hand"], values["Dunk"]), (0, 99))
            self.assertTrue(values["Overall"].startswith("="))
            check.close()
        self.assertEqual((overrides.read_bytes(), blacklist.read_bytes()), before)

    def test_duplicate_ids_unknown_headers_invalid_values_rejected(self):
        for columns, rows in [
            (["ProA ID"], [{"ProA ID": 123}, {"ProA ID": 123}]),
            (["ProA ID", "Overall"], [{"ProA ID": 123, "Overall": 99}]),
            (["ProA ID", "Shooting Hand"], [{"ProA ID": 123, "Shooting Hand": 2}]),
            (["ProA ID", "Dunk"], [{"ProA ID": 123, "Dunk": 100}]),
            (["ProA ID", "Last Name"], [{"ProA ID": 123, "Last Name": "LongerThanTwelve"}]),
            (["ProA ID", "Last Name"], [{"ProA ID": 123, "Last Name": "Müller"}]),
            (["ProA ID"], [{"ProA ID": "123.0"}]),
        ]:
            with self.subTest(columns=columns, rows=rows), self.assertRaises(ValueError):
                db.load_overrides(self.csv_file(columns, rows))
        for value in (True, 1.5, float("nan"), -1):
            with self.assertRaises(ValueError):
                db.field_value("headband", value)

    def test_blacklist_removes_cached_players_before_stat_requests(self):
        players = [{"proa_id": pid, "first_name": "A", "last_name": "B", "nationality": "DE"} for pid in (1, 2)]
        with patch.object(scraper, "fetch_html", return_value=""), \
                patch.object(scraper, "discover_team_ids", return_value=[435]), \
                patch.object(scraper, "load_json_cache", return_value=players), \
                patch.object(scraper, "save_json_cache"), \
                patch.object(scraper, "collect_player_seasons", return_value={}) as collect, \
                contextlib.redirect_stdout(io.StringIO()):
            result = scraper.scrape_all("2026_2027", blacklist={1})
        self.assertEqual([p["proa_id"] for p in result[435]], [2])
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(collect.call_args.args[0], 2)

    def test_manual_blacklist_removes_rows_and_duplicate_ids_fail(self):
        wb = workbook()
        with contextlib.redirect_stdout(io.StringIO()):
            db.apply_overrides(wb, {}, blacklist={123})
        self.assertEqual(wb.active.max_row, 1)
        wb.close()
        wb = workbook()
        wb.active.append(list(next(wb.active.iter_rows(min_row=2, values_only=True))))
        with self.assertRaises(ValueError):
            db.apply_overrides(wb, {})
        wb.close()

    def test_old_roster_cache_is_upgraded_from_cached_html(self):
        old = [{"proa_id": 123, "first_name": "A", "last_name": "B"}]
        upgraded = [{**old[0], "nationality": "DE"}]
        with patch.object(scraper, "fetch_html", return_value="cached team HTML"), \
                patch.object(scraper, "discover_team_ids", return_value=[435]), \
                patch.object(scraper, "load_json_cache", return_value=old), \
                patch.object(scraper, "parse_kader_page", return_value=upgraded) as parse, \
                patch.object(scraper, "save_json_cache"), \
                contextlib.redirect_stdout(io.StringIO()):
            result = scraper.scrape_all("2026_2027", no_stats=True, blacklist=set())
        parse.assert_called_once_with("cached team HTML")
        self.assertEqual(result[435][0]["nationality"], "DE")

    def test_spreadsheet_generation_applies_names_defaults_and_overrides(self):
        output = self.root / "output.xlsx"
        players = {435: [{"proa_id": 123, "first_name": "Jürgen", "last_name": "Groß",
                          "position": "PG", "jersey_number": 0, "birth_year": 2000,
                          "birth_month": 1, "birth_day": 1, "height_m": 1.9, "weight_kg": 85,
                          "nationality": "DE"}]}
        with contextlib.redirect_stdout(io.StringIO()):
            scraper.write_excel(players, output, db.SHEET_COLUMNS, headshot_map={123: 9000},
                                overrides={123: {"Dunk": 99, "Shooting Hand": 0, "College": "Example"}})
        wb = openpyxl.load_workbook(output)
        ws = wb["Dragons"]
        headers = [c.value for c in ws[1]]
        row = dict(zip(headers, next(ws.iter_rows(min_row=2, values_only=True))))
        self.assertEqual((row["First Name"], row["Last Name"]), ("Juergen", "Gross"))
        self.assertEqual((row["Dunk"], row["Shooting Hand"]), (99, 0))
        self.assertEqual(row["College"], "Example")
        self.assertEqual(row["headband"], 0)
        self.assertTrue(row["Overall"].startswith("="))
        self.assertEqual(headers[headers.index("Close Shot"):headers.index("Headshot ID")], list(db.ALL_ATTRS))
        wb.close()

    def test_nat_is_parsed_next_to_pos_and_populates_college(self):
        html = """<table><tr><th>#</th><th>Vorname</th><th>Nachname</th><th>Geb</th>
        <th>m</th><th>kg</th><th>Pos</th><th>Nat</th></tr>
        <tr><td>9</td><td><a href="/teams/kader/spieler/123">Test</a></td>
        <td><a href="/teams/kader/spieler/123">Player</a></td><td>02.01.2000</td>
        <td>1,90</td><td>85</td><td>PG</td><td><span class="flag-icon flag-icon-de"></span>
        <span class="flag-icon flag-icon-us"></span></td></tr></table>"""
        players = scraper.parse_kader_page(html)
        self.assertEqual(players[0]["nationality"], "DE / US")
        text_html = html.replace('<span class="flag-icon flag-icon-de"></span>', "DE").replace(
            '<span class="flag-icon flag-icon-us"></span>', "")
        self.assertEqual(scraper.parse_kader_page(text_html)[0]["nationality"], "DE")
        output = self.root / "nat.xlsx"
        with contextlib.redirect_stdout(io.StringIO()):
            scraper.write_excel({435: players}, output, db.SHEET_COLUMNS, headshot_map={123: 9000}, overrides={})
        wb = openpyxl.load_workbook(output)
        ws = wb["Dragons"]
        row = dict(zip([c.value for c in ws[1]], next(ws.iter_rows(min_row=2, values_only=True))))
        self.assertEqual(row["College"], "Germany / United States")
        wb.close()

    def test_nationalities_expand_in_english_with_order_and_deduplication(self):
        self.assertEqual(db.expand_nationality("LT / US / DE / DK"),
                         "Lithuania / United States / Germany / Denmark")
        self.assertEqual(db.expand_nationality("de / us / DE"), "Germany / United States")
        self.assertEqual(db.expand_nationality(""), "")
        self.assertEqual(db.expand_nationality(None), "")
        with self.assertRaisesRegex(ValueError, "Unknown nationality.*ZZ"):
            db.expand_nationality("DE / ZZ")

    def test_college_text_rejects_controls_and_non_bmp_without_shortening(self):
        for value in ("A\0B", "A\nB", "A\tB", "A\x7fB", "A\ud800B", "A\U0001f3c0B"):
            with self.subTest(value=repr(value)), self.assertRaisesRegex(ValueError, "College"):
                db.field_value("College", value)
        self.assertEqual(db.field_value("College", "Universität Köln"), "Universität Köln")
        self.assertEqual(db.field_value("College", "A" * 1000), "A" * 1000)

    def test_hand_and_accessories_are_written_from_workbook(self):
        row = {**dict.fromkeys(db.ALL_ATTRS, 60), "Years Pro": 1, "Shooting Hand": 0,
               "Height": 1.9, "Weight": 85}
        data = bytearray(0x94)
        write_record_fields(data, 0, {"rowd": row, "jersey": 0, "pos": 0, "attrs": row})
        self.assertEqual((data[P_HAND], data[P_YEARS]), (0, 1))
        apply_accessories(data, 0, {"headband": 2, "wrist_l": 1, "knee_r": 6})
        self.assertEqual((data[0x67], data[0x62], data[0x75], data[0x7F]), (0, 2, 7, 6))
        apply_accessories(data, 0, {"headband": 0, "wrist_l": 0})
        self.assertEqual((data[0x67], data[0x75]), (255, 0))

    def test_placeholder_report_names_ids_and_manual_destination(self):
        portrait_dir = self.root / "portraits"
        portrait_dir.mkdir()
        for pid in (1, 2, 3):
            (portrait_dir / f"{pid}.jpg").write_bytes(b"shared placeholder")
        (portrait_dir / "4.jpg").write_bytes(b"real portrait")
        players = {435: [{"proa_id": i, "first_name": "Test", "last_name": f"Player{i}"} for i in range(1, 6)]}
        with patch.object(scraper, "_cache_root", return_value=self.root), \
                patch.object(scraper, "PROJECT_ROOT", self.root), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            missing = scraper.report_missing_portraits(players, "2026_2027")
        self.assertEqual(missing, [1, 2, 3, 5])
        self.assertIn("Player1", log.getvalue())
        self.assertIn("512x512", log.getvalue())
        self.assertIn(str(self.root / "assets" / "PS_out"), log.getvalue())
        self.assertTrue(KNOWN_PLACEHOLDERS <= placeholder_hashes(portrait_dir))

    def test_single_known_placeholder_and_existing_manual_portrait(self):
        portrait_dir = self.root / "portraits"
        portrait_dir.mkdir()
        (portrait_dir / "1.jpg").write_bytes(b"known placeholder")
        manual = self.root / "assets" / "PS_out" / "1.png"
        manual.parent.mkdir(parents=True)
        manual.write_bytes(b"manual portrait")
        players = {435: [{"proa_id": 1, "first_name": "A", "last_name": "B"}]}
        with patch("crop_headshots.KNOWN_PLACEHOLDERS", {hashlib.md5(b"known placeholder").hexdigest()}), \
                patch.object(scraper, "_cache_root", return_value=self.root), \
                patch.object(scraper, "PROJECT_ROOT", self.root), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            missing = scraper.report_missing_portraits(players, "2026_2027")
        self.assertEqual(missing, [1])
        self.assertIn("manual portrait already present", log.getvalue())
        self.assertEqual(manual.read_bytes(), b"manual portrait")


if __name__ == "__main__":
    unittest.main()
