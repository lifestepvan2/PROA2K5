"""NBA 2K5 (PS2) attribute layout of the player record, and how the ProA workbook columns map onto it.

proa_attr_model.py rates the 19 2K5 attributes directly; proa_scraped.xlsx has one column per attribute (same names)
and manual edits there are written to the roster as they are. Record layout: docs/player_record_layout.md
"""

# attribute (= proa_scraped.xlsx column) -> byte offset inside the 0x94 byte player record (all values 0-99)
ATTR_OFFSETS = {
    "Close Shot": 0x45, "Midrange Shot": 0x46, "3pt Shot": 0x47, "Free Throws": 0x48, "Layup": 0x49, "Dunk": 0x4A,
    "Ball Handling": 0x4D, "Passing": 0x4E, "Post Offense": 0x51, "Post Defense": 0x52,
    "Block": 0x53, "Steal": 0x54, "Offensive Rebound": 0x56, "Defensive Rebound": 0x57, "Speed": 0x58, "Stamina": 0x59,
    "Durability": 0x5B, "Defensive Awareness": 0x5D, "Offensive Awareness": 0x5E,
}
# bytes whose meaning is unknown; neutral values (modal NBA value) so NBA star traits do not leak
NEUTRAL_BYTES = {0x4F: 50, 0x50: 70, 0x55: 50, 0x5A: 0, 0x5C: 60, 0x5F: 75, 0x60: 75}
DUNK_FLAG = 0x4C  # tiers 0/50/99, correlates with dunking (r=0.69)
# optional workbook columns that override the neutral/derived bytes (used by the calibration roster, see make_calibration.py)
EXTRA_BYTE_COLS = {"DunkFlag": DUNK_FLAG, "B4F": 0x4F, "B50": 0x50, "B55": 0x55, "B5A": 0x5A, "B5C": 0x5C, "B5F": 0x5F, "B60": 0x60}
ATTR_MIN, ATTR_MAX = 25, 99
BLANK_DEFAULT = 60  # used for an empty cell


def read_attrs(row):
    """row: dict keyed by the proa_scraped.xlsx column names -> {attribute: int 25-99}; an empty cell gets BLANK_DEFAULT."""
    out = {}
    for name in ATTR_OFFSETS:
        v = row[name]
        out[name] = int(max(ATTR_MIN, min(ATTR_MAX, round(v)))) if isinstance(v, (int, float)) else BLANK_DEFAULT
    return out


def dunk_flag(dunk):
    return 99 if dunk >= 75 else 50 if dunk >= 60 else 0
