# Season update workflow

Rebuilds the game's ProA roster for a new season and embeds it as the disc's default roster.
The [ISO-first command](#iso-first-roster-deployment) chains everything below the *manual prerequisites*.
An optional `--card PATH` exports the same final payload (PCSX2 must be closed for card writes).

## Pipeline (automated)

| # | Step | Script | Output |
|---|------|--------|--------|
| 1 | Scrape rosters, all selectable ProA regular-season histories and portraits; pool 6 seasons for the 19 2K5 ratings | `scrape_proa_roster.py --season S` | `proa_scraped.xlsx`, `data/proa_stats.json`, `cache/proa_S/` |
| 2 | Crop portraits to 512x512 head+shoulders (replaces the old Photoshop batch; only missing ones are cropped, silhouettes skipped) | `crop_headshots.py` | `assets/PS_out/<proa_id>.png` |
| 3 | Provisional payload/player list from the pristine disc; defer manual complexion leg changes | `build_roster.py --iso-source PRISTINE --prepare-faces` | `data/roster_build/player_map.csv` |
| 4 | ArcFace embeddings of the new headshots | `face_embed.py` | `data/face_match/*.npz` |
| 5 | Match new players to NBA face models and prepare requested model-local skin recipes (cached players keep their pid, overrides win) | `face_match.py [--iso-source PRISTINE]` | `data/face_match/proa_pid_map.csv`, `skin_tone_plan.json`, `docs/_face_sheets/` |
| 6 | Build payload, pass 2 (pids and validated manual leg bytes applied) | `build_roster.py --iso-source PRISTINE` | payload, `report.md` |
| 7 | Lineup headshots (pid-keyed) and team icons | `gen_replacements.py` | PCSX2 `replacements\` |
| 8 | Logo textures | `gen_logo_replacements.py` | PCSX2 `replacements\` |
| 9 | Recoloured light faces/necks and the light arm of the reserve (see `pcsx2_texture_mapping.md` item 7) | `gen_skin_replacements.py` | PCSX2 `replacements\` |
| 10 | Single combined default-roster/lettering/court/stats-year/skin ISO publication | `season_iso.py build --roster ... --skin-plan ...` | new ISO and `.season.json` manifest |
| 11 | Optional export of the exact step-6 payload, only after requested ISO work succeeds | `card_patch.py --bin ... --card ...` | backed-up, verified memory card |

A read-only roster/lettering/court preflight runs before step 1; publication runs
after all replacements (the final generator is `gen_logo_replacements.py`).
The pristine ISO supplies the roster baseline in every mode; no memory-card extraction is needed.
`--card-only` and `--build-only` skip visual ISO preflight/publication but still verify the disc roster.
Nonzero `Skin Tone` requires an ISO output; alternative modes stop before building a roster.

### Persistent player edits and exclusions

`proa_scraped.xlsx` is generated output, including accessory columns, `College`
(populated from the site's `Nat` column as English country names, e.g.
`Germany / United States`), and `Shooting Hand` (0 = left, 1 = right;
default 1). Do not rely on manual workbook edits surviving a scrape.
`Skin Tone` defaults to 0 (automatic).

Edit **only `data/overrides.csv`** for permanent player corrections. Its header
contains informational `Team`, the unique lookup key `ProA ID`, and every player
workbook column except the computed `Overall`. `Team` is ignored for matching
and never transfers a player; overrides follow IDs across clubs/seasons.
The existing accessory settings were migrated once; automation never creates,
appends to, or rewrites this file.

- Blank/whitespace cell: no override. **`0` is an explicit value**, including
  left-handedness, jersey number zero and removal of accessories.
- `<CLEAR>` explicitly empties `College`. For numeric fields use 0 where allowed;
  names, positions and other required values cannot be cleared.
- `College` supplies the in-game player-card **FROM** label. Replace the country
  with an actual college in the override CSV whenever desired; manual values are
  used literally, never translated or shortened. Nationality expansion applies
  only to generated defaults; cached NAT codes remain unchanged. Unknown codes
  fail explicitly instead of silently publishing an untranslated default.
- College values allow printable BMP text, without control characters or embedded
  NULs. Non-ASCII glyph rendering still depends on the game's font.
- The builder shares identical College labels across players, reuses all 457
  college rows and keeps the payload size unchanged. Original NBA/legend/template
  college labels are intentionally **not protected**. Extra unused college names
  are cleared to a shared empty string only if string space is needed.
  The build report lists label/row usage, remaining string bytes/largest block
  and extra bytes still reclaimable from unused college names.
  Too many distinct labels, insufficient bytes or fragmentation fail before
  publishing a new payload or writing a card; shorten/share values to fit.
- Generated names are transliterated (ae/oe/ue/ss, accents removed), whitespace
  normalized and shortened to 12 characters. Manual preferred names apply
  afterwards and must already fit those constraints.
- Ratings are integers 25..99; accessory values are integers 0..255, using the
  existing preset/raw-index meanings. Height is metres; weight is kg.
- Duplicate IDs, unknown columns, invalid dates/numbers/names and invalid
  shooting-hand values fail validation before saving. Overrides for players
  absent this season are reported and retained.
- `Years Pro` is derived from the season-history span. With stats enabled,
  conflicting overrides are rejected by the builder rather than mislabelling
  seasons. It is freely editable only for `build_roster.py --no-stats`.
- `Skin Tone`: **0 or blank = automatic; 1..6 = lightest to darkest**.
  Set it in `overrides.csv`, not in the generated face map. Use an explicit 0
  to reset an already-applied manual value; merely emptying its CSV cell does
  not undo the value in an existing workbook.
  Nonzero values preserve the selected face/PID, choose original arm and neck
  donors from the matching leg bucket, and recolour the face palette towards
  the donor neck. The roster leg byte is `6 - Skin Tone`.
  This requires a matching ISO, not only PCSX2 texture replacements; see below.

The scraper applies overrides after computing ratings and sanitizing names,
then builds the live `Overall` formulas. Stats JSON remains independently
generated and is never manually overlaid.

To reapply edits without scraping:

```powershell
python scripts\player_database.py
python scripts\build_roster.py --season 2026_2027
```

`--workbook`, `--overrides` and `--blacklist` select alternate paths for the
manual apply command. `update_season.py --skip-scrape` applies manual edits
before its other steps. Clearing/removing an override stops future application;
regenerate the workbook to restore the scraped/model value already overwritten
by an earlier application.

#### Manual complexion workflow

After editing `Skin Tone` in the override CSV, run the usual update with ISO
options (and optionally `--card`, with PCSX2 closed):

```powershell
python scripts\update_season.py --skip-scrape --season 2026_2027 --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "<NEW output ISO path>"
```

Face matching prepares `data/face_match/skin_tone_plan.json`, bound to every
current player/PID/tone. The single combined ISO build consumes this recipe
together with the team palettes, court edits and stats-year anchor. No separate
player-texture ISO patch is needed. The chosen face in the contact sheet previews
the prepared recolour; alternative candidates remain unrecoloured.

The provisional `--prepare-faces` roster cannot write a card. Final standalone
roster builds with nonzero tones require a matching prepared plan; do not use
their payload without its corresponding combined ISO. A changed PID/tone/roster
requires preparing the recipe again. No manual tone applies to two players
sharing a PID: model edits affect every use of that PID.

Fixed compressed resource spans and decoder scratch space remain hard limits.
The planner tries other safe same-bucket donors; if none fits, it stops before
publishing the face map/plan, ISO or card, identifying the target PID and resource.
Select another face PID or return that player to automatic mode; no complexion
is silently substituted. Some existing PIDs cannot accommodate every bucket.
Legacy light-reserve face/neck PNG generation skips manual-tone players and
prunes its old managed files; donor keys affected by the remaining global reserve
replacements are excluded. Boot the new ISO and load models fresh: F10 or an old
savestate containing loaded models does not load these ISO edits.

`data/blacklist.csv` has `Team,ProA ID,Reason`; only the ID affects behavior.
Blacklisted IDs are filtered out of freshly scraped **and cached** team rosters
before profile/stat/portrait requests and the top-player cutoff. The standalone
apply command also removes blacklisted workbook rows; regenerating the workbook
allows the next eligible player to fill the vacated top-player slot.

#### Missing portraits

After downloading portraits (or inspecting cached portraits with `--no-portraits`
or `--stats-json-only`), the scraper lists each player served the shared silhouette,
plus uncached/failed images, with team, name and ProA ID. It reports whether a
manual portrait already exists. The known shared silhouette is recognized even
when only one player uses it; repeated identical files also use the existing
cropper's shared-placeholder detection.

Add a **512x512 head-and-shoulders PNG** at
`assets/PS_out/<ProA ID>.png`, then rerun the normal replacement workflow.
Default cropping preserves existing images; avoid `crop_headshots.py --force`
if you want manual portraits left alone. Source-cache placeholders are not
silently replaced or deleted.

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
In card-only/build-only mode, counts are embedded but labels still require a separately
patched ISO. See the [verified format and rounding limits](roster_payload_format.md#historical-player-statistics).

### ISO-first roster deployment

Export and edit the [all-30-slot colour-control workspace](JerseyTextureWorkflow.md#simple-colour-controls-recommended)
first. The ISO source must be the verified untouched European original, not a prior
patched copy. Use a new output path:

```powershell
python scripts\update_season.py --season 2026_2027 --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "C:\Tools\isos\ESPN NBA 2K5 (Europe) - ProA.iso"
```

Add `--card "<Mcd001.ps2>"` to export the same final roster after ISO publication (PCSX2 must be closed).
The card exporter backs up the card, updates CRC/ECC and verifies read-back; it does not rebuild the roster.

Explicit alternatives, still using the pristine disc as the baseline:

```powershell
python scripts\update_season.py --season 2026_2027 --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --card-only --card "<Mcd001.ps2>"
python scripts\update_season.py --season 2026_2027 --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --build-only
```

Omitting `--iso-out` without one of these modes now fails with usage guidance, rather than silently
producing a roster that is not deployed. `--build-only` cannot write a card; neither alternative accepts `--iso-out`.

ISO mode now reads [native logo masters](./NativeLogoWorkflow.md) from
`texture_workspace_ISO`; export that workspace before running the pipeline.
`--texture-workspace PATH` selects another native workspace and its `team_palettes`
subfolder. `--team-palettes PATH` overrides those palettes for both roster
and ISO stages (`--lettering-workspace` remains an alias). It also works in alternative
modes. A missing/mismatched workspace, invalid palette, compressed edit
that does not fit, or existing output fails preflight before pipeline side effects.
Alternative modes and standalone legacy tools retain their original palette defaults.

New assignments require a new workspace and explicit palette migration.

Set `uniforms.<variant>.numbers/names.mode` in each team's `colours.json` to `monochrome` and choose `fill` for simple solid
lettering, or use `outlined` with three base colours. `palette` retains legacy
swatch editing. Export refreshes previews; the pipeline derives palettes in memory
from these controls without rewriting them.

The ISO stage embeds the complete final default roster: names, teams, starters, ratings,
PIDs, accessories, colleges, arena names and historical statistics. It also patches shared
number/name RGB, courts with `court.mode=recolour`, the player-card season-label anchor
matching `--season`, requested model-local skin recipes, and the native logo/centerlogo
masters. It does **not** embed PCSX2 portrait/legacy skin replacement PNGs. This extends the **roster-portable milestone**,
not yet a fully portable visual mod. Number swatches update court and preview
sources together; names remain independent. Artist edits are never overwritten or
derived automatically from the independent jersey/UI settings. Existing output ISOs are refused.
The source remains untouched and an adjacent `.season.json` records roster and visual
patch fingerprints plus full source/output hashes. All changes are composed against the
same pristine source and published once; never chain patchers over previous outputs.
Final roster storage and all patch overlaps are validated before publication.
Legacy logo PNG generation is skipped in ISO mode unless
`--legacy-logo-replacements` is supplied. Existing replacement files are left
alone; disable them when reviewing the native result. The fixed-span logo defaults
have compression-capacity blockers. Experimental `--repack-archive` instead pools
native package sectors without changing filesystem extents or image size; it is
forwarded to preflight and final composition. It currently fits the complete logo
set without further artwork reductions, but remains opt-in pending the batched
runtime review in [archive repacking](./ArchiveRepacking.md).

Boot the new ISO **fresh**, with no savestate or old roster loaded. Disable both card
slots for an unambiguous default-roster test. Existing saved rosters can replace disc
defaults when loaded; existing franchise/season saves are not migrated. F10 reloads
replacement textures, not the embedded roster or ISO assets.

Standalone `lettering_workspace.py check/build` remains available for visual-only builds;
its `.lettering.json` output does not embed a roster. Standalone `build_roster.py --base PATH`
retains the legacy save-baseline workflow for experiments; season automation never uses it.

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
press F10 in PCSX2 for replacement textures and rebuild/cold-boot the ISO for roster changes.
For card-only exports, load the updated roster from the card instead.

## Manual prerequisites when the set of clubs changes

1. `TEAM_MAP` in `scrape_proa_roster.py`: site team id -> (display name, sheet name). New ids are listed by
   `scrape_proa_roster.py --teams-only --season S` (marked "NOT IN TEAM_MAP").
2. `data/proa_teams.csv`: team names and home arena (see schema below).
   Row order = logo asset index (`nba2k_editor/assets/<38+row>.png`), so a new club takes the row of the club it replaces.
3. `data/team_slots.csv`: sheet -> NBA slot. The new club inherits the slot of the replaced club (textures are keyed by NBA slot);
   keep the default-matchup club (Falcons, slot 21) where it is.
   Edit the corresponding `texture_workspace_ISO/team_palettes/<slot>/colours.json`
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
[ISO team palette document](../texture_workspace_ISO/team_palettes/README.md).
`colorjersey1/2` remain available for the future native cloth workflow; the legacy
baseline cloth generator still reads the original workspace's palette documents.
`colorui1/2` feed roster RGB
triplets at `+0x62` / `+0x65` (UI/accessories and secondary backgrounds).
The UI colours were initially copied exactly from the jersey colours, but can now be
edited independently. Review light `colorui2` defaults (especially white) for text
contrast; no automatic darkening is applied. These are **not lettering colours**.
`build_roster.py --teams PATH --team-palettes PATH` reads metadata and palette documents, writes both UI triplets and
arena names, and reports UI colours in `team_map.csv`. The separate `--arenas` option
has been removed. Hex UI values must have exactly six digits, optionally prefixed by `#`.

Shared lettering and court settings live in the same documents but are independent
of jersey/UI values, and use the [combined ISO stage](#iso-first-roster-deployment).

## Not automated

- New clubs' **jerseys** (and non-logo court/arena artwork): court colours can now be approximated via team palettes; native logo masters are wired, while other layouts still come from the original slot.
  Needs texture dumps + the LOD pipeline, see `JerseyTextureWorkflow.md`.
- **Arena names** of new clubs (unverified guesses).
- **Player corrections** (`data/overrides.csv`): preferred shortened names, handedness, accessories and fixed ratings. Apply with `player_database.py` or re-scrape.
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
