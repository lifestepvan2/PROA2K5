"""Migrate CSV overrides to an editable workbook with enumerated dropdowns."""
import argparse
import csv
from copy import copy
from io import BytesIO
import re
from pathlib import Path

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

import player_database as db

OVERRIDE_SHEET = "Overrides"
ENUM_SHEET = "Enumerations"
MAX_ENUM_ROW = 1024
MAX_PLAYER_ROW = 10000


def enumeration_options():
    options = {
        "Position": [("PG", "Point Guard"), ("SG", "Shooting Guard"), ("SF", "Small Forward"),
                     ("PF", "Power Forward"), ("C", "Center")],
        "Secondary Position": [("PG", "Point Guard"), ("SG", "Shooting Guard"),
                               ("SF", "Small Forward"), ("PF", "Power Forward"),
                               ("C", "Center"), ("N/A", "None")],
        "Shooting Hand": [(0, "Left"), (1, "Right")],
        "Skin Tone": [(0, "Automatic"), *[(i, f"Tone {i} (1 lightest, 6 darkest)") for i in range(1, 7)]],
        "Head": [(i, f"Head {i + 1}") for i in range(7)],
        "Hairstyle": list({0: "Bald", 1: "Buzz", 2: "Buzz Fade", 5: "Natural", 7: "Afro",
                           10: "Cornrows", 11: "Dreadlocks", 13: "Short Flattop", 16: "Mullet",
                           18: "Slicked Back", 19: "Slicked Back Long", 21: "Chin Long Open",
                           22: "Part Right", 23: "Part Mid"}.items()),
        "Build": [(0, "Normal"), (1, "Thick"), (2, "Fat")],
        "Muscle Tone": [(0, "Buff"), (1, "Ripped")],
        "Hair Color": [(0, "Black"), (1, "Brown"), (2, "Blond"), (3, "Red")],
    }
    for name in ("Beard", "Moustache", "Sideburns",
                 "Lt Neck Tattoo", "Rt Neck Tattoo", "Lt Bicep Tattoo", "Rt Bicep Tattoo",
                 "Lt Forearm Tattoo", "Rt Forearm Tattoo"):
        maximum = (db.APPEARANCE_FIELDS if name in db.APPEARANCE_FIELDS else db.RAW_ACCESSORY_FIELDS)[name][1]
        options[name] = [(0, "None"), *[(i, f"{name} {i}") for i in range(1, maximum + 1)]]
    # Europe editor string-pointer tables at EE 0x8FD358..0x8FD64C.
    bands = {
        "Wrist Band": ("None", "Wht Forearm Band", "Blk Forearm Band", "Team Forearm Band",
                       "2nd Team Forearm Band", "Wht Wrist Band", "Blk Wrist Band",
                       "Team Wrist Band", "2nd Team Wrist Band", "Wht Dbl Wrist Band",
                       "Blk Dbl Wrist Band", "Team Dbl Wrist Band", "2nd Team Dbl Wrist Band"),
        "Arm Band": ("None", "Wht Upper Arm", "Blk Upper Arm", "Team Upper Arm",
                     "2nd Team Upper Arm", "Wht Lower Arm", "Blk Lower Arm",
                     "Team Lower Arm", "2nd Team Lower Arm", "Wht Sleeve", "Blk Sleeve",
                     "Team Sleeve", "2nd Team Sleeve"),
        "Elbow Pad": ("None", "White Pad", "Black Pad", "Team Pad", "2nd Team Pad",
                      "White Sleeve", "Black Sleeve", "Team Sleeve", "2nd Team Sleeve",
                      "White Band", "Black Band", "Team Band", "2nd Team Band"),
        "Knee Pad": ("None", "White Pad", "Black Pad", "Team Pad", "2nd Team Pad",
                     "White Brace", "Black Brace", "Team Brace", "2nd Team Brace",
                     "White Sleeve", "Black Sleeve", "Team Sleeve", "2nd Team Sleeve",
                     "White Strap", "Black Strap", "Team Strap", "2nd Team Strap",
                     "Wht Calf Sleeve", "Blk Calf Sleeve", "Team Calf Sleeve", "2nd Team Calf Sleeve"),
    }
    accessories = {
        "Headband": [(0, "None"), (1, "Headband 1")],
        "Shades": [(0, "None"), *[(i, f"Shades {i}") for i in range(1, 9)]],
        "Shorts Length": [(0, "Short"), (1, "Long")],
        "Sock Length": [(0, "Ankle Socks"), (1, "Short"), (2, "Medium"), (3, "Long")],
        "Home Sock Color": [(0, "Black"), (1, "White")],
        "Away Sock Color": [(0, "Black"), (1, "White")],
    }
    for part, descriptions in bands.items():
        for side in ("Left", "Right"):
            accessories[f"{side} {part}"] = list(enumerate(descriptions))
    for name in db.ACCESSORY_FIELDS:
        if name.startswith("Legacy"):
            cleared = 0 if name == "Legacy Accessory 0x62" else 255
            options[name] = [(i, f"Raw byte {i}" + (" (cleared)" if i == cleared else ""))
                             for i in range(256)]
        else:
            options[name] = accessories[name]
    for name, tiers in db.HIDDEN_TIERS.items():
        options[name] = [(value, f"Tier {value}") for value in tiers]
    return options


def make_workbook(rows, headers):
    options = enumeration_options()
    labels = {name: {str(code): f"{code} - {description}" for code, description in choices}
              for name, choices in options.items()}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = OVERRIDE_SHEET
    ws.append(headers)
    for row in rows:
        values = []
        for name in headers:
            value = row.get(name)
            if value is None or value == "":
                value = None
            elif name in labels:
                value = labels[name].get(str(value).strip(), value)
            values.append(value)
        ws.append(values)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, len(rows) + 1)}"
    enum = wb.create_sheet(ENUM_SHEET)
    for index, (name, choices) in enumerate(options.items()):
        code_col, label_col = index * 2 + 1, index * 2 + 2
        enum.cell(1, code_col, name)
        enum.cell(1, label_col, f"{name} dropdown")
        for rownum, (code, description) in enumerate(choices, start=2):
            enum.cell(rownum, code_col, code)
            enum.cell(rownum, label_col, f"{code} - {description}")
        letter = get_column_letter(label_col)
        enum.column_dimensions[get_column_letter(code_col)].width = 18
        enum.column_dimensions[letter].width = 36
        formula = (f"OFFSET('{ENUM_SHEET}'!${letter}$2,0,0,"
                   f"COUNTA('{ENUM_SHEET}'!${letter}$2:${letter}${MAX_ENUM_ROW}),1)")
        range_name = f"override_enum_{index}"
        wb.defined_names.add(DefinedName(range_name, attr_text=formula))
        if name in headers:
            column = get_column_letter(headers.index(name) + 1)
            dv = DataValidation(type="list", formula1=f"={range_name}", allow_blank=True,
                                showErrorMessage=False, showDropDown=False)
            dv.add(f"{column}2:{column}{MAX_PLAYER_ROW}")
            ws.add_data_validation(dv)
    for sheet in (ws, enum):
        for cell in sheet[1]:
            cell.font = Font(bold=True)
    enum.freeze_panes = "A2"
    return wb


def read_overrides(path):
    wb = openpyxl.load_workbook(path, data_only=False)
    try:
        if OVERRIDE_SHEET not in wb or ENUM_SHEET not in wb:
            raise ValueError(f"{path}: expected {OVERRIDE_SHEET} and {ENUM_SHEET} sheets")
        enum = wb[ENUM_SHEET]
        names = enumeration_options()
        found = set()
        mappings = {}
        for col in range(1, enum.max_column + 1, 2):
            name = enum.cell(1, col).value
            if (name not in names and name not in db.LEGACY_ACCESSORY_NAMES) or name in found:
                raise ValueError(f"{path}: unknown or duplicate enumeration {name!r}")
            found.add(name)
            seen = set()
            labels = {}
            gap = False
            for row in range(2, enum.max_row + 1):
                code_cell, label_cell = enum.cell(row, col), enum.cell(row, col + 1)
                code, label = code_cell.value, label_cell.value
                if code is None and label is None:
                    gap = True
                    continue
                if (gap or row > MAX_ENUM_ROW or code is None or label is None
                        or isinstance(label, bool) or not isinstance(label, (str, int, float))
                        or code_cell.data_type == "f" or label_cell.data_type == "f"):
                    raise ValueError(f"{path}: {name} has an incomplete or non-contiguous enumeration at row {row}")
                valid = db.field_value(name, code)
                label_key = str(label).strip()
                prefix = label_key.split(" - ", 1)[0] if " - " in label_key else None
                if (valid in seen or not label_key or label_key in labels
                        or (prefix is not None and (prefix.isdigit() or prefix in {"PG", "SG", "SF", "PF", "C", "N/A"})
                            and (prefix != str(valid) or not label_key.split(" - ", 1)[1].strip()))):
                    raise ValueError(f"{path}: {name} has a duplicate value or invalid label at row {row}")
                seen.add(valid)
                labels[label_key] = valid
            if not seen:
                raise ValueError(f"{path}: {name} has no enumeration options")
            mappings[name] = labels
        required = set(names)
        if found & db.LEGACY_ACCESSORY_NAMES.keys():
            required.remove("Legacy Accessory 0x62")
        canonical = {db.LEGACY_ACCESSORY_NAMES.get(name, name) for name in found}
        if required - canonical:
            raise ValueError(f"{path}: missing enumerations {sorted(required - canonical)}")
        ws = wb[OVERRIDE_SHEET]
        headers = [cell.value for cell in ws[1]]
        if (len(set(headers)) != len(headers)
                or set(headers) - (set(db.OVERRIDE_COLUMNS) | db.LEGACY_ACCESSORY_NAMES.keys())
                or "ProA ID" not in headers):
            raise ValueError(f"{path}: invalid override headers")
        rows, seen = [], set()
        for cells in ws.iter_rows(min_row=2):
            if all(cell.value is None or cell.value == "" for cell in cells):
                continue
            if any(cell.data_type == "f" for cell in cells):
                raise ValueError(f"{path}: formulas are not allowed in overrides (row {cells[0].row})")
            row = dict(zip(headers, (cell.value for cell in cells)))
            pid = db.player_id(row["ProA ID"])
            if pid in seen:
                raise ValueError(f"{path}: duplicate ProA ID {pid}")
            seen.add(pid)
            for name in mappings.keys() & row.keys():
                value = row[name]
                if value is not None and not isinstance(value, bool) and str(value).strip() in mappings[name]:
                    row[name] = mappings[name][str(value).strip()]
                elif isinstance(value, str) and " - " in value:
                    prefix = value.split(" - ", 1)[0].strip()
                    if name in db.TEXT_COLUMNS:
                        row[name] = db.field_value(name, prefix)
                    elif re.fullmatch(r"[+-]?\d+", prefix):
                        row[name] = int(prefix)
                    else:
                        raise ValueError(f"{path}: ProA ID {pid}, {name}: invalid dropdown value {value!r}")
            rows.append(row)
        return rows
    finally:
        wb.close()


def refresh_accessories(path):
    path = Path(path)
    original = path.read_bytes()
    rows = read_overrides(BytesIO(original))
    expected = [db.canonical_accessories(row) for row in rows]
    wb = openpyxl.load_workbook(BytesIO(original))
    try:
        ws, enum = wb[OVERRIDE_SHEET], wb[ENUM_SHEET]
        validations = {}
        for dv in ws.data_validations.dataValidation:
            if dv.type != "list" or not re.fullmatch(r"=?override_enum_\d+", str(dv.formula1)):
                raise ValueError(f"{path}: cannot relocate nonstandard override validation {dv.formula1!r}")
            fields = {ws.cell(1, col).value for region in dv.ranges
                      for col in range(region.min_col, region.max_col + 1)}
            if len(fields) != 1:
                raise ValueError(f"{path}: override validation spans different fields")
            name = next(iter(fields))
            validations[db.LEGACY_ACCESSORY_NAMES.get(name, name)] = copy(dv)
        headers = [cell.value for cell in ws[1]]
        by_id = {db.player_id(row["ProA ID"]): row for row in expected}
        replacements = {}
        options = enumeration_options()
        labels = {name: {code: f"{code} - {description}" for code, description in choices}
                  for name, choices in options.items()}
        for index in range(2, ws.max_row + 1):
            pid = ws.cell(index, headers.index("ProA ID") + 1).value
            if pid is None:
                continue
            row = by_id[db.player_id(pid)]
            replacements[index] = {name: labels[name].get(row.get(name), row.get(name))
                                   for name in db.ACCESSORY_FIELDS}
        accessories = set(db.ACCESSORY_FIELDS) | db.LEGACY_ACCESSORY_NAMES.keys()
        headers = [name for name in headers if name not in accessories] + list(db.ACCESSORY_FIELDS)
        db.reorder_columns(ws, headers, replacements=replacements, aliases=db.LEGACY_ACCESSORY_NAMES)
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws.max_row}"

        headers = [cell.value for cell in enum[1]]
        aliases = {**db.LEGACY_ACCESSORY_NAMES,
                   **{f"{old} dropdown": f"{new} dropdown"
                      for old, new in db.LEGACY_ACCESSORY_NAMES.items()}}
        retained = [headers[col:col + 2] for col in range(0, len(headers), 2)
                    if headers[col] not in accessories]
        headers = [name for pair in retained for name in pair]
        headers += [label for name in db.ACCESSORY_FIELDS for label in (name, f"{name} dropdown")]
        replacements = {}
        for row in range(2, max(enum.max_row, 257) + 1):
            values = {}
            for name in db.ACCESSORY_FIELDS:
                choices = options[name]
                code = choices[row - 2][0] if row - 2 < len(choices) else None
                values[name] = code
                values[f"{name} dropdown"] = labels[name].get(code)
            replacements[row] = values
        db.reorder_columns(enum, headers, replacements=replacements, aliases=aliases)
        for name in list(wb.defined_names):
            if name.startswith("override_enum_"):
                del wb.defined_names[name]
        ws.data_validations.dataValidation.clear()
        player_columns = {cell.value: cell.column for cell in ws[1]}
        for index, col in enumerate(range(1, enum.max_column + 1, 2)):
            name, letter = enum.cell(1, col).value, get_column_letter(col + 1)
            range_name = f"override_enum_{index}"
            formula = (f"OFFSET('{ENUM_SHEET}'!${letter}$2,0,0,"
                       f"COUNTA('{ENUM_SHEET}'!${letter}$2:${letter}${MAX_ENUM_ROW}),1)")
            wb.defined_names.add(DefinedName(range_name, attr_text=formula))
            if name in player_columns:
                dv = validations.get(name) or DataValidation(type="list", allow_blank=True,
                                                             showErrorMessage=False, showDropDown=False)
                dv.formula1 = f"={range_name}"
                column = get_column_letter(player_columns[name])
                dv.sqref = f"{column}2:{column}{MAX_PLAYER_ROW}"
                ws.add_data_validation(dv)
        stream = BytesIO()
        wb.save(stream)
        content = stream.getvalue()
        def meaningful(records):
            return [{k: v for k, v in row.items() if v not in (None, "")} for row in records]
        if meaningful(read_overrides(BytesIO(content))) != meaningful(expected):
            raise ValueError(f"{path}: accessory refresh changed existing override selections")
        if path.read_bytes() != original:
            raise ValueError(f"{path}: changed while refreshing accessories; refusing to overwrite")
        path.write_bytes(content)
    finally:
        wb.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=db.ROOT / "data" / "overrides.csv")
    parser.add_argument("--out", type=Path, default=db.OVERRIDES)
    parser.add_argument("--refresh-accessories", action="store_true",
                        help="Refresh accessory names/dropdowns in --out, preserving existing selections")
    args = parser.parse_args()
    if args.refresh_accessories:
        refresh_accessories(args.out)
        print(f"Refreshed accessory columns and dropdowns in {args.out}")
        return
    if args.out.exists():
        parser.error(f"{args.out} already exists; refusing to overwrite")
    rows = db.read_csv(args.csv, [*db.OVERRIDE_COLUMNS, *db.LEGACY_ACCESSORY_NAMES], ["ProA ID"])
    with args.csv.open(encoding="utf-8-sig", newline="") as file:
        headers = csv.DictReader(file).fieldnames
    if set(headers) & db.LEGACY_ACCESSORY_NAMES.keys():
        rows = [db.canonical_accessories(row) for row in rows]
        headers = [name for name in db.OVERRIDE_COLUMNS
                   if name in {column for row in rows for column in row}]
    wb = make_workbook(rows, headers)
    try:
        with args.out.open("xb") as file:
            wb.save(file)
    finally:
        wb.close()
    print(f"Migrated {len(rows)} rows to {args.out}; original CSV unchanged")


if __name__ == "__main__":
    main()
