"""Season-total parsing and multi-season pooling for ProA player pages.

parse_season_totals(html)  raw counting stats of the season shown on a player page (None when he did not play)
pool_seasons(seasons, current_year)  one set of stats from all available seasons: recent seasons count more, and seasons
                                     with few games count less. The result feeds PlayerContext (proa_attr_model.py).
"""
import math
import re

from bs4 import BeautifulSoup

FULL_WEIGHT_AGE = 1     # the current and the previous season both count fully
WEIGHT_STEP = 0.2       # lost per season further back: ages 2..5 -> 0.8, 0.6, 0.4, 0.2
LOW_GAMES = 10          # a season with fewer games gets LOW_GAMES_FACTOR on top
LOW_GAMES_FACTOR = 0.5

COUNT_KEYS = ["g", "sec", "p2m", "p2a", "p3m", "p3a", "ftm", "fta", "pts", "ast", "oreb", "dreb", "reb", "blk", "stl", "tov"]


def _nums(txt):
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", txt.replace(",", "."))]


def _seconds(txt):
    m = re.match(r"\s*(\d+):(\d{2})", txt)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else 0


def _row_totals(header, cells, *, strict=False):
    """Counting stats from one summary row. Cells hold 'total average' pairs, shooting cells 'made - att average - ... pct'."""
    c = dict(zip(header, cells))
    if strict and len(cells) != len(header):
        raise ValueError("Season summary row/header length differs")

    def first(name, k=1):
        n = _nums(c.get(name, ""))
        if strict and len(n) < k:
            raise ValueError(f"Missing counting values in season column {name!r}")
        return n[:k] + [0.0] * (k - len(n))

    if strict and not re.match(r"\s*\d+:[0-5]\d", c.get("Min", "")):
        raise ValueError(f"Invalid season minutes: {c.get('Min')!r}")
    reb = first("R: O-D-T", 3)
    out = {
        "g": int(first("G")[0]), "sec": _seconds(c.get("Min", "")),
        "p2m": first("2P-A-R", 2)[0], "p2a": first("2P-A-R", 2)[1],
        "p3m": first("3P-A-R", 2)[0], "p3a": first("3P-A-R", 2)[1],
        "ftm": first("FT-A-R", 2)[0], "fta": first("FT-A-R", 2)[1],
        "pts": first("P")[0], "ast": first("A")[0],
        "oreb": reb[0], "dreb": reb[1], "reb": reb[2],
        "blk": first("BL")[0], "stl": first("ST")[0], "tov": first("TO")[0],
        "fls": int(first("F")[0]) if _nums(c.get("F", "")) else None,
        "gs": None,
    }
    return out


def parse_season_totals(html, *, proa_only=False):
    """Regular-season totals of the season selected on a player page, or None if the page has no season table.

    A page lists game logs, one summary table per team and, for players with several teams, a combined summary
    (header without 'Team'). The combined table wins; otherwise the team tables are added up.
    """
    soup = BeautifulSoup(html, "html.parser")
    totals, teams, leagues = [], [], set()
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        if "Min" not in header or "G" not in header:  # game logs have 'Datum' instead of 'G'
            continue
        heading = table.find_previous(["h2", "h3", "h4", "h5"])
        title = heading.get_text(" ", strip=True) if heading else ""
        league = re.match(r"^(ProA|ProB|BBL)\b", title)
        if league:
            leagues.add(league[1])
        if proa_only:
            required = {"G", "Min", "2P-A-R", "3P-A-R", "FT-A-R", "P", "A", "R: O-D-T", "BL", "ST", "TO"}
            if missing := required - set(header):
                raise ValueError(f"Incomplete season summary header: {sorted(missing)}")
            if league and league[1] != "ProA":
                continue
            if "Team" in header and not league:
                raise ValueError(f"Cannot classify season summary league: {title!r}")
            if "Team" not in header and not league and not title.startswith("Gesamt"):
                raise ValueError(f"Cannot classify combined season summary: {title!r}")
        data = [[c.get_text(" ", strip=True) for c in r.find_all(["th", "td"])] for r in rows[1:]]
        hr = [r for r in data if r and r[0] == "HR"] or [r for r in data if r and r[0] == ""]
        if not hr:
            continue
        (teams if "Team" in header else totals).append(_row_totals(header, hr[0], strict=proa_only))
    # A global combined summary may include ProB appearances; only ProA team rows
    # are usable in that case.
    rows = (totals[:1] if not proa_only or leagues <= {"ProA"} else []) or teams
    if not rows:
        return None
    out = {k: sum(r[k] for r in rows) for k in COUNT_KEYS}
    for k in ("fls", "gs"):
        out[k] = sum(r[k] for r in rows) if all(r[k] is not None for r in rows) else None
    return out if out["g"] > 0 else None


def available_seasons(html):
    """Actual selectable start years, not a guessed backwards request range."""
    soup = BeautifulSoup(html, "html.parser")
    selector = soup.find("select", attrs={"name": "season"})
    if selector is None:
        raise ValueError("Player page has no season selector")
    years = set()
    for option in selector.find_all("option"):
        value = option.get("value", "")
        match = re.fullmatch(r"(\d{4})/(\d{4})", value)
        if not match or int(match[2]) != int(match[1]) + 1:
            raise ValueError(f"Invalid season option: {value!r}")
        years.add(int(match[1]))
    if not years:
        raise ValueError("Player season selector is empty")
    return sorted(years, reverse=True)


def history_stats(totals):
    """Unweighted counts, per-game rates and percentages (0..100). MIN retains fractions."""
    def count(key):
        value = totals.get(key)
        if value is None:
            if key not in ("fls", "gs"):
                raise ValueError(f"Missing counting stat {key}")
            return None
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0 or int(value) != value):
            raise ValueError(f"Invalid counting stat {key}: {value!r}")
        return int(value)

    counts = {name: count(key) for name, key in {
        "GP": "g", "GS": "gs", "PTS": "pts", "OREB": "oreb", "DREB": "dreb",
        "REB": "reb", "AST": "ast", "STL": "stl", "BLK": "blk", "TO": "tov",
        "3PM": "p3m", "3PA": "p3a", "FTM": "ftm", "FTA": "fta", "FLS": "fls",
    }.items()}
    counts["FGM"] = count("p2m") + count("p3m")
    counts["FGA"] = count("p2a") + count("p3a")
    counts["SEC"] = count("sec")
    counts["MIN"] = counts["SEC"] / 60
    warnings = []
    if counts["REB"] != counts["OREB"] + counts["DREB"]:
        warnings.append(f"Published REB={counts['REB']} differs from OREB+DREB="
                        f"{counts['OREB'] + counts['DREB']}; source figures preserved")
    for made, attempts in (("FGM", "FGA"), ("3PM", "3PA"), ("FTM", "FTA")):
        if counts[made] > counts[attempts]:
            raise ValueError(f"{made} exceeds {attempts}")
    rates = {name: (round(counts[key] / counts["GP"], 3) if counts["GP"] else 0.0)
             if counts[key] is not None else None
             for name, key in {
                 "PPG": "PTS", "ORPG": "OREB", "RPG": "REB", "APG": "AST",
                 "SPG": "STL", "BPG": "BLK", "TOPG": "TO", "MPG": "MIN", "FPG": "FLS",
             }.items()}
    rates.update({name: round(100 * counts[made] / counts[attempts], 3) if counts[attempts] else 0.0
                  for name, made, attempts in [
                      ("FG%", "FGM", "FGA"), ("3P%", "3PM", "3PA"), ("FT%", "FTM", "FTA"),
                  ]})
    return {"totals": counts, "averages": rates, **({"warnings": warnings} if warnings else {})}


def player_history(seasons):
    played = {year: totals for year, totals in sorted(seasons.items()) if totals}
    career = {key: sum(t[key] for t in played.values()) for key in COUNT_KEYS}
    for key in ("fls", "gs"):
        career[key] = (sum(t[key] for t in played.values())
                       if played and all(t.get(key) is not None for t in played.values()) else None)
    return {
        "seasons": {f"{year}_{year + 1}": history_stats(t) for year, t in played.items()},
        "career": history_stats(career),
        "checked_seasons": [f"{year}_{year + 1}" for year in sorted(seasons)],
    }


def season_weight(age, games):
    """age 0 = current season. 1, 1, 0.8, 0.6, 0.4, 0.2 ...; seasons under LOW_GAMES games count half."""
    w = max(0.0, 1.0 - WEIGHT_STEP * max(0, age - FULL_WEIGHT_AGE))
    return w * (LOW_GAMES_FACTOR if games < LOW_GAMES else 1.0)


def pool_seasons(seasons, current_year):
    """seasons: {start_year: totals or None}. Returns the stat fields the scraper / PlayerContext expect.

    Every count is multiplied by the season weight and summed; dividing by the weighted games gives per-game values and
    percentages as volume-weighted averages. The division normalises, so a player with fewer seasons available is not
    penalised. 'games' is the real number of games over all seasons used (the sample-size gate in the attribute model);
    'minutes_total_sec' is the weighted minutes per game times those games, so that PlayerContext.mpg is the weighted mpg.
    """
    acc = {k: 0.0 for k in COUNT_KEYS}
    used, raw_games = [], 0
    for year, t in sorted(seasons.items(), reverse=True):
        if not t or t["g"] <= 0:
            continue
        w = season_weight(current_year - year, t["g"])
        if w <= 0:
            continue
        raw_games += t["g"]
        used.append(f"{year}:{t['g']}G*{w:.2f}")
        for k in COUNT_KEYS:
            acc[k] += w * t[k]
    g = acc["g"]

    def per_game(k):
        return round(acc[k] / g, 3) if g else 0.0

    def pct(made, att):
        return round(100 * acc[made] / acc[att], 1) if acc[att] else 0.0

    fga = acc["p2a"] + acc["p3a"]
    sec_avg = acc["sec"] / g if g else 0.0
    return {
        "games": raw_games,
        "minutes_total_sec": int(round(sec_avg * raw_games)),
        "minutes_avg_str": f"{int(sec_avg) // 60}:{int(sec_avg) % 60:02d}",
        "points_avg": per_game("pts"), "assists_avg": per_game("ast"),
        "rebounds_avg": per_game("reb"), "rebounds_off_avg": per_game("oreb"), "rebounds_def_avg": per_game("dreb"),
        "steals_avg": per_game("stl"), "blocks_avg": per_game("blk"), "turnovers_avg": per_game("tov"),
        "fg_pct": round(100 * (acc["p2m"] + acc["p3m"]) / fga, 1) if fga else 0.0,
        "fg3_pct": pct("p3m", "p3a"), "ft_pct": pct("ftm", "fta"),
        "seasons_used": used,
    }
