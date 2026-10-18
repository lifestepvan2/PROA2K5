"""Resolve live player-model textures in a RAM snapshot: file object 'pNNN[ha].iff' -> head SCNE -> TXTR chain.

Findings (see docs/player_texture_mapping.md): each loaded player model has a file object named p<ID><h|a>.iff
(ID = u16 at record +4; h = home team, a = away team). The file object holds a pointer at +0xBC to the model's
SCNE; walking the prev pointers from there yields the neck/arm/face (hair) TXTR objects.
"""
import csv
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from txtr_inventory import wstr  # noqa: E402

NAME = re.compile(rb"p\x00(?:[0-9]\x00){2,4}[ha]\x00\.\x00i\x00f\x00f\x00")


def live_players(ram):
    """Yield (pid, side, file_obj, {texname: txtr_obj}) for every loaded player model file object."""
    for m in NAME.finditer(ram):
        a = m.start()
        s = m.group().decode("utf-16le")
        # the real file objects hold their name at offset 0 and a scene ptr at +0xBC
        scn = struct.unpack_from("<I", ram, a + 0xBC)[0]
        if not (0x100000 < scn < len(ram) - 0x20) or ram[scn + 0xC:scn + 0x10] != b"SCNE":
            continue
        texs, o = {}, struct.unpack_from("<I", ram, scn)[0]
        for _ in range(10):
            if not (0x100000 < o < len(ram) - 0x20) or ram[o + 0xC:o + 0x10] not in (b"TXTR", b"SCNE"):
                break
            if ram[o + 0xC:o + 0x10] == b"TXTR":
                texs.setdefault(wstr(ram, struct.unpack_from("<I", ram, o + 0x10)[0]), o)
            o = struct.unpack_from("<I", ram, o)[0]
        yield int(s[1:-5]), s[-5], a, texs


def collect(ram):
    """{pid: {'face': key, ...}} for the players loaded in the snapshot (keys '' when no dump matches yet)."""
    from txtr_match import match_ram
    keys = {r[0]: r[5] for r in match_ram(ram)}
    return {pid: {k: keys.get(f"{v:08x}", "") for k, v in t.items()} for pid, side, a, t in live_players(ram)}


def merge_csv(found, path=ROOT / "data/texture_map/pid_textures.csv"):
    cols = ["face", "arm", "neck", "hair"]
    rows = {}
    if path.exists():
        rows = {int(r["pid"]): r for r in csv.DictReader(open(path))}
    for pid, t in found.items():
        old = rows.get(pid, {})
        rows[pid] = {"pid": pid, **{c: t.get(c) or old.get(c, "") for c in cols}}
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["pid"] + cols)
        w.writeheader()
        w.writerows(rows[p] for p in sorted(rows))
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ram = open(sys.argv[1], "rb").read()
    else:
        from fast_scan import read_ps2_ram
        ram = read_ps2_ram()
    found = collect(ram)
    unk = sum(1 for t in found.values() if not t.get("face"))
    print(len(found), "players loaded,", unk, "without a matching face dump;", merge_csv(found), "pids stored")
