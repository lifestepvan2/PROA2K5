"""Season-total parsing and multi-season pooling for ProA player pages.

parse_season_totals(html)  raw counting stats of the season shown on a player page (None when he did not play)
pool_seasons(seasons, current_year)  one set of stats from all available seasons: recent seasons count more, and seasons
                                     with few games count less. The result feeds PlayerContext (proa_attr_model.py).
"""
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


def _row_totals(header, cells):
    """Counting stats from one summary row. Cells hold 'total average' pairs, shooting cells 'made - att average - ... pct'."""
    c = dict(zip(header, cells))

    def first(name, k=1):
        n = _nums(c.get(name, ""))
        return n[:k] + [0.0] * (k - len(n))

    reb = first("R: O-D-T", 3)
    out = {
        "g": int(first("G")[0]), "sec": _seconds(c.get("Min", "")),
        "p2m": first("2P-A-R", 2)[0], "p2a": first("2P-A-R", 2)[1],
        "p3m": first("3P-A-R", 2)[0], "p3a": first("3P-A-R", 2)[1],
        "ftm": first("FT-A-R", 2)[0], "fta": first("FT-A-R", 2)[1],
        "pts": first("P")[0], "ast": first("A")[0],
        "oreb": reb[0], "dreb": reb[1], "reb": reb[2],
        "blk": first("BL")[0], "stl": first("ST")[0], "tov": first("TO")[0],
    }
    return out


def parse_season_totals(html):
    """Regular-season totals of the season selected on a player page, or None if the page has no season table.

    A page lists game logs, one summary table per team and, for players with several teams, a combined summary
    (header without 'Team'). The combined table wins; otherwise the team tables are added up.
    """
    soup = BeautifulSoup(html, "html.parser")
    totals, teams = [], []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        if "Min" not in header or "G" not in header:  # game logs have 'Datum' instead of 'G'
            continue
        data = [[c.get_text(" ", strip=True) for c in r.find_all(["th", "td"])] for r in rows[1:]]
        hr = [r for r in data if r and r[0] == "HR"] or [r for r in data if r and r[0] == ""]
        if not hr:
            continue
        (teams if "Team" in header else totals).append(_row_totals(header, hr[0]))
    rows = totals[:1] or teams
    if not rows:
        return None
    out = {k: sum(r[k] for r in rows) for k in COUNT_KEYS}
    return out if out["g"] > 0 else None


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
