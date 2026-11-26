"""Migrate CSV overrides to an editable workbook with enumerated dropdowns."""
import argparse
import csv
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
        "Shorts Length": [(0, "Short"), (1, "Long")],
        "Sock Length": [(0, "Ankle Socks"), (1, "Short"), (2, "Medium"), (3, "Long")],
        "Home Sock Color": [(0, "Black"), (1, "White")],
        "Away Sock Color": [(0, "Black"), (1, "White")],
    }
    for name in ("Beard", "Moustache", "Sideburns", "Shades", "Left Arm Band", "Right Arm Band",
                 "Lt Neck Tattoo", "Rt Neck Tattoo", "Lt Bicep Tattoo", "Rt Bicep Tattoo",
                 "Lt Forearm Tattoo", "Rt Forearm Tattoo"):
        maximum = (db.APPEARANCE_FIELDS if name in db.APPEARANCE_FIELDS else db.RAW_ACCESSORY_FIELDS)[name][1]
        options[name] = [(0, "None"), *[(i, f"{name} {i}") for i in range(1, maximum + 1)]]
    for name in db.ACCESSORIES:
        presets = {"headband": ("Headband", "Headband, alternate style"),
                   "wrist_l": ("Wristband", "Long forearm tape"), "wrist_r": ("Wristband", "Long forearm tape"),
                   "arm_l": ("Small band", "Elbow brace"), "arm_r": ("Small band", "Elbow brace"),
                   "knee_l": ("Small knee tape", "Knee brace"), "knee_r": ("Small knee tape", "Knee brace")}
        options[name] = [(0, "None"), (1, presets[name][0]), (2, presets[name][1]),
                         *[(i, f"Raw index {i}") for i in range(3, 256)]]
    for name in ("Legacy Accessory 0x64", "Legacy Accessory 0x65", "Legacy Goggles 0x66"):
        options[name] = [(i, f"Raw byte {i}" + (" (cleared)" if i == 255 else "")) for i in range(256)]
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
            if name not in names or name in found:
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
        if found != set(names):
            raise ValueError(f"{path}: missing enumerations {sorted(set(names) - found)}")
        ws = wb[OVERRIDE_SHEET]
        headers = [cell.value for cell in ws[1]]
        if (len(set(headers)) != len(headers) or set(headers) - set(db.OVERRIDE_COLUMNS)
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
            for name in names.keys() & row.keys():
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=db.ROOT / "data" / "overrides.csv")
    parser.add_argument("--out", type=Path, default=db.OVERRIDES)
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"{args.out} already exists; refusing to overwrite")
    rows = db.read_csv(args.csv, db.OVERRIDE_COLUMNS, ["ProA ID"])
    with args.csv.open(encoding="utf-8-sig", newline="") as file:
        headers = csv.DictReader(file).fieldnames
    wb = make_workbook(rows, headers)
    try:
        with args.out.open("xb") as file:
            wb.save(file)
    finally:
        wb.close()
    print(f"Migrated {len(rows)} rows to {args.out}; original CSV unchanged")


if __name__ == "__main__":
    main()
