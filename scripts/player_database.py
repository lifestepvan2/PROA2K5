"""Canonical generated player schema and manually maintained ProA-ID overrides.

    python scripts/player_database.py
    python scripts/player_database.py --workbook proa_scraped.xlsx
"""
import argparse
import csv
from datetime import date
import math
import re
import unicodedata
from pathlib import Path

import openpyxl

from proa_attr_model import ALL_ATTRS

ROOT = Path(__file__).resolve().parent.parent
OVERRIDES = ROOT / "data" / "overrides.csv"
BLACKLIST = ROOT / "data" / "blacklist.csv"
ACCESSORIES = ("headband", "wrist_l", "wrist_r", "arm_l", "arm_r", "knee_l", "knee_r")
IDENTITY_COLS = [
    "First Name", "Last Name", "Position", "Secondary Position", "Jersey Number",
    "Birth Year", "Birth Month", "Birth Day", "Years Pro", "Height", "Weight",
]
SHEET_COLUMNS = IDENTITY_COLS + list(ALL_ATTRS) + ["Headshot ID", "College", "Shooting Hand", *ACCESSORIES, "Skin Tone"]
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


def field_value(column, value):
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
        **dict.fromkeys(ALL_ATTRS, (25, 99)), **dict.fromkeys(ACCESSORIES, (0, 255)),
    }
    if column not in bounds:
        raise ValueError(f"Unknown player column: {column}")
    low, high = bounds[column]
    if not low <= number <= high:
        raise ValueError(f"{column}: expected {low}..{high}, got {value!r}")
    if column in ("Height", "Weight"):
        return number
    if not number.is_integer():
        raise ValueError(f"{column}: expected an integer, got {value!r}")
    return int(number)


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
    result = {}
    for row in read_csv(path, OVERRIDE_COLUMNS, ["ProA ID"]):
        pid = player_id(row["ProA ID"])
        changes = {}
        for column, value in row.items():
            if column in ("Team", "ProA ID") or not value.strip():
                continue
            if value.strip() == CLEAR:
                if column != "College":
                    raise ValueError(f"{pid}: {CLEAR} is only supported for College; use 0 for numeric fields")
                changes[column] = ""
            else:
                changes[column] = field_value(column, value)
        result[pid] = changes
    return result


def apply_overrides(workbook, overrides, *, blacklist=None):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, default=ROOT / "proa_scraped.xlsx")
    parser.add_argument("--overrides", type=Path, default=OVERRIDES)
    parser.add_argument("--blacklist", type=Path, default=BLACKLIST)
    args = parser.parse_args()
    wb = openpyxl.load_workbook(args.workbook)
    try:
        apply_overrides(wb, load_overrides(args.overrides), blacklist=load_blacklist(args.blacklist))
        from overall_sheet import add_overall
        add_overall(wb)
        wb.save(args.workbook)
    finally:
        wb.close()
    print(f"Updated {args.workbook}; override and blacklist CSVs unchanged")


if __name__ == "__main__":
    main()
