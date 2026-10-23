"""Fit the in-game Overall formula from observed values and store it as data/overall_model.json.

Observations (all optional, merged):
  1. overall_ratings.xlsx: one sheet per team, the 'Overall' column holds the value displayed in game (other columns ignored);
     joined by ProA ID with the ratings in proa_scraped.xlsx (the values that were written to the roster).
  2. data/calibration/observed.csv: a calibration round (make_calibration.py) with random ratings/positions/bytes; its roster
     file data/calibration/proa_calibration.xlsx provides the ratings.
Add observations and re-run:

    python scripts/fit_overall.py [--displayed overall_ratings.xlsx] [--players proa_scraped.xlsx] [--calibration data/calibration]

Model: per primary position p, overall = b_p + sum_a W_p[a] * rating[a] (+ optional shared terms for the unknown record bytes
and for height/weight). The rating weights are a ridge fit with a shared weight vector plus a shrunken per-position deviation,
because real-roster data are strongly clustered by position. Shrinkage strength and whether the extra terms are used are picked
by leave-one-out cross validation (exact, via the hat matrix). The displayed value is an integer, so the noise floor is about
0.29 (uniform rounding); the report shows how close the fit gets.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overall_data import ATTRS, CALIBRATION, EXTRAS, POS, ROOT, calibration_dataset, dataset  # noqa: E402

OUT = ROOT / "data" / "overall_model.json"
SCALES = (0.0, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0)  # weight of the per-position deviation columns (0 = one shared weight vector)
LAMBDAS = (0.01, 0.1, 1, 3, 10, 30, 100)


def design(X, P, E, H, s, use_extras, use_hw):
    cols = [X] + [X * P[:, [k]] * s for k in range(len(POS))] + [P]
    if use_extras:
        cols.append(E)
    if use_hw:
        cols.append(H)
    return np.hstack(cols)


def ridge_matrix(F, lam, n_pen):
    pen = np.r_[np.ones(n_pen), np.zeros(F.shape[1] - n_pen)]
    return np.linalg.inv(F.T @ F + lam * np.diag(pen) + 1e-8 * np.eye(F.shape[1]))


def loo(F, y, lam, n_pen):
    M = ridge_matrix(F, lam, n_pen)
    hat = np.einsum("ij,jk,ik->i", F, M, F)
    r = y - F @ (M @ (F.T @ y))
    e = r / (1 - hat)
    return float(np.sqrt((e ** 2).mean())), float(np.abs(e).max())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--displayed", default=str(ROOT / "overall_ratings.xlsx"))
    ap.add_argument("--players", default=str(ROOT / "proa_scraped.xlsx"))
    ap.add_argument("--calibration", default=str(CALIBRATION), help="folder with observed.csv + proa_calibration.xlsx")
    ap.add_argument("--calibration-only", action="store_true", help="ignore overall_ratings.xlsx (real-roster observations)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    ds = ([] if a.calibration_only else dataset(a.displayed, a.players)) + calibration_dataset(a.calibration)
    y = np.array([r["ovr"] for r in ds], float)
    X = np.array([[r["attrs"][k] for k in ATTRS] for r in ds], float)
    P = np.array([[r["pos"] == p for p in POS] for r in ds], float)
    E = np.array([[r["extras"][k] for k in EXTRAS] for r in ds], float)
    H = np.array([[r["h"], r["w"]] for r in ds])
    mu_x, mu_e, mu_h, sd_h = X.mean(0), E.mean(0), H.mean(0), H.std(0)
    sd_e = np.where(E.std(0) > 0, E.std(0), 1.0)
    Xc, Ec, Hz = X - mu_x, (E - mu_e) / sd_e, (H - mu_h) / sd_h
    src = {s: sum(r["source"] == s for r in ds) for s in ("observed", "calibration")}
    print(f"{len(y)} observations {src}; per position: " + ", ".join(f"{p} {int(P[:, k].sum())}" for k, p in enumerate(POS)))
    na = len(ATTRS)
    n_pen = na * (1 + len(POS))

    results = []
    for use_extras in (False, True):
        for use_hw in (False, True):
            for s in SCALES:
                F = design(Xc, P, Ec, Hz, s, use_extras, use_hw)
                for lam in LAMBDAS:
                    results.append((*loo(F, y, lam, n_pen), s, lam, use_extras, use_hw))
    print("best leave-one-out error per variant (rmse, max error):")
    for ue in (False, True):
        for uh in (False, True):
            b = min((r for r in results if r[4] == ue and r[5] == uh), key=lambda r: r[0])
            print(f"  extra bytes {'yes' if ue else 'no ':3s} height/weight {'yes' if uh else 'no ':3s}: {b[0]:.3f}  {b[1]:.2f}  (deviation scale {b[2]}, ridge {b[3]})")
    best = min(results, key=lambda r: r[0] + 0.02 * (r[4] + r[5]))  # prefer the simpler model unless clearly better
    rmse, mx, s, lam, use_extras, use_hw = best
    print(f"chosen: extra bytes {use_extras}, height/weight {use_hw}, deviation scale {s}, ridge {lam}: LOO rmse {rmse:.3f}, max {mx:.2f}")

    F = design(Xc, P, Ec, Hz, s, use_extras, use_hw)
    M = ridge_matrix(F, lam, n_pen)
    e = (y - F @ (M @ (F.T @ y))) / (1 - np.einsum("ij,jk,ik->i", F, M, F))
    for name in ("observed", "calibration"):
        sel = np.array([r["source"] == name for r in ds])
        if sel.any():
            print(f"  LOO on {name} rows: rmse {np.sqrt((e[sel] ** 2).mean()):.3f}, max {np.abs(e[sel]).max():.2f} ({int(sel.sum())} rows)")
    coef =  ridge_matrix(F, lam, n_pen) @ (F.T @ y)
    shared = coef[:na]
    j = n_pen + len(POS)
    model = {"attributes": ATTRS, "positions": {}, "loo_rmse": round(rmse, 3), "n": int(len(y))}
    offset = 0.0
    if use_extras:
        ce = coef[j: j + len(EXTRAS)] / sd_e
        model["extras"] = {"names": EXTRAS, "weights": [round(float(v), 4) for v in ce]}
        offset -= float(ce @ mu_e)
        j += len(EXTRAS)
    if use_hw:
        ch = coef[j: j + 2] / sd_h
        model["height_weight"] = {"coef_per_unit": [round(float(v), 4) for v in ch]}  # height in m, weight in kg
        offset -= float(ch @ mu_h)
    for k, p in enumerate(POS):
        W = shared + s * coef[na * (1 + k): na * (2 + k)]
        b = coef[n_pen + k] - W @ mu_x + offset
        model["positions"][p] = {"weights": [round(float(v), 4) for v in W], "intercept": round(float(b), 3)}
    Path(a.out).write_text(json.dumps(model, indent=1), encoding="utf-8")

    from overall_model import predict_overall  # noqa: E402
    pred = np.array([predict_overall(r["pos"], r["attrs"], r["h"], r["w"], r["extras"], model) for r in ds])
    res = y - pred
    print(f"in-sample: rmse {np.sqrt((res ** 2).mean()):.3f}, max {np.abs(res).max():.2f}, "
          f"exact after rounding {int((np.round(pred) == y).sum())}/{len(y)}, within 1: {int((np.abs(np.round(pred) - y) <= 1).sum())}/{len(y)}")
    print("\nrating weights per position (x100):")
    print(f"{'rating':22s}" + "".join(f"{p:>7s}" for p in POS))
    for i, k in enumerate(ATTRS):
        print(f"{k:22s}" + "".join(f"{model['positions'][p]['weights'][i] * 100:7.1f}" for p in POS))
    print(f"{'sum':22s}" + "".join(f"{sum(model['positions'][p]['weights']) * 100:7.1f}" for p in POS))
    print(f"{'intercept':22s}" + "".join(f"{model['positions'][p]['intercept']:7.1f}" for p in POS))
    if use_extras:
        print("\nextra record bytes (weight per point x100): " + ", ".join(f"{n} {w * 100:.1f}" for n, w in zip(EXTRAS, model["extras"]["weights"])))
    if use_hw:
        print(f"height/weight: {model['height_weight']['coef_per_unit'][0]:.2f} per m, {model['height_weight']['coef_per_unit'][1]:.3f} per kg")
    worst = sorted(zip(res, ds), key=lambda t: -abs(t[0]))[:8]
    print("\nlargest in-sample residuals (shown - predicted):")
    for r_, d in worst:
        print(f"  {d['name']:28s} {d['pos']:2s} shown {d['ovr']}  {r_:+.1f}  [{d['source']}]")
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
