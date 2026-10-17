"""Provisional conversion of the ProA (2K26-style, 34 columns) ratings to the 19 NBA 2K5 attributes.

PLACEHOLDER: the skill/attribute estimation step of the pipeline should eventually produce the
2K5 attributes directly; until then `convert()` derives them from the cached columns.
Record layout: docs/player_record_layout.md
"""

# attribute -> byte offset inside the 0x94 byte player record (all values 0-99)
ATTR_OFFSETS = {
    "close": 0x45, "mid": 0x46, "three": 0x47, "ft": 0x48, "layup": 0x49, "dunk": 0x4A,
    "ballhandling": 0x4D, "pass": 0x4E, "lowpost_off": 0x51, "lowpost_def": 0x52,
    "block": 0x53, "steal": 0x54, "oreb": 0x56, "dreb": 0x57, "speed": 0x58, "stamina": 0x59,
    "durability": 0x5B, "def_aware": 0x5D, "off_aware": 0x5E,
}
# bytes whose meaning is unknown; neutral values (modal NBA value) so NBA star traits do not leak
NEUTRAL_BYTES = {0x4F: 50, 0x50: 70, 0x55: 50, 0x5A: 0, 0x5C: 60, 0x5F: 75, 0x60: 75}
DUNK_FLAG = 0x4C  # tiers 0/50/99, correlates with dunking (r=0.69)


def _avg(row, *cols, w=None):
    vals = [row[c] for c in cols if isinstance(row.get(c), (int, float))]
    return sum(vals) / len(vals) if vals else 60.0


def convert(row):
    """row: dict keyed by the proa_scraped.xlsx column names -> dict of 2K5 attributes (ints 25-99)."""
    dunk = max(row["Driving Dunk"], row["Standing Dunk"]) * 0.6 + min(row["Driving Dunk"], row["Standing Dunk"]) * 0.4
    a = {
        "close": row["Close Shot"], "mid": row["Midrange Shot"], "three": row["3pt Shot"], "ft": row["Free Throws"],
        "layup": row["Driving Layup"], "dunk": dunk,
        "ballhandling": _avg(row, "Ball Control", "Speed with Ball"),
        "pass": _avg(row, "Pass Accuracy", "Passing IQ", "Passing Vision"),
        "lowpost_off": _avg(row, "Post Moves", "Post Hook", "Post Fade"),
        "lowpost_def": row["Interior Defense"],
        "block": row["Block"], "steal": row["Steal"],
        "oreb": row["Offensive Rebound"], "dreb": row["Defensive Rebound"],
        "speed": _avg(row, "Speed", "Agility"),
        "stamina": row["Stamina"],
        "durability": 70 + (row["Hustle"] - 70),  # no ProA equivalent
        "def_aware": _avg(row, "Perimeter Defense", "Help Defense IQ", "Defensive Consistency"),
        "off_aware": _avg(row, "Shot IQ", "Offensive Consistency", "Intangibles"),
    }
    return {k: int(max(25, min(99, round(v)))) for k, v in a.items()}


def dunk_flag(dunk):
    return 99 if dunk >= 75 else 50 if dunk >= 60 else 0
