"""Dataset for the in-game Overall reverse engineering: overall_ratings.xlsx (display values read from the game,
one sheet per team, an 'Overall' column or an unnamed column right after Weight) joined by ProA ID with the 2K5
attributes that were written to the roster (proa_scraped.xlsx, clamped like build_roster does)."""
import csv
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from rating_map_2k5 import ATTR_OFFSETS, DUNK_FLAG, EXTRA_BYTE_COLS, NEUTRAL_BYTES, dunk_flag, read_attrs  # noqa: E402

ATTRS = list(ATTR_OFFSETS)
POS = ["PG", "SG", "SF", "PF", "C"]
EXTRAS = list(EXTRA_BYTE_COLS)  # unknown / derived record bytes: DunkFlag, B4F, ...
CALIBRATION = ROOT / "data" / "calibration"


def load_displayed(path):
    """{proa_id: displayed overall} for every sheet that has the Overall column."""
    out = {}
    wb = openpyxl.load_workbook(path, data_only=True)
    for ws in wb:
        rows = list(ws.iter_rows(values_only=True))
        h = list(rows[0])
        if "Overall" in h:
            i = h.index("Overall")
        elif h[11] is None and h[12] == "Close Shot":
            i = 11
        else:
            continue
        pid_col = h.index("ProA ID")
        for r in rows[1:]:
            if r[pid_col] is not None and isinstance(r[i], (int, float)):
                out[int(r[pid_col])] = int(r[i])
    return out


def default_extras(attrs):
    """Values build_roster writes for the unknown bytes when the workbook has no override column."""
    ex = {name: NEUTRAL_BYTES[off] for name, off in EXTRA_BYTE_COLS.items() if off in NEUTRAL_BYTES}
    ex["DunkFlag"] = dunk_flag(attrs["Dunk"])
    return ex


def load_players(path):
    """{proa_id: dict(pos, sec, height m, weight kg, attrs {name: int}, extras {name: byte}, sheet, name)} from a roster workbook."""
    out = {}
    wb = openpyxl.load_workbook(path, data_only=True)
    for ws in wb:
        rows = list(ws.iter_rows(values_only=True))
        h = list(rows[0])
        for r in rows[1:]:
            d = dict(zip(h, r))
            if d.get("ProA ID") is None:
                continue
            attrs = read_attrs(d)
            extras = default_extras(attrs)
            for name in EXTRAS:
                if isinstance(d.get(name), (int, float)):
                    extras[name] = int(max(0, min(99, d[name])))
            out[int(d["ProA ID"])] = dict(pos=d["Position"], sec=d["Secondary Position"], h=float(d["Height"]), w=float(d["Weight"]),
                                          attrs=attrs, extras=extras, sheet=ws.title, name=f'{d["First Name"]} {d["Last Name"]}')
    return out


def dataset(displayed_path=ROOT / "overall_ratings.xlsx", players_path=ROOT / "proa_scraped.xlsx"):
    shown, pl = load_displayed(displayed_path), load_players(players_path)
    rows = []
    for pid, ovr in shown.items():
        if pid in pl:
            rows.append(dict(pl[pid], pid=pid, ovr=ovr, source="observed"))
    return rows


def calibration_dataset(folder=CALIBRATION):
    """Rows from a calibration round (make_calibration.py): observed.csv overall values + proa_calibration.xlsx ratings."""
    obs, xlsx = Path(folder) / "observed.csv", Path(folder) / "proa_calibration.xlsx"
    if not (obs.exists() and xlsx.exists()):
        return []
    pl = load_players(xlsx)
    rows = []
    for r in csv.DictReader(open(obs, encoding="utf-8")):
        try:
            ovr, pid = int(float(r["overall"])), int(r["proa_id"])
        except (ValueError, KeyError):
            continue
        if pid in pl:
            rows.append(dict(pl[pid], pid=pid, ovr=ovr, source="calibration"))
    return rows



if __name__ == "__main__":
    ds = dataset()
    print(len(ds), "players with displayed overall")
    from collections import Counter
    print(Counter(r["pos"] for r in ds))
