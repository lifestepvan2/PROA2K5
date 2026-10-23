"""Predicted in-game Overall (model fitted by fit_overall.py, stored in data/overall_model.json)."""
import json
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "overall_model.json"
_cache = {}
POS_NAMES = ["PG", "SG", "SF", "PF", "C"]


def load_model(path=MODEL_PATH):
    if path not in _cache:
        _cache[path] = json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else None
    return _cache[path]


def predict_overall(pos, attrs, height_m=None, weight_kg=None, extras=None, model=None):
    """pos: 'PG'..'C' (or index 0-4); attrs: {rating: value}; extras: {unknown byte column: value}, defaults to what build_roster
    writes. Returns the unrounded predicted overall (None without a model)."""
    model = model or load_model()
    if model is None:
        return None
    if isinstance(pos, int):
        pos = POS_NAMES[pos]
    m = model["positions"][pos]
    v = m["intercept"] + sum(w * attrs[a] for w, a in zip(m["weights"], model["attributes"]))
    ex = model.get("extras")
    if ex:
        if extras is None:
            from overall_data import default_extras
            extras = default_extras(attrs)
        v += sum(w * extras[n] for n, w in zip(ex["names"], ex["weights"]))
    hw = model.get("height_weight")
    if hw and height_m is not None and weight_kg is not None:
        v += hw["coef_per_unit"][0] * height_m + hw["coef_per_unit"][1] * weight_kg
    return v
