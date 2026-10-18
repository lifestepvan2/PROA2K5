"""Shared helpers for the PCSX2 texture tools (dump folder access, PS2-alpha aware loading)."""
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).parent.parent
TEX_ROOT = Path.home() / "Documents/PCSX2/textures/SLES-53022"
DUMP_DIRS = [TEX_ROOT / "dumps", TEX_ROOT / "bu"]  # bu = older, larger dump session
REPL_DIR = TEX_ROOT / "replacements"
FACE_FAMILIES = {"00001dd3", "00001dd4"}


def proa_slots():
    """{nba_slot: proa_index} from data/team_slots.csv. The final ProA team -> NBA slot mapping; all texture maps are
    keyed by NBA slot (the NBA team's textures) and the ProA logo asset is nba2k_editor/assets/<38 + proa_index>.png."""
    import csv
    order = {r["sheet"]: i for i, r in enumerate(csv.DictReader(open(ROOT / "data/proa_teams.csv", encoding="utf-8")))}
    return {int(r["nba_slot"]): order[r["sheet"]] for r in csv.DictReader(open(ROOT / "data/team_slots.csv", encoding="utf-8"))}


def prune(name, out_dir, written):
    """Delete files an earlier run of generator `name` wrote that this run no longer writes (e.g. after a team
    slot mapping change). Run state lives next to the texture folders, not inside replacements\\."""
    import json
    f = TEX_ROOT / "pipeline_managed.json"
    state = json.loads(f.read_text()) if f.exists() else {}
    written = set(written)
    gone = [k for k in state.get(name, []) if k not in written]
    for k in gone:
        (Path(out_dir) / f"{k}.png").unlink(missing_ok=True)
    state[name] = sorted(written)
    f.write_text(json.dumps(state))
    return len(gone)


def family(key):
    return key.split("-")[-1]


def dump_files():
    """key -> path over all dump folders (first folder wins)."""
    out = {}
    for d in DUMP_DIRS:
        if d.is_dir():
            for p in d.glob("*.png"):
                out.setdefault(p.stem, p)
    return out


def load_rgba(path):
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)


def over_white(rgba, bg=255):
    """Composite a dump over a flat background. PS2 alpha is 0..128 (128 = opaque)."""
    a = np.clip(rgba[..., 3:].astype(np.float32) / 128, 0, 1)
    return (rgba[..., :3] * a + bg * (1 - a)).astype(np.uint8)


def load_white(path, bg=255):
    return over_white(load_rgba(path), bg)
