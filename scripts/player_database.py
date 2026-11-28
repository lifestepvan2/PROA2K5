"""Canonical generated player schema and manually maintained ProA-ID overrides.

    python scripts/player_database.py
    python scripts/player_database.py --workbook proa_scraped.xlsx
"""
import argparse
import csv
from copy import copy
import json
from datetime import date
import math
import re
import sys
import unicodedata
from pathlib import Path

import openpyxl

from proa_attr_model import ALL_ATTRS, HIDDEN_ATTRS, hidden_ratings, league_defense_averages, player_context
from rating_map_2k5 import HIDDEN_BOUNDS, HIDDEN_TIERS

ROOT = Path(__file__).resolve().parent.parent
OVERRIDES = ROOT / "data" / "overrides.xlsx"
BLACKLIST = ROOT / "data" / "blacklist.csv"
ACCESSORIES = ("Headband", "Left Elbow Pad", "Right Elbow Pad", "Left Wrist Band",
               "Right Wrist Band", "Left Knee Pad", "Right Knee Pad")
LEGACY_ACCESSORY_NAMES = {
    "headband": "Headband", "wrist_l": "Left Wrist Band", "wrist_r": "Right Wrist Band",
    "arm_l": "Left Elbow Pad", "arm_r": "Right Elbow Pad",
    "knee_l": "Left Knee Pad", "knee_r": "Right Knee Pad",
}
LEGACY_ACCESSORY_PRESETS = {
    "wrist_l": {1: 7, 2: 3}, "wrist_r": {1: 7, 2: 3},
    "arm_l": {1: 11, 2: 6}, "arm_r": {1: 11, 2: 6},
    "knee_l": {1: 14, 2: 6}, "knee_r": {1: 14, 2: 6},
}
RAW_ACCESSORY_FIELDS = {
    "Shades": (0x72, 8), "Left Arm Band": (0x79, 12), "Right Arm Band": (0x7A, 12),
    "Shorts Length": (0x63, 1), "Sock Length": (0x83, 3),
    "Home Sock Color": (0x84, 1), "Away Sock Color": (0x85, 1),
    "Legacy Accessory 0x62": (0x62, 255),
    "Legacy Accessory 0x64": (0x64, 255), "Legacy Accessory 0x65": (0x65, 255),
    "Legacy Goggles 0x66": (0x66, 255),
}
ACCESSORY_FIELDS = {
    "Headband": (0x67, 1), "Shades": RAW_ACCESSORY_FIELDS["Shades"],
    "Left Arm Band": RAW_ACCESSORY_FIELDS["Left Arm Band"],
    "Right Arm Band": RAW_ACCESSORY_FIELDS["Right Arm Band"],
    "Left Elbow Pad": (0x77, 255), "Right Elbow Pad": (0x78, 255),
    "Left Wrist Band": (0x75, 255), "Right Wrist Band": (0x76, 255),
    "Shorts Length": RAW_ACCESSORY_FIELDS["Shorts Length"],
    "Left Knee Pad": (0x7E, 255), "Right Knee Pad": (0x7F, 255),
    "Sock Length": RAW_ACCESSORY_FIELDS["Sock Length"],
    "Home Sock Color": RAW_ACCESSORY_FIELDS["Home Sock Color"],
    "Away Sock Color": RAW_ACCESSORY_FIELDS["Away Sock Color"],
    **{name: value for name, value in RAW_ACCESSORY_FIELDS.items() if name.startswith("Legacy")},
}
APPEARANCE_FIELDS = {
    "Head": (0x71, 6), "Hairstyle": (0x61, 25), "Build": (0x62, 2),
    "Muscle Tone": (0x6A, 1), "Hair Color": (0x70, 3),
    "Beard": (0x6E, 6), "Moustache": (0x6D, 6), "Sideburns": (0x6F, 3),
    "Lt Neck Tattoo": (0x86, 6), "Rt Neck Tattoo": (0x87, 6),
    "Lt Bicep Tattoo": (0x8A, 12), "Rt Bicep Tattoo": (0x8B, 12),
    "Lt Forearm Tattoo": (0x8C, 12), "Rt Forearm Tattoo": (0x8D, 12),
}
IDENTITY_COLS = [
    "First Name", "Last Name", "Position", "Secondary Position", "Jersey Number",
    "Birth Year", "Birth Month", "Birth Day", "Years Pro", "Height", "Weight",
]
SHEET_COLUMNS = IDENTITY_COLS + list(ALL_ATTRS) + list(HIDDEN_ATTRS) + ["Headshot ID", "College", "Shooting Hand", "Skin Tone", *APPEARANCE_FIELDS, *ACCESSORY_FIELDS]
PLAYER_COLUMNS = SHEET_COLUMNS + ["ProA ID"]
OVERRIDE_COLUMNS = ["Team", "ProA ID", *(c for c in SHEET_COLUMNS)]
TEXT_COLUMNS = {"First Name", "Last Name", "Position", "Secondary Position", "College"}
CLEAR = "<CLEAR>"
TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})
NATION_NAMES = {
    "AD": "Andorra", "AE": "United Arab Emirates", "AF": "Afghanistan", "AG": "Antigua and Barbuda",
    "AI": "Anguilla", "AL": "Albania", "AM": "Armenia", "AO": "Angola", "AQ": "Antarctica",
    "AR": "Argentina", "AS": "American Samoa", "AT": "Austria", "AU": "Australia", "AW": "Aruba",
    "AX": "Aland Islands", "AZ": "Azerbaijan", "BA": "Bosnia and Herzegovina", "BB": "Barbados",
    "BD": "Bangladesh", "BE": "Belgium", "BF": "Burkina Faso", "BG": "Bulgaria", "BH": "Bahrain",
    "BI": "Burundi", "BJ": "Benin", "BL": "Saint Barthelemy", "BM": "Bermuda", "BN": "Brunei",
    "BO": "Bolivia", "BQ": "Bonaire, Sint Eustatius and Saba", "BR": "Brazil", "BS": "Bahamas",
    "BT": "Bhutan", "BV": "Bouvet Island", "BW": "Botswana", "BY": "Belarus", "BZ": "Belize",
    "CA": "Canada", "CC": "Cocos Islands", "CD": "Democratic Republic of the Congo",
    "CF": "Central African Republic", "CG": "Republic of the Congo", "CH": "Switzerland",
    "CI": "Ivory Coast", "CK": "Cook Islands", "CL": "Chile", "CM": "Cameroon", "CN": "China",
    "CO": "Colombia", "CR": "Costa Rica", "CU": "Cuba", "CV": "Cape Verde", "CW": "Curacao",
    "CX": "Christmas Island", "CY": "Cyprus", "CZ": "Czech Republic", "DE": "Germany",
    "DJ": "Djibouti", "DK": "Denmark", "DM": "Dominica", "DO": "Dominican Republic",
    "DZ": "Algeria", "EC": "Ecuador", "EE": "Estonia", "EG": "Egypt", "EH": "Western Sahara",
    "ER": "Eritrea", "ES": "Spain", "ET": "Ethiopia", "FI": "Finland", "FJ": "Fiji",
    "FK": "Falkland Islands", "FM": "Micronesia", "FO": "Faroe Islands", "FR": "France",
    "GA": "Gabon", "GB": "United Kingdom", "GD": "Grenada", "GE": "Georgia", "GF": "French Guiana",
    "GG": "Guernsey", "GH": "Ghana", "GI": "Gibraltar", "GL": "Greenland", "GM": "Gambia",
    "GN": "Guinea", "GP": "Guadeloupe", "GQ": "Equatorial Guinea", "GR": "Greece",
    "GS": "South Georgia and the South Sandwich Islands", "GT": "Guatemala", "GU": "Guam",
    "GW": "Guinea-Bissau", "GY": "Guyana", "HK": "Hong Kong", "HM": "Heard Island and McDonald Islands",
    "HN": "Honduras", "HR": "Croatia", "HT": "Haiti", "HU": "Hungary", "ID": "Indonesia",
    "IE": "Ireland", "IL": "Israel", "IM": "Isle of Man", "IN": "India",
    "IO": "British Indian Ocean Territory", "IQ": "Iraq", "IR": "Iran", "IS": "Iceland",
    "IT": "Italy", "JE": "Jersey", "JM": "Jamaica", "JO": "Jordan", "JP": "Japan",
    "KE": "Kenya", "KG": "Kyrgyzstan", "KH": "Cambodia", "KI": "Kiribati", "KM": "Comoros",
    "KN": "Saint Kitts and Nevis", "KP": "North Korea", "KR": "South Korea", "KW": "Kuwait",
    "KY": "Cayman Islands", "KZ": "Kazakhstan", "LA": "Laos", "LB": "Lebanon",
    "LC": "Saint Lucia", "LI": "Liechtenstein", "LK": "Sri Lanka", "LR": "Liberia",
    "LS": "Lesotho", "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "LY": "Libya",
    "MA": "Morocco", "MC": "Monaco", "MD": "Moldova", "ME": "Montenegro", "MF": "Saint Martin",
    "MG": "Madagascar", "MH": "Marshall Islands", "MK": "North Macedonia", "ML": "Mali",
    "MM": "Myanmar", "MN": "Mongolia", "MO": "Macao", "MP": "Northern Mariana Islands",
    "MQ": "Martinique", "MR": "Mauritania", "MS": "Montserrat", "MT": "Malta", "MU": "Mauritius",
    "MV": "Maldives", "MW": "Malawi", "MX": "Mexico", "MY": "Malaysia", "MZ": "Mozambique",
    "NA": "Namibia", "NC": "New Caledonia", "NE": "Niger", "NF": "Norfolk Island", "NG": "Nigeria",
    "NI": "Nicaragua", "NL": "Netherlands", "NO": "Norway", "NP": "Nepal", "NR": "Nauru",
    "NU": "Niue", "NZ": "New Zealand", "OM": "Oman", "PA": "Panama", "PE": "Peru",
    "PF": "French Polynesia", "PG": "Papua New Guinea", "PH": "Philippines", "PK": "Pakistan",
    "PL": "Poland", "PM": "Saint Pierre and Miquelon", "PN": "Pitcairn Islands", "PR": "Puerto Rico",
    "PS": "Palestine", "PT": "Portugal", "PW": "Palau", "PY": "Paraguay", "QA": "Qatar",
    "RE": "Reunion", "RO": "Romania", "RS": "Serbia", "RU": "Russia", "RW": "Rwanda",
    "SA": "Saudi Arabia", "SB": "Solomon Islands", "SC": "Seychelles", "SD": "Sudan", "SE": "Sweden",
    "SG": "Singapore", "SH": "Saint Helena, Ascension and Tristan da Cunha", "SI": "Slovenia",
    "SJ": "Svalbard and Jan Mayen", "SK": "Slovakia", "SL": "Sierra Leone", "SM": "San Marino",
    "SN": "Senegal", "SO": "Somalia", "SR": "Suriname", "SS": "South Sudan",
    "ST": "Sao Tome and Principe", "SV": "El Salvador", "SX": "Sint Maarten", "SY": "Syria",
    "SZ": "Eswatini", "TC": "Turks and Caicos Islands", "TD": "Chad",
    "TF": "French Southern Territories", "TG": "Togo", "TH": "Thailand", "TJ": "Tajikistan",
    "TK": "Tokelau", "TL": "Timor-Leste", "TM": "Turkmenistan", "TN": "Tunisia", "TO": "Tonga",
    "TR": "Turkey", "TT": "Trinidad and Tobago", "TV": "Tuvalu", "TW": "Taiwan", "TZ": "Tanzania",
    "UA": "Ukraine", "UG": "Uganda", "UM": "United States Minor Outlying Islands",
    "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan", "VA": "Vatican City",
    "VC": "Saint Vincent and the Grenadines", "VE": "Venezuela", "VG": "British Virgin Islands",
    "VI": "United States Virgin Islands", "VN": "Vietnam", "VU": "Vanuatu", "WF": "Wallis and Futuna",
    "WS": "Samoa", "YE": "Yemen", "YT": "Mayotte", "ZA": "South Africa", "ZM": "Zambia",
    "ZW": "Zimbabwe", "XK": "Kosovo", "UK": "United Kingdom",
}


def expand_nationality(value):
    if not value or not value.strip():
        return ""
    codes = list(dict.fromkeys(re.split(r"[\s/,;]+", value.strip().upper())))
    unknown = [code for code in codes if code not in NATION_NAMES]
    if unknown:
        raise ValueError(f"Unknown nationality code(s): {', '.join(unknown)}; extend NATION_NAMES before scraping")
    return " / ".join(dict.fromkeys(NATION_NAMES[code] for code in codes))


def sanitize_names(first, last):
    def clean(value):
        value = str(value or "").translate(TRANSLIT)
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
        return " ".join(value.split())

    first, last = clean(first), clean(last)
    if len(first) > 12:
        first = first.split()[0][:12]
    if len(last) > 12:
        tokens = [t for t in last.split() if t.lower() not in {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}]
        tokens = tokens or last.split()
        while len(" ".join(tokens)) > 12 and len(tokens) > 1:
            tokens.pop(0)
        last = " ".join(tokens)[:12]
    return first, last


def player_id(value):
    text = str(value).strip()
    if not re.fullmatch(r"[1-9]\d*", text):
        raise ValueError(f"Invalid ProA ID: {value!r} (use an integer, not a decimal)")
    return int(text)


def field_value(column, value, *, clamp=False):
    if column in TEXT_COLUMNS:
        if not isinstance(value, str):
            raise ValueError(f"{column}: expected text, got {value!r}")
        value = value.strip()
        if value.startswith("="):
            raise ValueError(f"{column}: formulas are not allowed in player text fields")
        if column in ("First Name", "Last Name"):
            if not value or len(value) > 12 or not value.isascii() or any(ord(c) < 32 for c in value):
                raise ValueError(f"{column}: use 1..12 printable ASCII characters")
        elif column == "Position" and value not in {"PG", "SG", "SF", "PF", "C"}:
            raise ValueError(f"Invalid Position: {value!r}")
        elif column == "Secondary Position" and value not in {"PG", "SG", "SF", "PF", "C", "N/A"}:
            raise ValueError(f"Invalid Secondary Position: {value!r}")
        elif column == "College" and any(not c.isprintable() or ord(c) > 0xFFFF for c in value):
            raise ValueError("College: use printable BMP characters, without NULs or control characters")
        return value
    if isinstance(value, bool):
        raise ValueError(f"{column}: expected a number, got boolean")
    try:
        number = float(value)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{column}: invalid number {value!r}") from error
    if not math.isfinite(number):
        raise ValueError(f"{column}: number must be finite")
    bounds = {
        "Jersey Number": (0, 99), "Birth Year": (1900, 2100), "Birth Month": (1, 12),
        "Birth Day": (1, 31), "Years Pro": (1, 127), "Height": (1.0, 2.7),
        "Weight": (30, 250), "Headshot ID": (0, 65535), "Shooting Hand": (0, 1), "Skin Tone": (0, 6),
        **dict.fromkeys(ALL_ATTRS, (25, 99)), **dict.fromkeys(LEGACY_ACCESSORY_NAMES, (0, 255)),
        **HIDDEN_BOUNDS,
        **{name: (0, maximum) for name, (_, maximum) in ACCESSORY_FIELDS.items()},
        **{name: (0, maximum) for name, (_, maximum) in APPEARANCE_FIELDS.items()},
    }
    if column not in bounds:
        raise ValueError(f"Unknown player column: {column}")
    low, high = bounds[column]
    if clamp:
        number = max(low, min(high, number))
        if column in HIDDEN_TIERS:
            return min(HIDDEN_TIERS[column], key=lambda option: (abs(number - option), option))
        if column not in ("Height", "Weight"):
            return math.ceil(number - 0.5)
        return number
    if not low <= number <= high:
        raise ValueError(f"{column}: expected {low}..{high}, got {value!r}")
    if column in ("Height", "Weight"):
        return number
    if not number.is_integer():
        raise ValueError(f"{column}: expected an integer, got {value!r}")
    if column in HIDDEN_TIERS and int(number) not in HIDDEN_TIERS[column]:
        raise ValueError(f"{column}: expected one of {HIDDEN_TIERS[column]}, got {value!r}")
    return int(number)


def canonical_accessories(row):
    result = dict(row)
    for old, name in LEGACY_ACCESSORY_NAMES.items():
        value = result.pop(old, None)
        if value in (None, ""):
            continue
        value = field_value(old, value)
        changes = {name: LEGACY_ACCESSORY_PRESETS.get(old, {}).get(value, value)}
        if old == "headband":
            changes[name] = int(value != 0)
            if value not in (0, 1):
                changes["Legacy Accessory 0x62"] = value
        for target, replacement in changes.items():
            if (result.get(target) not in (None, "")
                    and field_value(target, result[target]) != replacement):
                raise ValueError(f"Conflicting accessory values: {old} and {target}")
            result[target] = replacement
    return result


def reorder_columns(ws, headers, *, replacements=None, aliases=None):
    """Move named columns without losing cell formatting or column dimensions."""
    old_headers = [cell.value for cell in ws[1]]
    if len(set(old_headers)) != len(old_headers) or None in old_headers:
        raise ValueError(f"{ws.title}: duplicate or empty column headers")
    replacements, aliases = replacements or {}, aliases or {}
    height = max(ws.max_row, max(replacements, default=0))
    cells = {name: [copy(ws.cell(row, col)) for row in range(1, ws.max_row + 1)]
             for col, name in enumerate(old_headers, 1)}
    dimensions = {}
    for col, name in enumerate(old_headers, 1):
        letter = openpyxl.utils.get_column_letter(col)
        dimension = ws.column_dimensions.get(letter)
        if dimension is None:
            dimension = next((d for d in ws.column_dimensions.values()
                              if d.min and d.min <= col <= d.max), None)
        if dimension is not None:
            dimensions[name] = copy(dimension)
    ws.delete_cols(1, ws.max_column)
    ws.column_dimensions.clear()
    for col, name in enumerate(headers, 1):
        origin = name if name in cells else next((old for old, new in aliases.items()
                                                 if new == name and old in cells), None)
        if origin in dimensions:
            dimension = copy(dimensions[origin])
            dimension.index = openpyxl.utils.get_column_letter(col)
            dimension.min = dimension.max = col
            ws.column_dimensions[dimension.index] = dimension
        for row in range(1, height + 1):
            target = ws.cell(row, col)
            source = cells[origin][row - 1] if origin in cells and row <= len(cells[origin]) else None
            if source is not None:
                target.value = source.value
                target._style = copy(source._style)
                target.comment = copy(source.comment)
                target.hyperlink = copy(source.hyperlink)
            if row == 1:
                target.value = name
                if source is None:
                    target._style = copy(next(iter(cells.values()))[0]._style)
            elif name in replacements.get(row, {}):
                target.value = replacements[row][name]


def migrate_accessory_columns(ws):
    headers = [cell.value for cell in ws[1]]
    fields = set(ACCESSORY_FIELDS) | set(LEGACY_ACCESSORY_NAMES)
    tail = [name for name in headers if name in ("ProA ID", "Overall")]
    ordered = [name for name in headers if name not in fields and name not in tail]
    ordered += [*ACCESSORY_FIELDS, *tail]
    if ordered == headers:
        return
    replacements = {}
    for index, values in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        normalized = canonical_accessories(dict(zip(headers, values)))
        replacements[index] = {name: normalized.get(name) for name in ACCESSORY_FIELDS}
    reorder_columns(ws, ordered, replacements=replacements, aliases=LEGACY_ACCESSORY_NAMES)
    if ws.auto_filter.ref:
        ws.auto_filter.ref = f"A1:{openpyxl.utils.get_column_letter(ws.max_column)}{ws.max_row}"


def read_csv(path, allowed, required):
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers = reader.fieldnames or []
        if len(set(headers)) != len(headers) or set(headers) - set(allowed) or set(required) - set(headers):
            raise ValueError(f"{path}: invalid headers; allowed: {', '.join(allowed)}")
        rows = list(reader)
    seen = set()
    for row in rows:
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f"{path}: malformed CSV row")
        pid = player_id(row["ProA ID"])
        if pid in seen:
            raise ValueError(f"{path}: duplicate ProA ID {pid}")
        seen.add(pid)
    return rows


def load_blacklist(path=BLACKLIST):
    return {player_id(row["ProA ID"]) for row in read_csv(path, ["Team", "ProA ID", "Reason"], ["ProA ID"])}


def load_overrides(path=OVERRIDES):
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        from overrides_workbook import read_overrides
        rows = read_overrides(path)
    elif path.suffix.lower() == ".csv":
        rows = read_csv(path, [*OVERRIDE_COLUMNS, *LEGACY_ACCESSORY_NAMES], ["ProA ID"])
    else:
        raise ValueError(f"{path}: overrides must be an .xlsx or .csv file")
    result = {}
    for row in rows:
        pid = player_id(row["ProA ID"])
        changes = {}
        for column, value in row.items():
            if column in ("Team", "ProA ID") or value is None or (isinstance(value, str) and not value.strip()):
                continue
            if isinstance(value, str) and value.strip() == CLEAR:
                if column != "College":
                    raise ValueError(f"{pid}: {CLEAR} is only supported for College; use 0 for numeric fields")
                changes[column] = ""
            else:
                corrected = field_value(column, value, clamp=True)
                if column not in TEXT_COLUMNS and corrected != float(value):
                    print(f"Warning: {path}: ProA ID {pid}, {column}: {value!r} adjusted to {corrected}",
                          file=sys.stderr)
                changes[column] = corrected
        result[pid] = canonical_accessories(changes)
    return result


def apply_overrides(workbook, overrides, *, blacklist=None):
    overrides = {pid: canonical_accessories(changes) for pid, changes in overrides.items()}
    seen, changes = set(), 0
    for ws in workbook:
        if ws.title.startswith("_"):
            continue
        columns = {cell.value: cell.column for cell in ws[1] if cell.value}
        if "Skin Tone" not in columns:
            column = columns.get("ProA ID", ws.max_column + 1)
            ws.insert_cols(column)
            ws.cell(1, column, "Skin Tone")
            for index in range(2, ws.max_row + 1):
                ws.cell(index, column, 0)
            columns = {cell.value: cell.column for cell in ws[1] if cell.value}
        for name in (*RAW_ACCESSORY_FIELDS, *APPEARANCE_FIELDS):
            if name not in columns:
                ws.cell(1, ws.max_column + 1, name)
        migrate_accessory_columns(ws)
        columns = {cell.value: cell.column for cell in ws[1] if cell.value}
        missing = set(PLAYER_COLUMNS) - set(columns)
        if missing:
            raise ValueError(f"{ws.title}: missing player columns {sorted(missing)}; regenerate workbook")
        for index in range(ws.max_row, 1, -1):
            raw = ws.cell(index, columns["ProA ID"]).value
            if raw is None:
                continue
            pid = player_id(raw)
            if blacklist and pid in blacklist:
                ws.delete_rows(index)
                print(f"Blacklist: removed {pid} from {ws.title}")
                continue
            if pid in seen:
                raise ValueError(f"Workbook contains duplicate ProA ID {pid}")
            seen.add(pid)
            for name, value in overrides.get(pid, {}).items():
                ws.cell(index, columns[name], value)
                changes += 1
            row = {name: ws.cell(index, col).value for name, col in columns.items()}
            for name in SHEET_COLUMNS:
                value = row[name]
                if value is not None and value != "":
                    field_value(name, value)
            if not row["First Name"] or not row["Last Name"]:
                raise ValueError(f"{pid}: First Name and Last Name must not be empty")
            if all(row.get(c) for c in ("Birth Year", "Birth Month", "Birth Day")):
                date(int(row["Birth Year"]), int(row["Birth Month"]), int(row["Birth Day"]))
    absent = sorted(set(overrides) - seen)
    if absent:
        print(f"Overrides retained for {len(absent)} absent/excluded ProA IDs: {', '.join(map(str, absent))}")
    print(f"Applied {changes} manual field override(s); matched {len(seen & set(overrides))} player(s)")
    return changes


def refresh_hidden_attributes(workbook, rosters: dict, year: int) -> int:
    players = {int(p["proa_id"]): p for team in rosters.values() for p in team}
    averages = league_defense_averages(list(players.values()))
    updates = []
    for ws in workbook:
        if ws.title.startswith("_"):
            continue
        columns = {cell.value: cell.column for cell in ws[1] if cell.value}
        for index in range(2, ws.max_row + 1):
            raw = ws.cell(index, columns["ProA ID"]).value
            if raw is None:
                continue
            pid = player_id(raw)
            if pid not in players:
                raise ValueError(f"{pid}: missing cached rating inputs; refresh the roster cache")
            source = dict(players[pid])
            if source.get("games", 0) > 0 and "fga_avg" not in source:
                raise ValueError(f"{pid}: cached ratings lack FGA/foul inputs; refresh the roster cache")
            for name, key in (("Position", "position"), ("Birth Year", "birth_year"), ("Height", "height_m")):
                source[key] = ws.cell(index, columns[name]).value
            ctx = player_context(source, year=year, defense_averages=averages)
            ratings = hidden_ratings(ctx, field_value("Speed", ws.cell(index, columns["Speed"]).value))
            updates.append((ws, index, ratings))
    for ws in workbook:
        if ws.title.startswith("_"):
            continue
        columns = {cell.value: cell.column for cell in ws[1] if cell.value}
        for name in HIDDEN_ATTRS:
            if name not in columns:
                column = columns["Headshot ID"]
                ws.insert_cols(column)
                ws.cell(1, column, name)
                columns = {cell.value: cell.column for cell in ws[1] if cell.value}
    for ws, index, ratings in updates:
        columns = {cell.value: cell.column for cell in ws[1] if cell.value}
        for name, value in ratings.items():
            ws.cell(index, columns[name], value)
    return len(updates)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, default=ROOT / "proa_scraped.xlsx")
    parser.add_argument("--overrides", type=Path, default=OVERRIDES)
    parser.add_argument("--blacklist", type=Path, default=BLACKLIST)
    parser.add_argument("--refresh-hidden", action="store_true", help="Regenerate hidden attributes, then reapply overrides")
    parser.add_argument("--rating-cache", type=Path, help="Enriched all_rosters.json from the scraper")
    parser.add_argument("--rating-year", type=int, help="Season start year used for age thresholds")
    args = parser.parse_args()
    if args.refresh_hidden and (args.rating_cache is None or args.rating_year is None):
        parser.error("--refresh-hidden requires --rating-cache and --rating-year")
    wb = openpyxl.load_workbook(args.workbook)
    try:
        if args.refresh_hidden:
            count = refresh_hidden_attributes(wb, json.loads(args.rating_cache.read_text(encoding="utf-8")), args.rating_year)
            print(f"Regenerated hidden attributes for {count} players")
        apply_overrides(wb, load_overrides(args.overrides), blacklist=load_blacklist(args.blacklist))
        from overall_sheet import add_overall
        add_overall(wb)
        wb.save(args.workbook)
    finally:
        wb.close()
    print(f"Updated {args.workbook}; override and blacklist CSVs unchanged")


if __name__ == "__main__":
    main()
