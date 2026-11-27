import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from proa_attr_model import ALL_ATTRS, PIPELINE, PlayerContext, apply_quality_balance, build_ratings, hidden_ratings, league_defense_averages
from rating_map_2k5 import HIDDEN_ATTR_OFFSETS, HIDDEN_BOUNDS, HIDDEN_TIERS
from overall_data import player_extras
from overall_model import predict_overall
from player_database import field_value
from season_stats import COUNT_KEYS, pool_seasons


class HiddenRatingsTests(unittest.TestCase):
    def context(self, **kw):
        return replace(PlayerContext(position="PG", birth_year=2000, height_m=1.9,
                                     weight_kg=85, games=10, minutes_total_sec=12000,
                                     fga_avg=10, fg_pct=45, turnovers_avg=2, fouls_per_min=.1,
                                     rating_year=2026, league_steals_avg=1, league_blocks_avg=.5), **kw)

    def values(self, **kw):
        return hidden_ratings(self.context(**kw), 80)

    def test_standing_dunk_position_height_boundaries(self):
        for pos, height, expected in (("PG", 2.2, 0), ("SG", 2.2, 0), ("SF", 2.2, 0),
                                      ("PF", 2.2, 50), ("C", 2.10, 50), ("C", 2.11, 99)):
            with self.subTest(pos=pos, height=height):
                values = self.values(position=pos, height_m=height)
                self.assertEqual(values["Standing Dunk"], expected)
                self.assertEqual(values["Dunk Range"], 10)

    def test_offense_both_gates_required_for_99(self):
        for fg, turnovers, expected in ((55, 1, 99), (55, 1.01, 75), (54.9, 1, 75),
                                         (50, 2, 75), (49, 1.5, 75), (49, 1.51, 50)):
            self.assertEqual(self.values(fg_pct=fg, turnovers_avg=turnovers)["Offense Clutch"], expected)

    def test_defense_strict_above_average_and_deduplication(self):
        for steals, blocks, expected in ((1.01, .51, 99), (1, .51, 75), (1.01, .5, 75), (1, .5, 50)):
            self.assertEqual(self.values(steals_avg=steals, blocks_avg=blocks)["Defense Clutch"], expected)
        players = [{"proa_id": 1, "games": 5, "minutes_total_sec": 60, "steals_avg": 2, "blocks_avg": 1},
                   {"proa_id": 2, "games": 5, "minutes_total_sec": 60, "steals_avg": 0, "blocks_avg": 0},
                   {"proa_id": 3, "games": 0, "minutes_total_sec": 0, "steals_avg": 99, "blocks_avg": 99}]
        self.assertEqual(league_defense_averages(players + players[:1]), (1, .5))

    def test_shoot_or_pass_and_foul_scaling(self):
        for assists, expected in ((0, 99), (2.5, 83), (3.75, 74), (5, 66),
                                  (7.4, 51), (7.5, 50), (10, 50), (20, 50)):
            self.assertEqual(self.values(assists_avg=assists)["Shoot or Pass"], expected)
        self.assertEqual(self.values(fga_avg=0)["Shoot or Pass"], 75)
        for fouls, expected in ((0, 20), (.1, 60), (.2, 99), (.3, 99)):
            self.assertEqual(self.values(fouls_per_min=fouls)["Fouls per Min"], expected)
        with self.assertWarnsRegex(RuntimeWarning, "no foul totals"):
            self.assertEqual(self.values(fouls_per_min=None)["Fouls per Min"], 60)

    def test_shoot_or_pass_spans_full_range_monotonically(self):
        values = [self.values(assists_avg=step * .075)["Shoot or Pass"] for step in range(101)]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertEqual(set(values), set(range(50, 100)))

    def test_consistency_age_minutes_boundaries(self):
        for birth, sec, expected in ((2001, 12000, 75), (2002, 12000, 50), (2001, 11999, 50)):
            self.assertEqual(self.values(birth_year=birth, minutes_total_sec=sec)["Consistency"], expected)

    def test_no_stats_defaults(self):
        values = self.values(games=0, minutes_total_sec=0, fouls_per_min=None)
        self.assertEqual([values[key] for key in ("Offense Clutch", "Defense Clutch", "Shoot or Pass",
                                                  "Fouls per Min", "Consistency")], [50, 50, 75, 60, 50])

    def test_random_emotion_only_generated_range_and_final_speed(self):
        with patch("proa_attr_model.random.randint", side_effect=[0, 5]) as rng:
            for expected in (0, 5):
                values = build_ratings(self.context())
                self.assertEqual(values["Emotion"], expected)
                self.assertEqual(values["Fastbreak"], max(50, min(99, values["Speed"])))
            self.assertEqual(rng.call_count, 2)
            rng.assert_called_with(0, 5)
        self.assertEqual(hidden_ratings(self.context(), 25)["Fastbreak"], 50)
        self.assertEqual(hidden_ratings(self.context(), 100)["Fastbreak"], 99)

    def test_hidden_raw_validation_and_manual_only_values(self):
        self.assertEqual(field_value("Emotion", 15), 15)
        self.assertEqual(field_value("Standing Dunk", 0), 0)
        self.assertEqual(field_value("Consistency", 99), 99)
        for name in HIDDEN_ATTR_OFFSETS:
            low, high = HIDDEN_BOUNDS[name]
            for value in (low - 1, high + 1):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    field_value(name, value)
        for name in HIDDEN_TIERS:
            with self.assertRaises(ValueError):
                field_value(name, 60)

    def test_weighted_fouls_use_only_matching_recorded_minutes(self):
        def totals(games, seconds, attempts, fouls):
            return {**dict.fromkeys(COUNT_KEYS, 0), "g": games, "sec": seconds,
                    "p2a": attempts, "fls": fouls}
        seasons = {2026: totals(10, 6000, 100, 10), 2024: totals(10, 6000, 50, 20),
                   2023: totals(10, 60000, 50, None)}
        result = pool_seasons(seasons, 2026)
        self.assertAlmostEqual(result["fouls_per_min"], (10 + .8 * 20) * 60 / (6000 + .8 * 6000))
        self.assertAlmostEqual(result["fga_avg"], (100 + .8 * 50 + .6 * 50) / (10 + .8 * 10 + .6 * 10), places=5)
        self.assertIsNone(pool_seasons({2026: totals(10, 6000, 100, None)}, 2026)["fouls_per_min"])
        self.assertEqual(pool_seasons({2026: totals(10, 6000, 100, 0)}, 2026)["fouls_per_min"], 0)


class QualityBalanceTests(unittest.TestCase):
    def overall(self, ctx, ratings):
        return predict_overall(ctx.position, ratings, ctx.height_m, ctx.weight_kg,
                               player_extras(ratings, ratings))

    def test_young_low_minutes_retain_70_to_75_even_with_lucky_shooting(self):
        with patch("proa_attr_model.random.randint", return_value=0):
            for position, height, weight in (("PG", 1.9, 85), ("SG", 1.96, 90),
                                            ("SF", 2, 95), ("PF", 2.06, 105), ("C", 2.12, 110)):
                for minutes in (0, 4, 5):
                    with self.subTest(position=position, minutes=minutes):
                        ctx = PlayerContext(position=position, birth_year=2007, rating_year=2026,
                                            height_m=height, weight_kg=weight, games=20,
                                            minutes_total_sec=20 * minutes * 60, points_avg=2,
                                            fg_pct=100, fg3_pct=100, ft_pct=100, fga_avg=1,
                                            fouls_per_min=.1)
                        ratings = build_ratings(ctx)
                        self.assertTrue(69.5 <= self.overall(ctx, ratings) < 75.5)
                        self.assertTrue(all(50 <= ratings[name] <= 99 for name in ALL_ATTRS))

    def test_balance_changes_real_attributes_and_preserves_specialists_and_hidden_values(self):
        ctx = PlayerContext(position="PG", birth_year=1998, rating_year=2026,
                            games=30, minutes_total_sec=30 * 30 * 60, points_avg=22,
                            assists_avg=8, fg_pct=55, fg3_pct=45, ft_pct=90,
                            turnovers_avg=1.5, fga_avg=15, fouls_per_min=.1)
        ratings = {}
        for _, fn in PIPELINE:
            fn(ratings, ctx)
        with patch("proa_attr_model.random.randint", return_value=3):
            ratings.update(hidden_ratings(ctx, ratings["Speed"]))
        before = ratings.copy()
        apply_quality_balance(ratings, ctx)
        self.assertLess(self.overall(ctx, ratings), self.overall(ctx, before) - 3)
        self.assertLess(self.overall(ctx, ratings), 95)
        self.assertGreaterEqual(ratings["3pt Shot"], 90)
        self.assertNotEqual([ratings[n] for n in ALL_ATTRS], [before[n] for n in ALL_ATTRS])
        self.assertEqual({n: ratings[n] for n in HIDDEN_ATTR_OFFSETS if n != "Fastbreak"},
                         {n: before[n] for n in HIDDEN_ATTR_OFFSETS if n != "Fastbreak"})
        self.assertEqual(ratings["Fastbreak"], ratings["Speed"])
        values = []
        with patch("proa_attr_model.random.randint", return_value=3):
            for minutes in (6, 12, 20, 30):
                more_minutes = replace(ctx, minutes_total_sec=30 * minutes * 60)
                values.append(self.overall(more_minutes, build_ratings(more_minutes)))
        self.assertEqual(values, sorted(values))

    def test_missing_fitted_model_is_an_explicit_error(self):
        with patch("overall_model.predict_overall", return_value=None):
            with self.assertRaisesRegex(ValueError, "finite fitted Overall"):
                build_ratings(PlayerContext())


if __name__ == "__main__":
    unittest.main()
