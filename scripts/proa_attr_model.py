"""
proa_attr_model.py
==================
Stats-driven attribute model for ProA roster imports.

Pipeline overview
-----------------
Each step is a function with signature (ratings: Ratings, ctx: PlayerContext) -> None.
Steps mutate *ratings* in-place and are applied in the order listed in PIPELINE.
To disable a step, comment it out of PIPELINE. To add a new rule, add a function
and append it to PIPELINE — no other wiring is required.

Steps
-----
1. apply_position_baseline     – Set all 34 attrs from positional archetype
2. apply_impact_scaling        – Lift all attrs based on minutes & scoring load
3. apply_stat_modifiers        – Targeted deltas per individual stat (3P%, AST, REB …)
4. apply_physical_modifiers    – Height and weight → athleticism / strength adjustments
5. apply_age_modifiers         – Career arc: raw youth vs IQ of veterans
6. apply_positional_floors     – Guarantee no position is "unplayable"

Attribute names must match RATING_COLS in scrape_proa_roster.py exactly.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Ratings = dict[str, int]
ModifierFn = Callable[[Ratings, "PlayerContext"], None]

# All 34 attributes that are written to the Excel file.
# Keep in sync with RATING_COLS in scrape_proa_roster.py.
ALL_ATTRS: tuple[str, ...] = (
    "Close Shot",
    "Midrange Shot",
    "3pt Shot",
    "Free Throws",
    "Driving Layup",
    "Driving Dunk",
    "Standing Dunk",
    "Post Hook",
    "Post Fade",
    "Post Moves",
    "Draw Foul",
    "Shot IQ",
    "Offensive Consistency",
    "Ball Control",
    "Speed with Ball",
    "Pass Accuracy",
    "Passing IQ",
    "Passing Vision",
    "Interior Defense",
    "Perimeter Defense",
    "Steal",
    "Block",
    "Offensive Rebound",
    "Defensive Rebound",
    "Help Defense IQ",
    "Defensive Consistency",
    "Speed",
    "Agility",
    "Strength",
    "Vertical",
    "Stamina",
    "Hustle",
    "Intangibles",
    "Potential",
)

ATTR_MIN = 25
ATTR_MAX = 99

# ---------------------------------------------------------------------------
# PlayerContext
# ---------------------------------------------------------------------------

@dataclass
class PlayerContext:
    """
    All scraped data for a single player.
    Derived fields (mpg, age) are computed automatically from raw fields.
    Pass 0 / sensible defaults for any field not available from the scraper.
    """
    # --- Vitals ---
    position:   str   = "PG"    # One of: PG, SG, SF, PF, C
    birth_year: int   = 1995
    height_m:   float = 1.90    # metres
    weight_kg:  float = 85.0    # kilograms

    # --- Season stats ---
    games:            int   = 0
    minutes_total_sec: int  = 0   # total minutes played across all games (seconds)
    points_avg:       float = 0.0
    assists_avg:      float = 0.0
    rebounds_avg:     float = 0.0
    rebounds_off_avg: float = 0.0
    rebounds_def_avg: float = 0.0
    steals_avg:       float = 0.0
    blocks_avg:       float = 0.0
    turnovers_avg:    float = 0.0
    fg_pct:           float = 0.0  # 0–100 scale as returned by scraper
    fg3_pct:          float = 0.0  # 0–100 scale
    ft_pct:           float = 0.0  # 0–100 scale

    # --- Derived (read-only properties) ---

    @property
    def mpg(self) -> float:
        """Average minutes per game. Minutes_total_sec is in seconds."""
        if self.games <= 0:
            return 0.0
        return (self.minutes_total_sec / 60) / self.games

    @property
    def age(self) -> int:
        """Age as of the current season (prorated from birth year only)."""
        return datetime.date.today().year - self.birth_year

    @property
    def height_cm(self) -> float:
        return self.height_m * 100.0

    @property
    def ast_to_ratio(self) -> float:
        """Assist-to-turnover ratio. Returns 0 when turnovers == 0."""
        if self.turnovers_avg <= 0:
            return 0.0
        return self.assists_avg / self.turnovers_avg


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------

def _add(ratings: Ratings, attr: str, delta: int) -> None:
    """Add *delta* to an attribute, clamping the result to [ATTR_MIN, ATTR_MAX]."""
    if attr in ratings:
        ratings[attr] = max(ATTR_MIN, min(ATTR_MAX, ratings[attr] + delta))


def _floor(ratings: Ratings, attr: str, minimum: int) -> None:
    """Raise an attribute to at least *minimum* (never lower it)."""
    if attr in ratings:
        ratings[attr] = max(ratings[attr], minimum)

def _ceil(ratings: Ratings, attr: str, maximum: int) -> None:
    """Raise an attribute to at most *maximum* (never increase it beyond maximum)."""
    if attr in ratings:
        ratings[attr] = min(ratings[attr], maximum)

def _add_many(ratings: Ratings, attrs: list[str], delta: int) -> None:
    for attr in attrs:
        _add(ratings, attr, delta)


def _floor_many(ratings: Ratings, attrs: list[str], minimum: int) -> None:
    for attr in attrs:
        _floor(ratings, attr, minimum)


def _blank_ratings() -> Ratings:
    return {attr: 50 for attr in ALL_ATTRS}


# ---------------------------------------------------------------------------
# Step 1 – Positional baseline
# ---------------------------------------------------------------------------
# Every attribute gets an initial value that reflects the positional archetype.
# These are the "average ProA player" values for each position.
# Adjust these dicts to shift the entire floor for a position.

## note: 50 is the lower limit in NBA 2k5!

_POSITION_BASELINES: dict[str, Ratings] = {
    "PG": {
        "Close Shot":            70,
        "Midrange Shot":         75,
        "3pt Shot":              70,
        "Free Throws":           80,
        "Driving Layup":         82,
        "Driving Dunk":          62,
        "Standing Dunk":         50,
        "Post Hook":             50,
        "Post Fade":             50,
        "Post Moves":            50,
        "Draw Foul":             75,
        "Shot IQ":               70,
        "Offensive Consistency": 70,
        "Ball Control":          85,
        "Speed with Ball":       80,
        "Pass Accuracy":         80,
        "Passing IQ":            85,
        "Passing Vision":        82,
        "Interior Defense":      50,
        "Perimeter Defense":     78,
        "Steal":                 82,
        "Block":                 50,
        "Offensive Rebound":     50,
        "Defensive Rebound":     50,
        "Help Defense IQ":       65,
        "Defensive Consistency": 65,
        "Speed":                 80,
        "Agility":               80,
        "Strength":              60,
        "Vertical":              67,
        "Stamina":               77,
        "Hustle":                72,
        "Intangibles":           74,
        "Potential":             65,
    },
    "SG": {
        "Close Shot":            72,
        "Midrange Shot":         75,
        "3pt Shot":              77,
        "Free Throws":           77,
        "Driving Layup":         76,
        "Driving Dunk":          67,
        "Standing Dunk":         50,
        "Post Hook":             50,
        "Post Fade":             55,
        "Post Moves":            50,
        "Draw Foul":             67,
        "Shot IQ":               70,
        "Offensive Consistency": 72,
        "Ball Control":          73,
        "Speed with Ball":       74,
        "Pass Accuracy":         65,
        "Passing IQ":            68,
        "Passing Vision":        67,
        "Interior Defense":      55,
        "Perimeter Defense":     72,
        "Steal":                 72,
        "Block":                 55,
        "Offensive Rebound":     50,
        "Defensive Rebound":     55,
        "Help Defense IQ":       67,
        "Defensive Consistency": 68,
        "Speed":                 78,
        "Agility":               78,
        "Strength":              60,
        "Vertical":              72,
        "Stamina":               77,
        "Hustle":                71,
        "Intangibles":           70,
        "Potential":             65,
    },
    "SF": {
        "Close Shot":            73,
        "Midrange Shot":         73,
        "3pt Shot":              66,
        "Free Throws":           73,
        "Driving Layup":         77,
        "Driving Dunk":          76,
        "Standing Dunk":         53,
        "Post Hook":             50,
        "Post Fade":             60,
        "Post Moves":            55,
        "Draw Foul":             67,
        "Shot IQ":               72,
        "Offensive Consistency": 70,
        "Ball Control":          69,
        "Speed with Ball":       68,
        "Pass Accuracy":         65,
        "Passing IQ":            65,
        "Passing Vision":        61,
        "Interior Defense":      65,
        "Perimeter Defense":     69,
        "Steal":                 67,
        "Block":                 60,
        "Offensive Rebound":     62,
        "Defensive Rebound":     62,
        "Help Defense IQ":       67,
        "Defensive Consistency": 70,
        "Speed":                 75,
        "Agility":               71,
        "Strength":              71,
        "Vertical":              72,
        "Stamina":               76,
        "Hustle":                72,
        "Intangibles":           72,
        "Potential":             65,
    },
    "PF": {
        "Close Shot":            75,
        "Midrange Shot":         67,
        "3pt Shot":              63,
        "Free Throws":           65,
        "Driving Layup":         72,
        "Driving Dunk":          77,
        "Standing Dunk":         65,
        "Post Hook":             73,
        "Post Fade":             69,
        "Post Moves":            72,
        "Draw Foul":             67,
        "Shot IQ":               66,
        "Offensive Consistency": 66,
        "Ball Control":          57,
        "Speed with Ball":       60,
        "Pass Accuracy":         62,
        "Passing IQ":            59,
        "Passing Vision":        58,
        "Interior Defense":      74,
        "Perimeter Defense":     62,
        "Steal":                 60,
        "Block":                 70,
        "Offensive Rebound":     78,
        "Defensive Rebound":     76,
        "Help Defense IQ":       66,
        "Defensive Consistency": 67,
        "Speed":                 64,
        "Agility":               61,
        "Strength":              78,
        "Vertical":              68,
        "Stamina":               77,
        "Hustle":                77,
        "Intangibles":           69,
        "Potential":             65,
    },
    "C": {
        "Close Shot":            79,
        "Midrange Shot":         62,
        "3pt Shot":              50,
        "Free Throws":           62,
        "Driving Layup":         70,
        "Driving Dunk":          74,
        "Standing Dunk":         79,
        "Post Hook":             77,
        "Post Fade":             67,
        "Post Moves":            77,
        "Draw Foul":             70,
        "Shot IQ":               67,
        "Offensive Consistency": 62,
        "Ball Control":          50,
        "Speed with Ball":       50,
        "Pass Accuracy":         55,
        "Passing IQ":            52,
        "Passing Vision":        52,
        "Interior Defense":      79,
        "Perimeter Defense":     50,
        "Steal":                 55,
        "Block":                 79,
        "Offensive Rebound":     80,
        "Defensive Rebound":     80,
        "Help Defense IQ":       67,
        "Defensive Consistency": 69,
        "Speed":                 55,
        "Agility":               50,
        "Strength":              85,
        "Vertical":              67,
        "Stamina":               79,
        "Hustle":                78,
        "Intangibles":           69,
        "Potential":             65,
    },
}

def apply_position_baseline(ratings: Ratings, ctx: PlayerContext) -> None:
    """
    Step 1: Overwrite all attributes with the positional archetype values.
    This always runs first and establishes everything — subsequent steps
    layer deltas on top of these values.
    Falls back to SG baseline for any unrecognised position string.
    """
    baseline = _POSITION_BASELINES.get(ctx.position, _POSITION_BASELINES["SG"])
    ratings.update(baseline)


# ---------------------------------------------------------------------------
# Step 2 – Impact scaling (minutes + scoring)
# ---------------------------------------------------------------------------
# A player with high minutes is a foundational piece of his team.
# We apply a uniform "overall quality" lift based on MPG, plus a targeted
# scoring bonus for high-point-output players.
#
# MPG reference for ProA (2nd Bundesliga):
#   Elite starter  ~30+ min  → tier ~0.9  → +14 across the board
#   Solid starter  ~22–28    → tier ~0.7  → +10
#   Rotation       ~14–20    → tier ~0.5  → +7
#   Bench          ~6–12     → tier ~0.3  → +4
#
# Point-scoring bonus: only applied to offensive attributes, so a dominant
# scorer stands out offensively without becoming a superhuman defender.

_SCORING_ATTRS: list[str] = [
    "Close Shot", "Midrange Shot", "3pt Shot", "Driving Layup",
    "Driving Dunk", "Draw Foul", "Shot IQ", "Offensive Consistency",
]

_MPG_MAX = 32.0     # cap for normalisation – tune if ProA minutes climb higher

def apply_impact_scaling(ratings: Ratings, ctx: PlayerContext) -> None:
    """
    Step 2: Apply a global quality lift based on average minutes per game,
    plus a targeted scoring bonus for high-usage offensive players.
    """
    mpg_tier = min(ctx.mpg, _MPG_MAX) / _MPG_MAX  # 0.0 – 1.0

    # Universal lift: up to +15 for elite 30-min starters
    impact_bonus = round(mpg_tier * 15)
    _add_many(ratings, list(ALL_ATTRS), impact_bonus)

    # Scoring bonus layered on top of the universal lift
    pts = ctx.points_avg
    if pts > 20:
        _add_many(ratings, _SCORING_ATTRS, 8)
    elif pts > 15:
        _add_many(ratings, _SCORING_ATTRS, 5)
    elif pts > 10:
        _add_many(ratings, _SCORING_ATTRS, 2)


# ---------------------------------------------------------------------------
# Step 3 – Stat modifiers (per-stat targeted deltas)
# ---------------------------------------------------------------------------
# Each rule maps a scraper stat threshold to the attributes it most directly
# reflects.  Rules are intentionally split by threshold level so the magnitude
# of the bonus is proportional to the stat, not binary.
#
# Note on fg3_pct: we guard with games >= 5 to ignore single-game outliers
# (e.g. a player who hit one three in game 1 and never played again → 100%).

_MIN_GAMES_FOR_PCT_STATS = 5

def apply_stat_modifiers(ratings: Ratings, ctx: PlayerContext) -> None:
    """
    Step 3: Apply targeted attribute adjustments based on individual season stats.
    Each block is self-contained; add new stat → attribute mappings here.
    """
    g = ctx.games

    # ---- Three-point shooting ----
    if g >= _MIN_GAMES_FOR_PCT_STATS:
        if ctx.fg3_pct > 40:
            _add(ratings, "3pt Shot", 12)
            _floor(ratings, "3pt Shot", 80)
        elif ctx.fg3_pct > 35:
            _add(ratings, "3pt Shot", 7)
            _floor(ratings, "3pt Shot", 70)
        elif ctx.fg3_pct > 28:
            _floor(ratings, "3pt Shot", 60)
            _ceil(ratings, "3pt Shot", 67)
        elif ctx.fg3_pct < 22 and ctx.fg3_pct > 0:
            _add(ratings, "3pt Shot", -5)
            _ceil(ratings, "3pt Shot", 60)

    # ---- Playmaking / assists ----
    _PLAYMAKING: list[str] = ["Pass Accuracy", "Passing IQ", "Passing Vision", "Ball Control"]
    if ctx.assists_avg > 7:
        _add_many(ratings, _PLAYMAKING, 12)
        _floor(ratings, "Pass Accuracy", 70)
        _floor(ratings, "Passing IQ", 70)
        _floor(ratings, "Passing Vision", 70)
    elif ctx.assists_avg > 5:
        _add_many(ratings, _PLAYMAKING, 7)
    elif ctx.assists_avg > 3:
        _add_many(ratings, _PLAYMAKING, 3)

    # ---- Offensive rebounding ----
    _OREB: list[str] = ["Offensive Rebound", "Hustle"]
    if ctx.rebounds_off_avg > 3:
        _add_many(ratings, _OREB, 10)
        _floor(ratings, "Offensive Rebound", 70)
    elif ctx.rebounds_off_avg > 2:
        _add_many(ratings, _OREB, 6)
    elif ctx.rebounds_off_avg > 1:
        _add_many(ratings, _OREB, 3)

    # ---- Defensive rebounding ----
    _DREB: list[str] = ["Defensive Rebound", "Help Defense IQ"]
    if ctx.rebounds_def_avg > 7:
        _add_many(ratings, _DREB, 10)
        _floor(ratings, "Defensive Rebound", 75)
    elif ctx.rebounds_def_avg > 4:
        _add_many(ratings, _DREB, 5)
        _floor(ratings, "Defensive Rebound", 70)
    elif ctx.rebounds_def_avg > 2:
        _add_many(ratings, _DREB, 2)
        _ceil(ratings, "Defensive Rebound", 69)

    # ---- Steals ----
    _STEALS: list[str] = ["Steal", "Perimeter Defense"]
    if ctx.steals_avg > 2:
        _add_many(ratings, _STEALS, 12)
        _floor(ratings, "Steal", 80)
    elif ctx.steals_avg > 1.5:
        _add_many(ratings, _STEALS, 7)
        _floor(ratings, "Steal", 76)
    elif ctx.steals_avg > 1:
        _add_many(ratings, _STEALS, 3)
        _floor(ratings, "Steal", 71)

    # ---- Blocks ----
    _BLOCKS: list[str] = ["Block", "Interior Defense"]
    if ctx.blocks_avg > 2:
        _add_many(ratings, _BLOCKS, 12)
        _floor(ratings, "Block", 80)
    elif ctx.blocks_avg > 1.5:
        _add_many(ratings, _BLOCKS, 7)  
        _floor(ratings, "Block", 76)
    elif ctx.blocks_avg > 1:
        _add_many(ratings, _BLOCKS, 4)
        _floor(ratings, "Block", 71)

    # ---- Field goal percentage (general interior/finishing ability) ----
    if g >= _MIN_GAMES_FOR_PCT_STATS:
        _FINISHING: list[str] = ["Close Shot", "Driving Layup", "Post Hook"]
        if ctx.fg_pct > 60:
            _add_many(ratings, _FINISHING, 10)
        elif ctx.fg_pct > 55:
            _add_many(ratings, _FINISHING, 6)
        elif ctx.fg_pct > 50:
            _add_many(ratings, _FINISHING, 3)

    # ---- Free throw percentage ----
    if g >= _MIN_GAMES_FOR_PCT_STATS:
        _FT: list[str] = ["Free Throws", "Draw Foul"]
        if ctx.ft_pct > 85:
            _add_many(ratings, _FT, 8)
            _floor(ratings, "Free Throws", 85)
        elif ctx.ft_pct > 75:
            _add_many(ratings, _FT, 5)
            _floor(ratings, "Free Throws", 75)
        elif ctx.ft_pct > 65:
            _add_many(ratings, _FT, 2)
            _floor(ratings, "Free Throws", 65)
            _ceil(ratings, "Free Throws", 69)
        if ctx.ft_pct < 65:
            _ceil(ratings, "Free Throws", 60)

    # ---- Assist-to-turnover ratio (ball security + decision-making) ----
    _DECISIONS: list[str] = ["Ball Control", "Speed with Ball", "Passing IQ"]
    if ctx.ast_to_ratio > 3.0:
        _add_many(ratings, _DECISIONS, 8)
    elif ctx.ast_to_ratio > 2.0:
        _add_many(ratings, _DECISIONS, 4)

    # ---- High turnover rate (penalises inconsistent ball handlers) ----
    if ctx.turnovers_avg > 3.0:
        _add_many(ratings, ["Ball Control", "Offensive Consistency"], -5)
    elif ctx.turnovers_avg > 2.0:
        _add_many(ratings, ["Ball Control", "Offensive Consistency"], -2)


# ---------------------------------------------------------------------------
# Step 4 – Physical modifiers (height + weight)
# ---------------------------------------------------------------------------
# These encode the physical archetypes the game already uses internally.
# Tall heavy players become post anchors; small light guards become quick
# perimeter threats.  Adjustments are relative deltas, not overrides.

def apply_physical_modifiers(ratings: Ratings, ctx: PlayerContext) -> None:
    """
    Step 4: Adjust athleticism and physical attributes based on height and weight.
    Works in two independent sub-passes (height then weight) so both contribute.
    """
    h = ctx.height_cm
    w = ctx.weight_kg

    # ---- Height ----
    if h >= 215:
        _add_many(ratings, ["Block", "Offensive Rebound", "Defensive Rebound"], 8)
        _add_many(ratings, ["Standing Dunk", "Interior Defense"], 6)
        _add_many(ratings, ["Strength"], 5)
        _add_many(ratings, ["Speed", "Agility", "Speed with Ball"], -6)
        _floor(ratings, "Block", 85)
        _floor(ratings, "Offensive Rebound", 75)
        _floor(ratings, "Defensive Rebound", 80)
        _floor(ratings, "Standing Dunk", 80)
        _ceil(ratings, "Speed", 67)
    elif h >= 210:
        _add_many(ratings, ["Block", "Offensive Rebound", "Defensive Rebound"], 5)
        _add_many(ratings, ["Standing Dunk", "Interior Defense"], 4)
        _add_many(ratings, ["Strength"], 3)
        _add_many(ratings, ["Speed", "Agility"], -4)
        _floor(ratings, "Block", 80)
        _floor(ratings, "Offensive Rebound", 70)
        _floor(ratings, "Defensive Rebound", 75)
        _floor(ratings, "Standing Dunk", 75)
        _ceil(ratings, "Speed", 72)
    elif h >= 205:
        _add_many(ratings, ["Block", "Defensive Rebound"], 3)
        _add_many(ratings, ["Strength", "Interior Defense"], 2)
        _floor(ratings, "Block", 77)
        _floor(ratings, "Offensive Rebound", 68)
        _floor(ratings, "Defensive Rebound", 73)
        _floor(ratings, "Standing Dunk", 70)
        _ceil(ratings, "Speed", 77)    
    elif h >= 200:
        pass  # neutral range — no adjustment
    elif h >= 193:
        _add_many(ratings, ["Speed", "Agility", "Ball Control"], 2)
        _add_many(ratings, ["Speed with Ball"], 2)
    elif h >= 185:
        _add_many(ratings, ["Speed", "Agility", "Speed with Ball"], 4)
        _add_many(ratings, ["Ball Control", "Driving Layup"], 3)
        _add_many(ratings, ["Standing Dunk", "Block", "Interior Defense"], -4)
        _add_many(ratings, ["Strength"], -2)
        _ceil(ratings, "Offensive Rebound", 73)
        _ceil(ratings, "Defensive Rebound", 78)
        _ceil(ratings, "Standing Dunk", 70)
    else:  # < 185 – true small
        _add_many(ratings, ["Speed", "Agility", "Speed with Ball"], 6)
        _add_many(ratings, ["Ball Control", "Driving Layup", "Steal"], 4)
        _add_many(ratings, ["Standing Dunk", "Block", "Interior Defense"], -6)
        _add_many(ratings, ["Strength"], -4)
        _ceil(ratings, "Offensive Rebound", 70)
        _ceil(ratings, "Defensive Rebound", 75)
        _ceil(ratings, "Standing Dunk", 60)

    # ---- Weight ----
    if w >= 115:
        _add_many(ratings, ["Strength", "Interior Defense"], 8)
        _floor(ratings, "Offensive Rebound", 70)
        _floor(ratings, "Defensive Rebound", 80)
        _floor(ratings, "Interior Defense", 80)
        _floor(ratings, "Strength", 90)
        _add_many(ratings, ["Speed", "Agility"], -6)
        _ceil(ratings, "Speed", 80)
        _ceil(ratings, "Agility", 80)
    elif w >= 105:
        _add_many(ratings, ["Strength", "Interior Defense"], 5)
        _add_many(ratings, ["Speed", "Agility"], -3)
        _floor(ratings, "Offensive Rebound", 65)
        _floor(ratings, "Defensive Rebound", 70)
        _floor(ratings, "Strength", 80)
    elif w >= 95:
        _add_many(ratings, ["Strength", "Interior Defense"], 2)
    elif w >= 85:
        pass  # neutral range
    elif w >= 75:
        _add_many(ratings, ["Agility", "Speed"], 2)
    else:  # < 75 – very light
        _add_many(ratings, ["Agility", "Speed"], 4)
        _add_many(ratings, ["Strength"], -4)


# ---------------------------------------------------------------------------
# Step 5 – Age modifiers (career arc)
# ---------------------------------------------------------------------------
# Young players: more raw athleticism, more inconsistency.
# Prime-age players: no adjustment (the baseline is calibrated for this range).
# Veterans: less athleticism, but better feel for the game and mental attributes.

def apply_age_modifiers(ratings: Ratings, ctx: PlayerContext) -> None:
    """
    Step 5: Encode the basketball career arc.
      < 22  – raw athlete, high ceiling, poor decision-making
      22–29 – prime range (no adjustment)
      30–34 – slight decline in burst, gains in IQ and consistency
      35+   – clear athletic decline, hard-earned wisdom attributes
    """
    age = ctx.age

    _MENTAL: list[str] = [
        "Shot IQ", "Offensive Consistency", "Defensive Consistency",
        "Intangibles", "Help Defense IQ", "Passing IQ",
    ]
    _ATHLETIC: list[str] = ["Speed", "Agility", "Vertical", "Stamina"]

    if age < 22:
        _add_many(ratings, ["Vertical", "Speed", "Agility"], 4)
        _add_many(ratings, _MENTAL, -6)
        _add(ratings, "Potential", 12)

    elif age <= 29:
        pass  # prime – no adjustment

    elif age <= 34:
        _add_many(ratings, _ATHLETIC, -3)
        _add_many(ratings, _MENTAL, 5)
        _add(ratings, "Potential", -8)

    else:  # 35+
        _add_many(ratings, _ATHLETIC, -7)
        _add(ratings, "Stamina", -4)  # extra stamina hit beyond _ATHLETIC
        _add_many(ratings, _MENTAL, 8)
        _add(ratings, "Potential", -15)
        _ceil(ratings, "Speed", 75)


# ---------------------------------------------------------------------------
# Step 6 – Positional floors (guarantee playability)
# ---------------------------------------------------------------------------
# Applied last so earlier steps cannot accidentally push an essential attribute
# below a usable level.  _floor() only raises, never lowers.

_UNIVERSAL_FLOOR = 50      # absolute minimum for any attribute
_UNIVERSAL_SPECIAL: dict[str, int] = {
    "Free Throws": 50,
    "Hustle":      55,
    "Stamina":     65,
}

_POSITIONAL_FLOORS: dict[str, dict[str, int]] = {
    "PG": {
        "Ball Control":   68,
        "Speed with Ball": 65,
        "Pass Accuracy":  68,
        "Speed":          67,
        "Agility":        67,
    },
    "SG": {
        "3pt Shot":       60,
        "Midrange Shot":  60,
        "Ball Control":   60,
        "Speed":          63,
    },
    "SF": {
        "Perimeter Defense": 64,
        "Speed":             60,
        "Midrange Shot":     65,
    },
    "PF": {
        "Strength":          67,
        "Interior Defense":  64,
        "Offensive Rebound": 65,
        "Defensive Rebound": 63,
    },
    "C": {
        "Strength":          68,
        "Interior Defense":  65,
        "Offensive Rebound": 65,
        "Defensive Rebound": 68,
        "Standing Dunk":     66,
        "Block":             66,
    },
}

def apply_positional_floors(ratings: Ratings, ctx: PlayerContext) -> None:
    """
    Step 6: Guarantee no player is "unplayable" at their position.
    Raises attributes that fell below positional minimums; never lowers anything.
    """
    # Universal absolute floor for every attribute
    for attr in ALL_ATTRS:
        _floor(ratings, attr, _UNIVERSAL_FLOOR)

    # Universal special floors
    for attr, minimum in _UNIVERSAL_SPECIAL.items():
        _floor(ratings, attr, minimum)

    # Position-specific floors
    pos_floors = _POSITIONAL_FLOORS.get(ctx.position, {})
    for attr, minimum in pos_floors.items():
        _floor(ratings, attr, minimum)


# ---------------------------------------------------------------------------
# Pipeline declaration
# ---------------------------------------------------------------------------
# Ordered list of (label, function) pairs.  The label is used for debug
# logging only — it is never parsed or evaluated by build_ratings().
# To disable a step: comment out its tuple.
# To add a new step: append a new (label, fn) tuple and write the function.

PIPELINE: list[tuple[str, ModifierFn]] = [
    ("1_position_baseline",   apply_position_baseline),
    ("2_impact_scaling",      apply_impact_scaling),
    ("3_stat_modifiers",      apply_stat_modifiers),
    ("4_physical_modifiers",  apply_physical_modifiers),
    ("5_age_modifiers",       apply_age_modifiers),
    ("6_positional_floors",   apply_positional_floors),
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_ratings(ctx: PlayerContext, *, debug: bool = False) -> Ratings:
    """
    Run the full attribute pipeline for one player and return a Ratings dict.

    Args:
        ctx:   Scraped player data wrapped in a PlayerContext.
        debug: If True, prints the ratings after each pipeline step.

    Returns:
        A dict mapping every attribute name in ALL_ATTRS to an int in [25, 99].
    """
    ratings = _blank_ratings()

    for label, fn in PIPELINE:
        fn(ratings, ctx)
        if debug:
            _print_debug_snapshot(label, ratings)

    return ratings


def _print_debug_snapshot(label: str, ratings: Ratings) -> None:
    print(f"\n--- After {label} ---")
    for attr in ALL_ATTRS:
        print(f"  {attr:<28} {ratings[attr]:>3}")


# ---------------------------------------------------------------------------
# Quick self-test / demo (python scripts/proa_attr_model.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    demo_players = [
        ("Elite PG starter",
         PlayerContext(position="PG", birth_year=1998, height_m=1.88, weight_kg=80,
                       games=30, minutes_total_sec=30*28*60,
                       points_avg=18.0, assists_avg=8.0, rebounds_avg=3.5,
                       steals_avg=1.8, fg3_pct=38.0, ft_pct=82.0, turnovers_avg=1.8)),
        ("Bench C (young)",
         PlayerContext(position="C", birth_year=2003, height_m=2.12, weight_kg=108,
                       games=20, minutes_total_sec=20*12*60,
                       points_avg=5.0, blocks_avg=1.6, rebounds_off_avg=2.2,
                       rebounds_def_avg=4.0, fg_pct=55.0)),
        ("Veteran SF",
         PlayerContext(position="SF", birth_year=1988, height_m=1.98, weight_kg=97,
                       games=25, minutes_total_sec=25*22*60,
                       points_avg=11.0, assists_avg=2.5, fg3_pct=36.0,
                       steals_avg=1.1, ft_pct=78.0)),
    ]

    for name, ctx in demo_players:
        r = build_ratings(ctx)
        ovr = round(sum(r.values()) / len(r))
        low = min(r.values())
        high = max(r.values())
        print(f"\n{'='*60}")
        print(f"  {name}  (pos={ctx.position}, age={ctx.age}, mpg={ctx.mpg:.1f})")
        print(f"  avg OVR={ovr}  min={low}  max={high}")
        for attr in ALL_ATTRS:
            print(f"    {attr:<28} {r[attr]:>3}")
