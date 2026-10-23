# Season update workflow

Rebuilds the game's ProA roster for a new season. Everything below the *manual prerequisites* is chained by
`python scripts/update_season.py --season 2026_2027 --card "<Mcd001.ps2>"` (PCSX2 must be closed for `--card`).

## Pipeline (automated)

| # | Step | Script | Output |
|---|------|--------|--------|
| 1 | Scrape rosters, stats (pooled over 6 seasons), portraits; compute the 19 2K5 ratings | `scrape_proa_roster.py --season S` | `proa_scraped.xlsx`, `cache/proa_S/` |
| 2 | Crop portraits to 512x512 head+shoulders (replaces the old Photoshop batch; only missing ones are cropped, silhouettes skipped) | `crop_headshots.py` | `assets/PS_out/<proa_id>.png` |
| 3 | Build payload, pass 1 (writes the player list the face steps need) | `build_roster.py` | `data/roster_build/player_map.csv` |
| 4 | ArcFace embeddings of the new headshots | `face_embed.py` | `data/face_match/*.npz` |
| 5 | Match new players to NBA face models (cached players keep their pid, overrides win) | `face_match.py` | `data/face_match/proa_pid_map.csv`, `docs/_face_sheets/` |
| 6 | Build payload, pass 2 (pids applied), optionally write the card | `build_roster.py [--card]` | payload, `report.md` |
| 7 | Lineup headshots (pid-keyed) and team icons | `gen_replacements.py` | PCSX2 `replacements\` |
| 8 | Logo textures | `gen_logo_replacements.py` | PCSX2 `replacements\` |
| 9 | Recoloured light faces/necks and the light arm of the reserve (see `pcsx2_texture_mapping.md` item 7) | `gen_skin_replacements.py` | PCSX2 `replacements\` |

## Ratings website (GitHub Pages)

`.github/workflows/pages.yml` rebuilds and deploys a static site (`site_src/` frontend, built by `scripts/build_site.py`) on every
push to `main` that touches `proa_scraped.xlsx`, `data/proa_stats.json`, `data/overall_model.json`, `assets/PS_out/**`, `site_src/**`
or the build scripts. Nothing is committed back; the site is a deploy artifact.

- Ratings and bio come from `proa_scraped.xlsx` (edit there, commit, push). Overall is computed by `overall_model.py` (same model
  as the workbook's formula column). Stats come from `data/proa_stats.json`, which every scraper run writes
  (`scrape_proa_roster.py --stats-json-only` rebuilds it from the cache without touching the workbook). Team badges are linked live from
  `api.2basketballbundesliga.de/pics2/<season>/lp/<team id>`; portraits are resized from `assets/PS_out/`.
- Local preview: `python scripts/build_site.py --check`, then `python -m http.server -d site`.
- One-time setup: repository Settings -> Pages -> Source = GitHub Actions.

## Pipeline notes

`skin_brighten.py scan` / `embed` are one-off setup steps (rerun only after new face dumps).

Afterwards: review `docs/_face_sheets/` (edit `override_pid` in `proa_pid_map.csv` and re-run steps 6-7 for corrections), then
press F10 in PCSX2 (textures) and start a new game from the card (roster).

## Manual prerequisites when the set of clubs changes

1. `TEAM_MAP` in `scrape_proa_roster.py`: site team id -> (display name, sheet name). New ids are listed by
   `scrape_proa_roster.py --teams-only --season S` (marked "NOT IN TEAM_MAP").
2. `data/proa_teams.csv` (sheet, city, nickname, abbr; ASCII only). Row order = logo asset index (`nba2k_editor/assets/<38+row>.png`),
   so a new club takes the row of the club it replaces.
3. `data/team_slots.csv`: sheet -> NBA slot. The new club inherits the slot of the replaced club (textures are keyed by NBA slot);
   keep the default-matchup club (Falcons, slot 21) where it is.
4. `data/proa_arenas.csv`: arena name (`verified` = yes only when checked in game).
5. `python scripts/fetch_team_logos.py --sheets <new sheets>`: downloads the club logo. The site only has ~100 px logos
   (upscaled): replace `nba2k_editor/assets/<38+row>.png` with a high-res logo when available.

## Not automated

- New clubs' **jerseys** (and court/arena textures): the replaced club's slot still carries the old club's uniform and court.
  Needs texture dumps + the LOD pipeline, see `JerseyTextureWorkflow.md`.
- **Arena names** of new clubs (unverified guesses).
- **Name tweaks** (`data/overrides.csv`) for names that get truncated by the 2K string limits (see "Name adjustments" in `report.md`).
- **Face overrides** after reviewing the contact sheets; **hair** (bald vs. not) is not modelled.
- Players with only the site's **silhouette** portrait (no headshot, no face match): they take whatever pid is left over and
  have no lineup headshot. Fix by providing `assets/PS_out/<proa_id>.png` by hand and re-running.
- Closing PCSX2 before writing the card.

## 2026/27 notes

- Replaced Hagen, Muenster, Leverkusen with Essen (site id 444, ETB Miners), Heidelberg (488, MLP Academics) and Ulm (537,
  OrangeAcademy), taking slots 23 (Rockets), 28 (Warriors) and 13 (Kings). Falcons stay at slot 21.
- Rosters on the site are still being filled (11-15 players per team, 249 total). Ratings are derived from stats pooled over
  several seasons (see "Stats pooling"); new players without any games get defaults. Re-run the update as rosters grow; cached
  players keep their face pid.
- Players who left the league drop out of `proa_pid_map.csv`, freeing their pids.

## Stats pooling (`season_stats.py`)

Early in a season the current stats are a tiny sample, so the scraper pools the current season and the five before it
(`--history-seasons N`, `0` = current season only). Earlier seasons are fetched through the season selector of the player page
(one cached request per player and season, `cache/proa_S/player_<id>__<y>_<y+1>.html`; finished seasons are never re-fetched
unless `--refresh`).

- Season weight: current season 1, previous season 1, then 0.8 / 0.6 / 0.4 / 0.2 for the older ones. A season with fewer than
  10 games counts half on top (this applies to the current season too, so it takes over as it fills up).
- Counts (made/attempted, points, rebounds, ...) are weighted and summed, then divided by the weighted games: MPG, scoring,
  percentages etc. are volume-weighted averages. Because of the normalisation, players with fewer available seasons are not
  penalised; they just rest on less data (the attribute model only applies percentage modifiers from 5 real games on).
- All leagues the site lists for the player count (ProB seasons too); only regular-season (`HR`) rows are used.
- Team sheets are ordered by pooled minutes per game.
