"""Per-home-team texture usage scan: which dumped textures does the game draw in each NBA arena?

For every NBA team slot the script restarts PCSX2 from savestate slot 2 (Team Select, right-hand team = slot 28), steps the
right-hand (home) team to the wanted slot, starts the game and records every texture PCSX2 dumps while the game loads and the
intro plays. PCSX2 only dumps a texture once per process, so the dump folder is swapped for an empty one and PCSX2 is restarted
for every slot; the original folder is restored (plus any new files) when the scan ends.

Textures that are drawn for one home team only are team specific, the rest is shared ("various").
Output: data/texture_labels/home_scan/slot<N>.txt (dump key + seconds after pressing "begin game" per line), then `python scripts/arena_scan.py report`.
Usage:  python scripts/arena_scan.py scan [SLOT ...]    (default 0..29; PCSX2 must be able to take the foreground)
        python scripts/arena_scan.py report              (writes data/texture_labels/home_scan_summary.csv)
        python scripts/arena_scan.py restore             (undo an interrupted scan: puts the original dump folder back)
"""
import csv
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from pine_client import PineClient  # noqa: E402

OUT = ROOT / "data/texture_labels/home_scan"
TEX = Path(r"C:\Users\Sebastian\Documents\PCSX2\textures\SLES-53022")
DUMPS, FULL = TEX / "dumps", TEX / "dumps_full_backup"
PCSX2 = r"C:\Program Files\PCSX2\pcsx2-qt.exe"
ISO = r"C:\Tools\isos\ESPN NBA 2K5 (Europe).iso"
STATE = Path(r"C:\Users\Sebastian\Documents\PCSX2\sstates\SLES-53022 (CA37B42E).02.p2s")
SLOT_ADDR, START_SLOT = 0x801908, 28  # right-hand team slot on the Team Select screen


def press(b, wait=1.0):
    subprocess.run([sys.executable, str(ROOT / "scripts/pcsx2_controller.py"), b], capture_output=True)
    time.sleep(wait)


def pcsx2_pid():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq pcsx2-qt.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return int(out.strip().split(",")[1].strip('"')) if "pcsx2" in out else None


def kill():
    pid = pcsx2_pid()
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        time.sleep(4)


def launch():
    subprocess.Popen([PCSX2, "-batch", "-nogui", "-statefile", str(STATE), "--", ISO])


def read_slot():
    try:
        with PineClient() as p:
            return p.read32(SLOT_ADDR)
    except Exception:
        return None


def swap_in():
    if FULL.exists():
        raise SystemExit(f"{FULL} exists - run 'restore' first")
    DUMPS.rename(FULL)
    DUMPS.mkdir()


def restore():
    if not FULL.exists():
        return
    for f in DUMPS.glob("*.png"):
        if not (FULL / f.name).exists():
            shutil.move(str(f), FULL / f.name)
    shutil.rmtree(DUMPS)
    FULL.rename(DUMPS)
    print("dump folder restored:", len(list(DUMPS.glob("*.png"))), "files")


def scan_slot(slot, window=(55, 25, 120)):
    kill()
    for f in DUMPS.glob("*"):
        f.unlink()
    launch()
    t0 = time.time()
    while read_slot() != START_SLOT:
        if time.time() - t0 > 150:
            raise SystemExit("savestate did not load")
        time.sleep(3)
    time.sleep(4)
    press("right", 1)
    cur = None
    for _ in range(80):
        cur = read_slot()
        if cur == slot:
            break
        press("r1" if slot >= START_SLOT else "l1", 1.3)
    else:
        raise SystemExit(f"could not reach slot {slot} (at {cur})")
    press("start", 4)
    press("cross", 1)
    t0, last, last_t = time.time(), -1, time.time()
    while True:
        time.sleep(5)
        n = len(os.listdir(DUMPS))
        if n != last:
            last, last_t = n, time.time()
        if time.time() - t0 > window[2] or (time.time() - t0 > window[0] and time.time() - last_t > window[1]):
            break
    t_go = t0
    rows = sorted((f.stem, f.stat().st_mtime - t_go) for f in DUMPS.glob("*.png"))
    keys = [k for k, _ in rows]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"slot{slot}.txt").write_text("\n".join(f"{k} {t:.0f}" for k, t in rows))
    print(f"slot {slot}: {len(keys)} textures dumped in {time.time() - t0:.0f}s", flush=True)


def report():
    """key -> home teams that drew it; writes data/texture_labels/home_scan_summary.csv."""
    names = {int(r["slot"]): r["nickname"] for r in csv.DictReader(open(ROOT / "data/nba_defaults/teams_unknown.csv", encoding="utf-8"))}
    uses = {}
    for f in OUT.glob("slot*.txt"):
        s = int(f.stem[4:])
        for line in f.read_text().splitlines():
            uses.setdefault(line.split()[0], set()).add(s)
    scanned = len(list(OUT.glob("slot*.txt")))
    with open(ROOT / "data/texture_labels/home_scan_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "n_home_teams", "of", "teams"])
        for k, s in sorted(uses.items()):
            w.writerow([k, len(s), scanned, "|".join(names.get(x, str(x)) for x in sorted(s))])
    print(f"{len(uses)} keys over {scanned} home teams")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "restore":
        restore()
    elif cmd == "report":
        report()
    else:
        slots = [int(x) for x in sys.argv[2:]] or list(range(30))
        swap_in()
        try:
            for s in slots:
                scan_slot(s)
        finally:
            kill()
            restore()
            launch()


