import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scrape_proa_roster as scraper
from season_stats import COUNT_KEYS, available_seasons, history_stats, parse_season_totals, player_history, pool_seasons


def table(games=10, points=30, league="ProA", team=True, fouls=True):
    header = ["", *(["Team"] if team else []), "G", "Min", "2P-A-R", "3P-A-R",
              "FT-A-R", "P", "A", "R: O-D-T", *(["F"] if fouls else []), "BL", "ST", "TO"]
    row = ["HR", *(["ABC"] if team else []), str(games), "100:30 10:03", "10 - 20",
           "2 - 8", "4 - 5", str(points), "8", "3 - 9 - 12",
           *(["15 1.5"] if fouls else []), "2", "4", "7"]
    return (f"<h5>{league} - Example</h5><table><tr>" +
            "".join(f"<th>{c}</th>" for c in header) + "</tr><tr>" +
            "".join(f"<td>{c}</td>" for c in row) + "</tr></table>")


def selector(*years, selected=None):
    return '<select name="season">' + "".join(
        f'<option value="{y}/{y+1}"' + (' selected' if selected == y else '') +
        f'>{y}/{y+1}</option>' for y in years) + '</select>'


class SeasonStatsTests(unittest.TestCase):
    def test_fouls_seconds_and_unknown_starts(self):
        t = parse_season_totals(table(), proa_only=True)
        stats = history_stats(t)
        self.assertEqual(stats["totals"]["SEC"], 6030)
        self.assertEqual(stats["totals"]["MIN"], 100.5)
        self.assertEqual(stats["totals"]["FLS"], 15)
        self.assertIsNone(stats["totals"]["GS"])
        self.assertEqual(stats["averages"]["FPG"], 1.5)

    def test_combined_summary_wins_over_team_rows(self):
        result = parse_season_totals(table() + table() + table(games=20, team=False), proa_only=True)
        self.assertEqual(result["g"], 20)

    def test_mixed_league_combined_summary_is_not_used(self):
        result = parse_season_totals(
            table() + table(league="ProB") + table(games=20, team=False, league="Gesamt"),
            proa_only=True)
        self.assertEqual(result["g"], 10)
        self.assertIsNone(parse_season_totals(table(league="ProB"), proa_only=True))
        self.assertIsNone(parse_season_totals(table(league="BBL"), proa_only=True))

    def test_team_summaries_are_added_when_no_combined(self):
        self.assertEqual(parse_season_totals(table() + table(), proa_only=True)["g"], 20)

    def test_unknown_league_and_incomplete_headers_fail(self):
        with self.assertRaises(ValueError):
            parse_season_totals(table(league="Unknown"), proa_only=True)
        with self.assertRaises(ValueError):
            parse_season_totals(table().replace("<th>TO</th>", "<th>?</th>"), proa_only=True)
        with self.assertRaises(ValueError):
            parse_season_totals(table().replace("<td>7</td>", "<td></td>"), proa_only=True)

    def test_unavailable_fouls_are_not_zero(self):
        stats = history_stats(parse_season_totals(table(fouls=False), proa_only=True))
        self.assertIsNone(stats["totals"]["FLS"])
        self.assertIsNone(stats["averages"]["FPG"])

    def test_career_uses_sums_not_mean_of_season_rates(self):
        a = parse_season_totals(table(games=10, points=100))
        b = parse_season_totals(table(games=20, points=50))
        b["p2m"], b["p2a"] = 30, 60
        result = player_history({2024: a, 2025: b, 2026: None})
        self.assertEqual(result["career"]["totals"]["PTS"], 150)
        self.assertEqual(result["career"]["averages"]["PPG"], 5)
        self.assertAlmostEqual(result["career"]["averages"]["FG%"], 100 * 44 / 96, places=3)
        self.assertEqual(len(result["seasons"]), 2)
        self.assertEqual(len(result["checked_seasons"]), 3)

    def test_empty_career_and_unchanged_rating_weights(self):
        self.assertEqual(player_history({2026: None})["career"]["totals"]["GP"], 0)
        t = parse_season_totals(table())
        self.assertEqual(pool_seasons({2026: t}, 2026)["games"], 10)
        self.assertEqual(set(COUNT_KEYS) - set(t), set())

    def test_source_rebound_inconsistency_is_preserved_and_reported(self):
        totals = parse_season_totals(table())
        totals["reb"] += 1
        stats = history_stats(totals)
        self.assertEqual(stats["totals"]["REB"], 13)
        self.assertEqual(stats["totals"]["OREB"] + stats["totals"]["DREB"], 12)
        self.assertIn("source figures preserved", stats["warnings"][0])

    def test_season_discovery_and_old_cache_reparse(self):
        pages = {
            "player_1": selector(2026, 2020, selected=2026) + table(),
            "player_1__2020_2021": selector(2026, 2020, selected=2020) + table(),
        }
        self.assertEqual(available_seasons(pages["player_1"]), [2026, 2020])
        with patch.object(scraper, "fetch_html", side_effect=lambda u, s, k, **kw: pages[k]), \
                patch.object(scraper, "save_json_cache"):
            result = scraper.collect_player_seasons(1, "2026_2027", 0)
        self.assertEqual(set(result), {2020, 2026})
        self.assertEqual(result[2020]["fls"], 15)

    def test_wrong_season_response_is_rejected(self):
        html = selector(2026, 2020, selected=2026) + table()
        with patch.object(scraper, "fetch_html", return_value=html), \
                patch.object(scraper, "save_json_cache"), self.assertRaises(ValueError):
            scraper.collect_player_seasons(1, "2026_2027", 5)

    def test_rating_input_is_preserved_separately_from_proa_archive(self):
        pages = {
            "player_1": selector(2026, 2025, selected=2026) + table(),
            "player_1__2025_2026": selector(2026, 2025, selected=2025) + table(league="ProB"),
        }
        ratings = {}
        with patch.object(scraper, "fetch_html", side_effect=lambda u, s, k, **kw: pages[k]), \
                patch.object(scraper, "save_json_cache"):
            result = scraper.collect_player_seasons(1, "2026_2027", 5, rating_seasons=ratings)
        self.assertIsNone(result[2025])
        self.assertEqual(ratings[2025]["g"], 10)
        self.assertEqual(pool_seasons(ratings, 2026)["games"], 20)

    def test_requested_prior_season_is_not_parsed_from_latest_get(self):
        pages = {
            "player_1": selector(2026, 2025, selected=2026) + table(points=99),
            "player_1__2025_2026": selector(2026, 2025, selected=2025) + table(points=30),
        }
        with patch.object(scraper, "fetch_html", side_effect=lambda u, s, k, **kw: pages[k]), \
                patch.object(scraper, "save_json_cache"):
            result = scraper.collect_player_seasons(1, "2025_2026", 0)
        self.assertEqual(result[2025]["pts"], 30)
        self.assertNotIn(2026, result)


if __name__ == "__main__":
    unittest.main()
