"""Fit the in-game Overall formula from observed values and store it as data/overall_model.json.

Data: overall_ratings.xlsx (one sheet per team; the 'Overall' column holds the value displayed in game, other columns are
ignored) joined by ProA ID with the attributes in proa_scraped.xlsx (these are the values written to the roster).
Add more rows to overall_ratings.xlsx (or new team sheets) and re-run:

    python scripts/fit_overall.py [--displayed overall_ratings.xlsx] [--players proa_scraped.xlsx]

Model: per primary position p, overall = b_p + sum_a W_p[a] * attr[a]. The weights are a ridge fit with a shared weight vector
plus a shrunken per-position deviation (hierarchical), because the data are strongly clustered by position. Shrinkage strength
and height/weight use are picked by leave-one-out cross validation. The in-game value is an integer, so the noise floor is
about 0.29 (uniform rounding); the report shows how close the fit gets.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overall_data import ATTRS, POS, ROOT, dataset  # noqa: E402

OUT = ROOT / "data" / "overall_model.json"
SCALES = (0.0, 0.1, 0.2, 0.3, 0.5, 1.0)  # weight of the per-position deviation columns (0 = one shared weight vector)
LAMBDAS = (0.1, 1, 3, 10, 30, 100)


def design(X, P, H, s, use_hw):
    cols = [X] + [X * P[:, [k]] * s for k in range(len(POS))] + [P]
    if use_hw:
        cols.append(H)
    return np.hstack(cols)


def ridge(F, y, lam, n_pen):
    pen = np.r_[np.ones(n_pen), np.zeros(F.shape[1] - n_pen)]
    return np.linalg.solve(F.T @ F + lam * np.diag(pen) + 1e-9 * np.eye(F.shape[1]), F.T @ y)


def loo(F, y, lam, n_pen):
    e = np.empty(len(y))
    for i in range(len(y)):
        m = np.arange(len(y)) != i
        e[i] = y[i] - F[i] @ ridge(F[m], y[m], lam, n_pen)
    return np.sqrt((e ** 2).mean()), np.abs(e).max()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--displayed", default=str(ROOT / "overall_ratings.xlsx"))
    ap.add_argument("--players", default=str(ROOT / "proa_scraped.xlsx"))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    ds = dataset(a.displayed, a.players)
    y = np.array([r["ovr"] for r in ds], float)
    X = np.array([[r["attrs"][k] for k in ATTRS] for r in ds], float)
    P = np.array([[r["pos"] == p for p in POS] for r in ds], float)
    H = np.array([[r["h"], r["w"]] for r in ds])
    mu_x, mu_h, sd_h = X.mean(0), H.mean(0), H.std(0)
    Xc, Hz = X - mu_x, (H - mu_h) / sd_h
    print(f"{len(y)} observations; per position: " + ", ".join(f"{p} {int(P[:, k].sum())}" for k, p in enumerate(POS)))

    best = None
    for use_hw in (False, True):
        for s in SCALES:
            F = design(Xc, P, Hz, s, use_hw)
            n_pen = len(ATTRS) * (1 + len(POS))
            for lam in LAMBDAS:
                rmse, mx = loo(F, y, lam, n_pen)
                if best is None or rmse < best[0]:
                    best = (rmse, mx, s, lam, use_hw)
    rmse, mx, s, lam, use_hw = best
    print(f"best by leave-one-out: rmse {rmse:.3f}, max error {mx:.1f} (shared/deviation scale {s}, ridge {lam}, height/weight {use_hw})")

    F = design(Xc, P, Hz, s, use_hw)
    coef = ridge(F, y, lam, len(ATTRS) * (1 + len(POS)))
    na = len(ATTRS)
    shared = coef[:na]
    model = {"attributes": ATTRS, "positions": {}, "loo_rmse": round(float(rmse), 3), "n": int(len(y)), "use_height_weight": use_hw}
    for k, p in enumerate(POS):
        W = shared + s * coef[na * (1 + k): na * (2 + k)]
        b = coef[na * (1 + len(POS)) + k] - W @ mu_x
        model["positions"][p] = {"weights": [round(float(v), 4) for v in W], "intercept": round(float(b), 3)}
    if use_hw:
        j = na * (1 + len(POS)) + len(POS)
        gh = coef[j: j + 2]
        model["height_weight"] = {"coef_per_unit": [round(float(v), 4) for v in gh / sd_h]}  # height in m, weight in kg
        for p in POS:
            model["positions"][p]["intercept"] = round(model["positions"][p]["intercept"] - float(gh @ (mu_h / sd_h)), 3)
    Path(a.out).write_text(json.dumps(model, indent=1), encoding="utf-8")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from overall_model import predict_overall  # noqa: E402
    pred = np.array([predict_overall(r["pos"], r["attrs"], r["h"], r["w"], model) for r in ds])
    res = y - pred
    print(f"in-sample: rmse {np.sqrt((res ** 2).mean()):.3f}, max {np.abs(res).max():.2f}, "
          f"exact after rounding {int((np.round(pred) == y).sum())}/{len(y)}, within 1: {int((np.abs(np.round(pred) - y) <= 1).sum())}/{len(y)}")
    print("\neffective weights per position (x100; sum = scale of the position's overall per attribute point):")
    print(f"{'attribute':22s}" + "".join(f"{p:>7s}" for p in POS))
    for i, k in enumerate(ATTRS):
        print(f"{k:22s}" + "".join(f"{model['positions'][p]['weights'][i] * 100:7.1f}" for p in POS))
    print(f"{'sum':22s}" + "".join(f"{sum(model['positions'][p]['weights']) * 100:7.1f}" for p in POS))
    print(f"{'intercept':22s}" + "".join(f"{model['positions'][p]['intercept']:7.1f}" for p in POS))
    worst = sorted(zip(res, ds), key=lambda t: -abs(t[0]))[:8]
    print("\nlargest in-sample residuals (shown - predicted):")
    for r_, d in worst:
        print(f"  {d['name']:28s} {d['pos']:2s} shown {d['ovr']}  {r_:+.1f}")
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
