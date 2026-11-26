"""Read-only historical logo key inventory for migration audits."""
import csv

import numpy as np

from texlib import ROOT, dump_files, load_rgba, proa_slots

SRC = ROOT / "data/texture_map/logo_variants.csv"
ACCEPT = dict(score=0.75, mae=27.0, content=0.25, size=0.45)  # tuned on reviews of ~90 + 72 matches; 0.75-0.80 only adds right halves of split logos
_cache = {}


def logo_matches(slots=None):
    """All logo-variant rows that pass the acceptance thresholds (mode A: window of a reference logo frame),
    optionally restricted to a set of NBA team slots."""
    out = []
    files = dump_files()
    rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
    # thin logos (Rockets, Wizards) have little ink even in the full frame: scale the content threshold by it
    ref_content = {r["key"]: float(r["content"]) for r in rows if r["key"] == r["ref_key"]}
    for r in rows:
        if (slots is not None and int(r["team_slot"]) not in slots) or r["mode"] != "A" or r["key"] not in files:
            continue
        w, h = float(r["w"]), float(r["h"])
        min_content = min(ACCEPT["content"], 0.7 * ref_content.get(r["ref_key"], 1.0))
        if (float(r["score"]) < ACCEPT["score"] or float(r["mae"]) > ACCEPT["mae"]
                or float(r["content"]) < min_content or max(w, h) < ACCEPT["size"]):
            continue
        out.append(r)
    return out


def accepted():
    """Matches of NBA slots occupied by ProA teams that can be replaced (the reference frame is not one half of a split logo)."""
    files = dump_files()
    return [r for r in logo_matches(set(proa_slots())) if ref_box(r["ref_key"], files) is not None]


PARTIAL_REFS = ("190a7d68", "31fbe669")  # Cavaliers wordmark halves ("Cav" / "ALIERS"): one logo split over two textures


def ref_box(ref_key, files):
    """Content box of a reference frame (native px), or None for split-logo reference frames."""
    if ref_key not in _cache:
        a = load_rgba(files[ref_key])[..., 3]
        ys, xs = np.where(a > 8)
        h, w = a.shape
        box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
        _cache[ref_key] = None if ref_key.startswith(PARTIAL_REFS) else (box, (w, h))
    return _cache[ref_key]






def managed_keys():
    return {r["key"] for r in accepted()}
