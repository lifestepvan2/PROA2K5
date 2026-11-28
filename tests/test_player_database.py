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
import overrides_workbook as overrides_xlsx
import scrape as scraper
from build_roster import P_HAND, P_YEARS, apply_accessories, apply_created_appearance, write_record_fields
from crop_headshots import placeholder_hashes, KNOWN_PLACEHOLDERS
from rating_map_2k5 import HIDDEN_ATTR_OFFSETS, EXTRA_CANONICAL
from overall_data import player_extras
from overall_model import load_model, predict_overall
from overall_sheet import add_overall, MODEL_SHEET
import make_calibration
import build_site


def workbook():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Example"
    ws.append(db.PLAYER_COLUMNS)
    row = {**dict.fromkeys(db.SHEET_COLUMNS, 50), **dict.fromkeys(db.ACCESSORIES, 0),
           **dict.fromkeys(db.RAW_ACCESSORY_FIELDS),
           **dict.fromkeys(db.APPEARANCE_FIELDS),
           "First Name": "Test", "Last Name": "Player", "Position": "PG", "Secondary Position": "N/A",
           "Birth Year": 2000, "Birth Month": 1, "Birth Day": 2, "Height": 1.90, "Weight": 85,
           "College": "", "Shooting Hand": 1, "Skin Tone": 0, "ProA ID": 123, "Years Pro": 1,
           "Dunk Range": 10, "Emotion": 0, "Standing Dunk": 0}
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
             "Shooting Hand": "0", "Headband": "0", "College": db.CLEAR},
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
            (["ProA ID", "Dunk"], [{"ProA ID": 123, "Dunk": "bad"}]),
            (["ProA ID", "Dunk"], [{"ProA ID": 123, "Dunk": "nan"}]),
            (["ProA ID", "Last Name"], [{"ProA ID": 123, "Last Name": "LongerThanTwelve"}]),
            (["ProA ID", "Last Name"], [{"ProA ID": 123, "Last Name": "Müller"}]),
            (["ProA ID"], [{"ProA ID": "123.0"}]),
        ]:
            with self.subTest(columns=columns, rows=rows), self.assertRaises(ValueError):
                db.load_overrides(self.csv_file(columns, rows))
        for value in (True, 1.5, float("nan"), -1):
            with self.assertRaises(ValueError):
                db.field_value("headband", value)

    def test_numeric_csv_overrides_use_nearest_valid_value_with_warnings(self):
        path = self.csv_file(db.OVERRIDE_COLUMNS, [
            {"ProA ID": 123, "Dunk": 100, "Shooting Hand": -3, "Consistency": 70,
             "Standing Dunk": 25, "Height": 3.0, "Shades": 2.5, "Hair Color": 3},
        ])
        before = path.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as warnings:
            values = db.load_overrides(path)[123]
        self.assertEqual(values, {"Dunk": 99, "Shooting Hand": 0, "Consistency": 75,
                                  "Standing Dunk": 0, "Height": 2.7, "Shades": 2,
                                  "Hair Color": 3})
        text = warnings.getvalue()
        for field in ("Dunk", "Shooting Hand", "Consistency", "Standing Dunk", "Height", "Shades"):
            self.assertIn(f"ProA ID 123, {field}:", text)
        self.assertNotIn("Hair Color", text)
        self.assertEqual(before, path.read_bytes())
        with self.assertRaises(ValueError):
            db.field_value("Consistency", 70)

    def test_xlsx_dropdowns_mapping_expansion_and_numeric_correction(self):
        wb = overrides_xlsx.make_workbook([
            {"ProA ID": "123", "Shooting Hand": "0", "Hairstyle": "7",
             "Consistency": "70", "College": db.CLEAR},
        ], db.OVERRIDE_COLUMNS)
        path = self.root / "manual.xlsx"
        ws, enum = wb["Overrides"], wb["Enumerations"]
        cols = {cell.value: cell.column for cell in ws[1]}
        self.assertEqual(ws.cell(2, cols["Shooting Hand"]).value, "0 - Left")
        self.assertEqual(ws.cell(2, cols["Hairstyle"]).value, "7 - Afro")
        enum_cols = {enum.cell(1, col).value: col for col in range(1, enum.max_column + 1, 2)}
        hairstyle = enum_cols["Hairstyle"]
        enum.cell(3, hairstyle + 1, "1 - User-defined buzz")
        added = 2 + len(overrides_xlsx.enumeration_options()["Hairstyle"])
        enum.cell(added, hairstyle, 25)
        enum.cell(added, hairstyle + 1, "25 - User-defined hairstyle")
        ws.cell(2, cols["Hairstyle"], "25 - User-defined hairstyle")
        ws.cell(2, cols["Shooting Hand"], "0 - Left")
        ws.cell(2, cols["Position"], "PG - Point Guard")
        dv = next(d for d in ws.data_validations.dataValidation
                  if f"{openpyxl.utils.get_column_letter(cols['Hairstyle'])}2" in d)
        self.assertIn("OFFSET(", wb.defined_names[dv.formula1[1:]].attr_text)
        wb.save(path)
        wb.close()
        with contextlib.redirect_stderr(io.StringIO()) as warnings:
            values = db.load_overrides(path)[123]
        self.assertEqual(values["Hairstyle"], 25)
        self.assertEqual(values["Shooting Hand"], 0)
        self.assertEqual(values["Position"], "PG")
        self.assertEqual(values["Consistency"], 75)
        self.assertEqual(values["College"], "")
        self.assertIn("Consistency", warnings.getvalue())

        wb = openpyxl.load_workbook(path)
        wb["Enumerations"].cell(added, hairstyle + 1, "24 - mismatched")
        wb.save(path)
        wb.close()
        with self.assertRaisesRegex(ValueError, "invalid label"):
            db.load_overrides(path)

    def test_csv_to_xlsx_migration_preserves_effective_values(self):
        source = self.csv_file(db.OVERRIDE_COLUMNS, [
            {"ProA ID": 123, "Shooting Hand": "0", "Hairstyle": "3", "College": db.CLEAR},
            {"ProA ID": 456, "Hair Color": "3", "Standing Dunk": "50", "Last Name": "Test"},
        ])
        destination = self.root / "manual.xlsx"
        with patch.object(sys, "argv", ["overrides_workbook.py", "--csv", str(source),
                                        "--out", str(destination)]), contextlib.redirect_stdout(io.StringIO()):
            overrides_xlsx.main()
        self.assertEqual(db.load_overrides(source), db.load_overrides(destination))
        with patch.object(sys, "argv", ["overrides_workbook.py", "--csv", str(source),
                                        "--out", str(destination)]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                overrides_xlsx.main()

    def test_xlsx_expanded_enum_and_label_change_keep_existing_selections(self):
        wb = overrides_xlsx.make_workbook([{"ProA ID": 123, "Shooting Hand": "0 - Old label"}],
                                          db.OVERRIDE_COLUMNS)
        enum = wb["Enumerations"]
        cols = {enum.cell(1, col).value: col for col in range(1, enum.max_column + 1, 2)}
        hand = cols["Shooting Hand"]
        enum.cell(2, hand + 1, "0 - New label")
        hairstyle = cols["Hairstyle"]
        added = 2 + len(overrides_xlsx.enumeration_options()["Hairstyle"])
        enum.cell(added, hairstyle, 24)
        enum.cell(added, hairstyle + 1, "24 - Custom hairstyle")
        ws = wb["Overrides"]
        ws.cell(2, db.OVERRIDE_COLUMNS.index("Hairstyle") + 1, "24 - Custom hairstyle")
        path = self.root / "expanded.xlsx"
        wb.save(path)
        wb.close()
        values = db.load_overrides(path)[123]
        self.assertEqual((values["Shooting Hand"], values["Hairstyle"]), (0, 24))

    def test_xlsx_uses_edited_text_and_numeric_labels(self):
        wb = overrides_xlsx.make_workbook([
            {"ProA ID": 123, "Shooting Hand": "0 - Left", "Head": 0, "Left Elbow Pad": 6},
        ], db.OVERRIDE_COLUMNS)
        enum, ws = wb["Enumerations"], wb["Overrides"]
        cols = {enum.cell(1, col).value: col for col in range(1, enum.max_column + 1, 2)}
        enum.cell(2, cols["Shooting Hand"] + 1, "Left")
        for i in range(7):
            enum.cell(i + 2, cols["Head"] + 1, i + 1)
        ws.cell(2, db.OVERRIDE_COLUMNS.index("Shooting Hand") + 1, "Left")
        ws.cell(2, db.OVERRIDE_COLUMNS.index("Head") + 1, 1)
        path = self.root / "labels.xlsx"
        wb.save(path)
        wb.close()
        values = db.load_overrides(path)[123]
        self.assertEqual((values["Shooting Hand"], values["Head"], values["Left Elbow Pad"]), (0, 0, 6))

        wb = openpyxl.load_workbook(path)
        wb["Enumerations"].cell(3, cols["Shooting Hand"] + 1, "Left")
        wb.save(path)
        wb.close()
        with self.assertRaisesRegex(ValueError, "duplicate value or invalid label"):
            db.load_overrides(path)

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
                                overrides={123: {"Dunk": 99, "Shooting Hand": 0, "College": "Example",
                                                 "Beard": 0, "Shades": 6, "Sock Length": 3}})
        wb = openpyxl.load_workbook(output)
        ws = wb["Dragons"]
        headers = [c.value for c in ws[1]]
        row = dict(zip(headers, next(ws.iter_rows(min_row=2, values_only=True))))
        self.assertEqual((row["First Name"], row["Last Name"]), ("Juergen", "Gross"))
        self.assertEqual((row["Dunk"], row["Shooting Hand"]), (99, 0))
        self.assertEqual(row["College"], "Example")
        self.assertEqual(row["Headband"], 0)
        self.assertEqual(row["Beard"], 0)
        self.assertIsNone(row["Hairstyle"])
        data = bytearray(0x94)
        apply_accessories(data, 0, row)
        self.assertEqual((data[0x72], data[0x83]), (6, 3))
        self.assertTrue(row["Overall"].startswith("="))
        self.assertEqual(headers[headers.index("Close Shot"):headers.index("Headshot ID")],
                         [*db.ALL_ATTRS, *db.HIDDEN_ATTRS])
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
               "Height": 1.9, "Weight": 85, **dict.fromkeys(db.HIDDEN_ATTRS, 50),
               "Dunk Range": 10, "Emotion": 0, "Standing Dunk": 0}
        data = bytearray(0x94)
        write_record_fields(data, 0, {"rowd": row, "jersey": 0, "pos": 0, "attrs": row})
        self.assertEqual((data[P_HAND], data[P_YEARS]), (0, 1))
        apply_accessories(data, 0, {"headband": 2, "wrist_l": 1, "knee_r": 6})
        self.assertEqual((data[0x67], data[0x62], data[0x75], data[0x7F]), (0, 2, 7, 6))
        apply_accessories(data, 0, {"headband": 0, "wrist_l": 0})
        self.assertEqual((data[0x67], data[0x75]), (255, 0))

    def test_named_accessories_write_raw_editor_indices_including_former_presets(self):
        data = bytearray([0x55] * 0x94)
        apply_accessories(data, 0, {"Headband": 1, "Left Wrist Band": 1,
                                  "Right Wrist Band": 2, "Left Elbow Pad": 1,
                                  "Right Elbow Pad": 2, "Left Knee Pad": 19,
                                  "Right Knee Pad": 20})
        self.assertEqual((data[0x67], data[0x75], data[0x76], data[0x77], data[0x78],
                          data[0x7E], data[0x7F]), (0, 1, 2, 1, 2, 19, 20))
        apply_accessories(data, 0, {"Headband": 0, "Right Wrist Band": 0})
        self.assertEqual((data[0x67], data[0x76]), (255, 0))

    def test_legacy_accessory_csv_preserves_item_indices_and_headband_build_byte(self):
        path = self.csv_file(["ProA ID", *db.LEGACY_ACCESSORY_NAMES], [
            {"ProA ID": 123, "headband": 2, "wrist_l": 1, "wrist_r": 2,
             "arm_l": 1, "arm_r": 2, "knee_l": 1, "knee_r": 2},
        ])
        self.assertEqual(db.load_overrides(path)[123], {
            "Headband": 1, "Legacy Accessory 0x62": 2,
            "Left Wrist Band": 7, "Right Wrist Band": 3,
            "Left Elbow Pad": 11, "Right Elbow Pad": 6,
            "Left Knee Pad": 14, "Right Knee Pad": 6,
        })
        with self.assertRaisesRegex(ValueError, "Conflicting accessory"):
            db.canonical_accessories({"wrist_l": 1, "Left Wrist Band": 2})

    def test_refresh_accessories_preserves_custom_non_accessory_enums_values_and_styles(self):
        options = overrides_xlsx.enumeration_options()
        for old, new in db.LEGACY_ACCESSORY_NAMES.items():
            del options[new]
            options[old] = [(0, "None"), *[(i, f"Old option {i}") for i in range(1, 256)]]
        del options["Legacy Accessory 0x62"]
        with patch.object(overrides_xlsx, "enumeration_options", return_value=options):
            wb = overrides_xlsx.make_workbook(
                [{"ProA ID": 123, "wrist_l": 1, "headband": 2, "Hairstyle": 5, "Dunk": 99}],
                ["Team", "ProA ID", "wrist_l", "Hairstyle", "headband", "Dunk"])
        ws, enum = wb["Overrides"], wb["Enumerations"]
        ws.column_dimensions["C"].width = 29
        ws["C2"].font = openpyxl.styles.Font(color="ABC123")
        columns = {enum.cell(1, col).value: col for col in range(1, enum.max_column + 1, 2)}
        for row in range(2, enum.max_row + 1):
            if enum.cell(row, columns["Hairstyle"]).value == 5:
                enum.cell(row, columns["Hairstyle"] + 1, "Artist choice")
        enum.cell(4, columns["headband"] + 1, "Alternate headband")
        ws["D2"], ws["E2"] = "Artist choice", "Alternate headband"
        for validation in ws.data_validations.dataValidation:
            validation.formula1 = validation.formula1.lstrip("=")
        path = self.root / "old-overrides.xlsx"
        wb.save(path)
        wb.close()
        for _ in range(2):
            overrides_xlsx.refresh_accessories(path)
            self.assertEqual(db.load_overrides(path)[123], {
                "Left Wrist Band": 7, "Headband": 1, "Legacy Accessory 0x62": 2,
                "Hairstyle": 5, "Dunk": 99,
            })
            check = openpyxl.load_workbook(path)
            ws, enum = check["Overrides"], check["Enumerations"]
            cols = {cell.value: cell.column for cell in ws[1]}
            self.assertEqual([cell.value for cell in ws[1]][-len(db.ACCESSORY_FIELDS):],
                             list(db.ACCESSORY_FIELDS))
            self.assertEqual(ws.cell(2, cols["Hairstyle"]).value, "Artist choice")
            self.assertEqual(ws.cell(2, cols["Left Wrist Band"]).font.color.rgb, "00ABC123")
            self.assertEqual(ws.column_dimensions[openpyxl.utils.get_column_letter(
                cols["Left Wrist Band"])].width, 29)
            self.assertEqual(ws.cell(2, cols["Right Knee Pad"]).value, None)
            for name, count in (("Left Wrist Band", 13), ("Left Elbow Pad", 13), ("Left Knee Pad", 21)):
                col = next(col for col in range(1, enum.max_column + 1, 2)
                           if enum.cell(1, col).value == name)
                self.assertEqual(sum(enum.cell(row, col).value is not None
                                     for row in range(2, enum.max_row + 1)), count)
            check.close()

    def test_generated_accessory_column_upgrade_preserves_other_values_and_legacy_bytes(self):
        wb = workbook()
        ws = wb.active
        columns = {cell.value: cell.column for cell in ws[1]}
        ws.cell(1, columns["Headband"], "headband")
        ws.cell(2, columns["Headband"], 2)
        ws.cell(1, columns["Left Wrist Band"], "wrist_l")
        ws.cell(2, columns["Left Wrist Band"], 1)
        ws.delete_cols(columns["Legacy Accessory 0x62"])
        ws.auto_filter.ref = f"A1:{openpyxl.utils.get_column_letter(ws.max_column)}{ws.max_row}"
        before = dict(zip([cell.value for cell in ws[1]], next(ws.iter_rows(min_row=2, values_only=True))))
        with contextlib.redirect_stdout(io.StringIO()):
            db.apply_overrides(wb, {})
        after = dict(zip([cell.value for cell in ws[1]], next(ws.iter_rows(min_row=2, values_only=True))))
        self.assertEqual(after, db.canonical_accessories(before))
        self.assertEqual(list(after)[-len(db.ACCESSORY_FIELDS)-1:-1], list(db.ACCESSORY_FIELDS))
        self.assertEqual(ws.auto_filter.ref,
                         f"A1:{openpyxl.utils.get_column_letter(ws.max_column)}{ws.max_row}")
        for row in (before, after):
            data = bytearray(0x94)
            apply_accessories(data, 0, row)
            self.assertEqual((data[0x67], data[0x62], data[0x75]), (0, 2, 7))
        wb.close()

    def test_optional_accessory_bytes_and_created_model_are_independent(self):
        data = bytearray([0x55] * 0x94)
        values = {"Shades": 8, "Left Arm Band": 1, "Right Arm Band": 12,
                  "Shorts Length": 1, "Sock Length": 3, "Home Sock Color": 1,
                  "Away Sock Color": 0, "Legacy Accessory 0x64": 9,
                  "Legacy Accessory 0x65": 255, "Legacy Goggles 0x66": 0}
        apply_accessories(data, 0, values)
        for name, value in values.items():
            self.assertEqual(data[db.RAW_ACCESSORY_FIELDS[name][0]], value, name)
        self.assertFalse(apply_created_appearance(data, 0, values, 123))
        data[0x69] = 4
        apply_created_appearance(data, 0, {"Beard": 1}, 123)
        for name, value in values.items():
            self.assertEqual(data[db.RAW_ACCESSORY_FIELDS[name][0]], value, name)
        apply_accessories(data, 0, {})
        self.assertEqual(data[0x63], 1)
        self.assertEqual(data[0x72], 8)
        self.assertEqual(data[0x79], 0)
        self.assertEqual(data[0x64], 255)

    def test_created_appearance_explicit_zero_and_accessories(self):
        data = bytearray(0x94)
        data[8], data[0x69] = 4, 5
        apply_accessories(data, 0, {"headband": 2, "wrist_l": 1})
        before = bytes(data)
        self.assertFalse(apply_created_appearance(data, 0, {}, 123))
        self.assertEqual(bytes(data), before)
        row = {"Beard": 0, "Build": 1, "Hairstyle": 7, "Rt Forearm Tattoo": 12}
        self.assertTrue(apply_created_appearance(data, 0, row, 123))
        self.assertEqual((data[8], data[0x68], data[0x61], data[0x62]), (5, 1, 7, 1))
        self.assertEqual((data[0x6E], data[0x8D], data[0x67], data[0x75]), (0, 12, 0, 7))
        self.assertIn(data[0x71], range(2, 7))

    def test_created_head_selection_is_stable_and_uses_effective_skin(self):
        for skin in range(6):
            heads = set()
            for pid in range(1, 100):
                data = bytearray(0x94)
                data[0x69] = skin
                apply_created_appearance(data, 0, {"Beard": 1}, pid)
                head = data[0x71]
                apply_created_appearance(data, 0, {"Beard": 1}, pid)
                self.assertEqual(data[0x71], head)
                heads.add(head)
            self.assertEqual(heads, set(range(2, 7) if skin in (4, 5) else range(7)))
        data[0x69] = 5
        apply_created_appearance(data, 0, {"Head": 0}, 123)
        self.assertEqual(data[0x71], 0)
        data[0x69] = 6
        with self.assertRaisesRegex(ValueError, "skin tone"):
            apply_created_appearance(data, 0, {"Head": 1}, 123)

    def test_created_hairstyle_default_is_stable_and_uses_effective_skin(self):
        for skin in range(6):
            hairstyles = set()
            for pid in range(1, 100):
                data = bytearray(0x94)
                data[0x69] = skin
                apply_created_appearance(data, 0, {"Beard": 0}, pid)
                hairstyle = data[0x61]
                apply_created_appearance(data, 0, {"Beard": 0}, pid)
                self.assertEqual(data[0x61], hairstyle)
                hairstyles.add(hairstyle)
            self.assertEqual(hairstyles, {5, 13, 22} if skin in (4, 5) else {1, 2})
        for hairstyle in (0, 7):
            apply_created_appearance(data, 0, {"Hairstyle": hairstyle}, 123)
            self.assertEqual(data[0x61], hairstyle)

    def test_appearance_override_ranges_and_legacy_workbook_migration(self):
        for name, (_, maximum) in db.APPEARANCE_FIELDS.items():
            self.assertEqual(db.field_value(name, 0), 0)
            self.assertEqual(db.field_value(name, maximum), maximum)
            with self.assertRaises(ValueError):
                db.field_value(name, maximum + 1)
        wb = workbook()
        ws = wb.active
        optional = {*db.APPEARANCE_FIELDS, *db.RAW_ACCESSORY_FIELDS}
        for col in sorted((c.column for c in ws[1] if c.value in optional), reverse=True):
            ws.delete_cols(col)
        with contextlib.redirect_stdout(io.StringIO()):
            db.apply_overrides(wb, {123: {"Beard": 0, "Sock Length": 3}})
        cols = {cell.value: cell.column for cell in ws[1]}
        self.assertEqual(ws.cell(2, cols["Beard"]).value, 0)
        self.assertEqual(ws.cell(2, cols["Sock Length"]).value, 3)
        self.assertIsNone(ws.cell(2, cols["Head"]).value)
        wb.close()

    def test_hidden_migration_preserves_existing_values_and_override_precedence(self):
        wb = workbook()
        ws = wb.active
        before = dict(zip([c.value for c in ws[1]], next(ws.iter_rows(min_row=2, values_only=True))))
        for column in sorted([c.column for c in ws[1] if c.value in db.HIDDEN_ATTRS], reverse=True):
            ws.delete_cols(column)
        rosters = {"1": [{"proa_id": 123, "games": 10, "minutes_total_sec": 12000,
                           "fga_avg": 10, "fouls_per_min": .1, "fg_pct": 55, "turnovers_avg": 1}]}
        with patch("proa_attr_model.random.randint", return_value=3) as rng:
            self.assertEqual(db.refresh_hidden_attributes(wb, rosters, 2026), 1)
            db.apply_overrides(wb, {123: {"Emotion": 15, "Consistency": 99, "Standing Dunk": 0}})
            db.apply_overrides(wb, {123: {"Emotion": 15, "Consistency": 99, "Standing Dunk": 0}})
            rng.assert_called_once_with(0, 5)
        after = dict(zip([c.value for c in ws[1]], next(ws.iter_rows(min_row=2, values_only=True))))
        for name, value in before.items():
            if name not in db.HIDDEN_ATTRS:
                self.assertEqual(after[name], value, name)
        self.assertEqual((after["Emotion"], after["Consistency"], after["Standing Dunk"]), (15, 99, 0))
        self.assertEqual(after["Offense Clutch"], 99)
        self.assertEqual(after["Fastbreak"], after["Speed"])
        wb.close()

    def test_missing_rating_inputs_abort_migration_before_changes(self):
        wb = workbook()
        before = list(wb.active.values)
        with self.assertRaisesRegex(ValueError, "lack FGA"):
            db.refresh_hidden_attributes(wb, {"1": [{"proa_id": 123, "games": 1}]}, 2026)
        self.assertEqual(before, list(wb.active.values))
        wb.close()

    def test_builder_writes_all_nine_raw_bytes_and_rejects_legacy_conflict(self):
        wb = workbook()
        row = dict(zip(db.PLAYER_COLUMNS, next(wb.active.iter_rows(min_row=2, values_only=True))))
        row.update({"Standing Dunk": 99, "Emotion": 15, "Consistency": 99, "Offense Clutch": 75,
                    "Defense Clutch": 99, "Shoot or Pass": 97, "Fouls per Min": 20, "Fastbreak": 83})
        data = bytearray(0x94)
        player = {"rowd": row, "jersey": 0, "pos": 0, "attrs": row}
        with patch("proa_attr_model.random.randint", side_effect=AssertionError("Build must not randomize")):
            write_record_fields(data, 0, player)
        for name, offset in HIDDEN_ATTR_OFFSETS.items():
            self.assertEqual(data[offset], row[name])
        row["DunkFlag"] = 0
        with self.assertRaisesRegex(ValueError, "conflicts"):
            write_record_fields(data, 0, player)
        row.pop("DunkFlag")
        row.pop("Emotion")
        with self.assertRaisesRegex(ValueError, "missing hidden"):
            write_record_fields(data, 0, player)
        wb.close()

    def test_overall_formula_and_predictor_use_named_hidden_values(self):
        wb = workbook()
        ws = wb.active
        row = dict(zip(db.PLAYER_COLUMNS, next(ws.iter_rows(min_row=2, values_only=True))))
        row.update({"Standing Dunk": 99, "Emotion": 15, "Offense Clutch": 99,
                    "Shoot or Pass": 99, "Defense Clutch": 99, "Consistency": 99, "Fastbreak": 99})
        for column, cell in enumerate(ws[1], 1):
            ws.cell(2, column, row[cell.value])
        add_overall(wb)
        from openpyxl.utils import get_column_letter
        cols = {cell.value: get_column_letter(cell.column) for cell in ws[1]}
        expression = ws.cell(2, ws.max_column).value
        model = load_model()
        coefficients = list(wb[MODEL_SHEET].values)[1]
        visible = sum(w * row[name] for w, name in zip(coefficients[1:20], model["attributes"]))
        extras = player_extras(row, row)
        result = visible + coefficients[20] + coefficients[21] * row["Standing Dunk"]
        result += coefficients[22] * row["Height"] + coefficients[23] * row["Weight"]
        from overall_data import default_extras
        neutral = default_extras({"Dunk": 0})
        for index, name in enumerate(model["extras"]["names"]):
            canonical = EXTRA_CANONICAL[name]
            self.assertIn(f"{cols[canonical]}2", expression)
            if name != "DunkFlag":
                result += coefficients[24 + index] * (row[canonical] - neutral[name])
        expected = predict_overall("PG", row, row["Height"], row["Weight"], extras)
        self.assertAlmostEqual(result, expected)
        self.assertAlmostEqual(expected, predict_overall("PG", row, row["Height"], row["Weight"]))
        self.assertIn("INDEX('_Overall_Model'!$Z$2:$Z$6", expression)
        wb.close()

    def test_calibration_aliases_agree_with_named_bytes(self):
        from types import SimpleNamespace
        wb = workbook()
        source, output = self.root / "source.xlsx", self.root / "calibration.xlsx"
        wb.save(source)
        wb.close()
        args = SimpleNamespace(source=source, out=output, seed=2005)
        with patch.object(make_calibration, "CAL", self.root), contextlib.redirect_stdout(io.StringIO()):
            make_calibration.make(args)
        result = openpyxl.load_workbook(output)
        row = dict(zip([c.value for c in result.active[1]],
                       next(result.active.iter_rows(min_row=2, values_only=True))))
        for alias, name in EXTRA_CANONICAL.items():
            self.assertEqual(row[alias], row[name])
        payload = bytearray(0x94)
        write_record_fields(payload, 0, {"rowd": row, "jersey": 1, "pos": 0, "attrs": row})
        for name, offset in HIDDEN_ATTR_OFFSETS.items():
            self.assertEqual(payload[offset], row[name])
        result.close()

    def test_site_overall_reads_named_hidden_values(self):
        import json
        wb = workbook()
        ws = wb.active
        cols = {cell.value: cell.column for cell in ws[1]}
        ws.cell(2, cols["Offense Clutch"], 99)
        ws.cell(2, cols["Shoot or Pass"], 99)
        ws.cell(2, cols["Defense Clutch"], 99)
        row = dict(zip([c.value for c in ws[1]], next(ws.iter_rows(min_row=2, values_only=True))))
        book, stats = self.root / "players.xlsx", self.root / "stats.json"
        wb.save(book)
        wb.close()
        stats.write_text(json.dumps({"season": "2026_2027", "teams": {}, "players": {}}), encoding="utf-8")
        data = build_site.build_data(book, stats)
        expected = round(predict_overall("PG", row, row["Height"], row["Weight"], player_extras(row, row)))
        self.assertEqual(data["players"][0]["ovr"], expected)

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
