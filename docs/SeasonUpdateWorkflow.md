# Season update workflow

Rebuilds the game's ProA roster for a new season. Everything below the *manual prerequisites* is chained by
`python scripts/update_season.py --season 2026_2027 --card "<Mcd001.ps2>"` (PCSX2 must be closed for `--card`).

## Pipeline (automated)

| # | Step | Script | Output |
|---|------|--------|--------|
| 1 | Scrape rosters, all selectable ProA regular-season histories and portraits; pool 6 seasons for the 19 2K5 ratings | `scrape_proa_roster.py --season S` | `proa_scraped.xlsx`, `data/proa_stats.json`, `cache/proa_S/` |
| 2 | Crop portraits to 512x512 head+shoulders (replaces the old Photoshop batch; only missing ones are cropped, silhouettes skipped) | `crop_headshots.py` | `assets/PS_out/<proa_id>.png` |
| 3 | Build payload, pass 1 (writes the player list the face steps need) | `build_roster.py` | `data/roster_build/player_map.csv` |
| 4 | ArcFace embeddings of the new headshots | `face_embed.py` | `data/face_match/*.npz` |
| 5 | Match new players to NBA face models (cached players keep their pid, overrides win) | `face_match.py` | `data/face_match/proa_pid_map.csv`, `docs/_face_sheets/` |
| 6 | Build payload, pass 2 (pids applied), optionally write the card | `build_roster.py [--card]` | payload, `report.md` |
| 7 | Lineup headshots (pid-keyed) and team icons | `gen_replacements.py` | PCSX2 `replacements\` |
| 8 | Logo textures | `gen_logo_replacements.py` | PCSX2 `replacements\` |
| 9 | Recoloured light faces/necks and the light arm of the reserve (see `pcsx2_texture_mapping.md` item 7) | `gen_skin_replacements.py` | PCSX2 `replacements\` |

With ISO options, a read-only lettering/court preflight runs before step 1 and ISO
publication runs after all replacements (the final script is `gen_logo_replacements.py`).
Neither stage runs without explicit ISO options.

### Season and career statistics

The scraper archives every selectable season through the requested season,
including older pages beyond the rating window. `--history-seasons` only controls
the rating window; its existing recency/low-games weights are unchanged.
Historical BBL/ProB appearances and playoff rows are excluded. League headings
are checked explicitly; unknown layouts or a server returning the wrong
selected season fail instead of publishing an apparently complete history.
Existing HTML caches are reused and reparsed; old parsed JSON cannot hide
newly collected personal fouls. An uncached request failure aborts publication
and can be retried without losing already fetched HTML.

In schema-v2 `data/proa_stats.json`, existing pooled site fields remain at the
same paths. Each player's `history` additionally contains:

- `seasons`: keyed by `YYYY_YYYY`, each with `totals` and `averages`;
- `career`: unweighted summed totals and ratios derived from those sums;
- `checked_seasons`: all successfully inspected options, including seasons
  with no ProA regular-season games (absent from `seasons`).

Totals contain PTS, OREB, DREB, REB, AST, STL, BLK, TO, FGM, FGA, 3PM, 3PA,
FTM, FTA, SEC, MIN, FLS, GP and GS. Averages contain PPG, ORPG, RPG, APG,
SPG, BPG, TOPG, MPG, FPG, FG%, 3P% and FT%. Percentages use 0..100;
MIN retains fractions and SEC is exact. Unavailable GS (and FLS, if a source
omits it) is JSON `null`, including the career result if any constituent is
unknown. Career ratios are not means of season averages.
If published REB differs from OREB+DREB, the archive preserves the published
figures and adds explicit `warnings`. By user choice, the game keeps the original
OREB/DREB components and derives their sum; the build report records the resulting
small REB/RPG difference instead of silently changing either component.

`build_roster.py` embeds these histories in the payload by default, preserves
untouched NBA/legend histories, checks fixed-pool capacity and reports missing
GS/FLS. `--stats PATH` selects another archive; `--no-stats` explicitly retains
the old inherited-statistics behavior. `--skip-scrape` therefore requires an
already-updated schema-v2 archive. The built payload is not automatically
copied to `data/roster.bin` or the card; use the existing `card_patch.py`
workflow with PCSX2 closed.

Labels use season start years: 2026/2027 displays 2026. Years Pro becomes the
contiguous history span, including gaps; zero-game gaps are hidden by the
game. The ISO stage automatically adds the matching season-label anchor.
Without ISO options, counts are embedded but labels still require a separately
patched ISO. See the [verified format and rounding limits](roster_payload_format.md#historical-player-statistics).

### Optional lettering ISO stage

Export and edit the [all-30-slot colour-control workspace](JerseyTextureWorkflow.md#simple-colour-controls-recommended)
first. The ISO source must be the verified untouched European original, not a prior
patched copy. Run the normal season update with both ISO flags:

```powershell
python scripts\update_season.py --season 2026_2027 --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "C:\Tools\isos\ESPN NBA 2K5 (Europe) - ProA.iso"
```

Add `--card "<Mcd001.ps2>"` to write the roster as usual (PCSX2 must be closed).
`--team-palettes PATH` overrides `texture_workspace/team_palettes` for both roster
and ISO stages (`--lettering-workspace` remains an alias). It also works without ISO
flags for roster-only runs. A missing/mismatched workspace, invalid palette, compressed edit
that does not fit, or existing output fails preflight before pipeline side effects.

New assignments require a new workspace and explicit palette migration.

Set `uniforms.<variant>.numbers/names.mode` in each team's `colours.json` to `monochrome` and choose `fill` for simple solid
lettering, or use `outlined` with three base colours. `palette` retains legacy
swatch editing. Export refreshes previews; the pipeline derives palettes in memory
from these controls without rewriting them.

The ISO stage patches shared number/name RGB, courts with `court.mode=recolour`,
and the player-card season-label anchor matching `--season`. It does **not** embed the roster
or PCSX2 replacement textures into the ISO. Number swatches update court and preview
sources together; names remain independent. Artist edits are never overwritten or
derived automatically from the independent jersey/UI settings. Existing output ISOs are refused.
The source remains untouched and an adjacent `.lettering.json` records verified
patches and source/output hashes. Boot the new ISO **fresh**; F10 reloads replacements,
not ISO lettering. Omit both ISO flags to preserve the original roster-only workflow.

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
2. `data/proa_teams.csv`: team names and home arena (see schema below).
   Row order = logo asset index (`nba2k_editor/assets/<38+row>.png`), so a new club takes the row of the club it replaces.
3. `data/team_slots.csv`: sheet -> NBA slot. The new club inherits the slot of the replaced club (textures are keyed by NBA slot);
   keep the default-matchup club (Falcons, slot 21) where it is.
   Edit the corresponding `texture_workspace/team_palettes/<slot>/colours.json`
   for jersey/UI, uniform lettering and approximate court colours.
4. `python scripts/fetch_team_logos.py --sheets <new sheets>`: downloads the club logo. The site only has ~100 px logos
   (upscaled): replace `nba2k_editor/assets/<38+row>.png` with a high-res logo when available.

### Combined team metadata

`data/proa_teams.csv` is the single source for the following fields; arena metadata is
no longer maintained in a separate CSV. Text written into the game should be ASCII.

| Columns | Consumer / meaning |
|---|---|
| `sheet,city,nickname,abbr` | Workbook identity and roster team names |
| `arena,verified` | Home arena name; `verified=yes` only when that name has been checked in-game |

Colour fields have moved to the `team` section of each
[team palette document](../texture_workspace/team_palettes/README.md).
`colorjersey1/2` feed the baseline cloth generator; `colorui1/2` feed roster RGB
triplets at `+0x62` / `+0x65` (UI/accessories and secondary backgrounds).
The UI colours were initially copied exactly from the jersey colours, but can now be
edited independently. Review light `colorui2` defaults (especially white) for text
contrast; no automatic darkening is applied. These are **not lettering colours**.
`build_roster.py --teams PATH --team-palettes PATH` reads metadata and palette documents, writes both UI triplets and
arena names, and reports UI colours in `team_map.csv`. The separate `--arenas` option
has been removed. Hex UI values must have exactly six digits, optionally prefixed by `#`.

Shared lettering and court settings live in the same documents but are independent
of jersey/UI values, and use the [opt-in ISO stage](#optional-lettering-iso-stage).

## Not automated

- New clubs' **jerseys** (and court/arena artwork): court colours can now be approximated via team palettes, but logos/layout still come from the original slot.
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
