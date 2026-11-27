# Season update workflow

1. Run `python scrape.py` to refresh roster and headshots.
2. Edit `data\overrides.xlsx` and `texture_workspace_ISO`.
3. Run `python build.py` to build the portable ISO from
   `C:\Tools\isos\ESPN NBA 2K5 (Europe).iso`.

The output is `C:\Tools\isos\proa2k5_<build-id>.iso`; existing outputs are
not overwritten. The build applies portrait and model-local skin generation,
including the automatic light reserve; explicit Skin Tone overrides take
precedence. Manual jerseys remain protected. The title build ID is stamped only
in the ISO. The ID hashes the ISO creation timestamp rather than the payload;
the manifest records the timestamp, and separate source/output hashes still
verify publication. Add `--card PATH` for an optional memory-card export.

### Persistent player edits and exclusions

`proa_scraped.xlsx` is generated output, including accessory columns, `College`
(populated from the site's `Nat` column as English country names, e.g.
`Germany / United States`), and `Shooting Hand` (0 = left, 1 = right;
default 1). Do not rely on manual workbook edits surviving a scrape.
`Skin Tone` defaults to 0 (automatic).

Edit **only `data/overrides.xlsx`** for permanent player corrections. Its `Overrides` sheet header
contains informational `Team`, the unique lookup key `ProA ID`, and every player
workbook column except the computed `Overall`. `Team` is ignored for matching
and never transfers a player; overrides follow IDs across clubs/seasons.
The existing CSV values were migrated without changing their meaning; automation
never appends to or rewrites this file. `--overrides` also accepts an explicit
legacy CSV, but the default season workflow reads the XLSX only.

The `Enumerations` sheet contains a pair of columns per dropdown: the raw value
and its display label. To add an option, append both cells immediately below
that field's existing entries; values must be valid and both values and labels
must be unique within the field. Labels can be text or numbers. Dropdowns
automatically include added contiguous rows through row 1024. If a label without
a value prefix is renamed, update existing selections to the new label too;
an unrecognized selection is an error. Older `value - description` selections
retain their value when renamed. Raw numeric values can still be entered directly,
but a value matching a numeric dropdown label is interpreted as that label first
(for example, Head 1 selects raw value 0). The lists are suggestions, not a
substitute for pipeline validation. Unlabeled
valid hairstyles may be added this way. Do not invent labels for unverified
accessory values; legacy accessory bytes remain explicitly raw.

- Blank/whitespace cell: no override. **`0` is an explicit value**, including
  left-handedness, jersey number zero and removal of accessories.
- `<CLEAR>` explicitly empties `College`. For numeric fields use 0 where allowed;
  names, positions and other required values cannot be cleared.
- `College` supplies the in-game player-card **FROM** label. Replace the country
  with an actual college in the override workbook whenever desired; manual values are
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
- Visible ratings are integers 25..99; hidden attributes use the ranges below.
  Accessory selectors use the ranges and preset/raw-index meanings documented
  in [player record layout](player_record_layout.md#accessories-verified-in-game-through-the-memory-card).
  Height is metres; weight is kg.
- Out-of-range, fractional integer and invalid-tier **numeric overrides**
  are adjusted to the nearest allowed value with a warning identifying the
  player and column (ties choose the lower value). The override file is not rewritten;
  the corrected value is applied to the workbook. Non-numeric or non-finite
  values, duplicate IDs, unknown columns, invalid dates and invalid names still
  fail explicitly because there is no unambiguous numeric correction. Direct
  workbook edits remain strictly validated. Overrides for players absent this
  season are reported and retained.
- `Years Pro` is derived from the season-history span. With stats enabled,
  conflicting overrides are rejected by the builder rather than mislabelling
  seasons. It is freely editable only for `build_roster.py --no-stats`.
- `Skin Tone`: **0 or blank = automatic; 1..6 = lightest to darkest**.
  Set it in `overrides.xlsx`, not in the generated face map. Use an explicit 0
  to reset an already-applied manual value; merely emptying its override cell does
  not undo the value in an existing workbook.
  Nonzero values preserve the selected face/PID, choose original arm and neck
  donors from the matching leg bucket, and recolour the face palette towards
  the donor neck. The roster leg byte is `6 - Skin Tone`.
  This requires the matching combined ISO; see below.

The scraper applies overrides after computing ratings and sanitizing names,
then builds the live `Overall` formulas. Stats JSON remains independently
generated and is never manually overlaid.

To reapply edits without scraping:

```powershell
python scripts\player_database.py
python scripts\build_roster.py --season 2026_2027
```

`--workbook`, `--overrides` and `--blacklist` select alternate paths for the
manual apply command. `build.py` applies manual edits
before its other steps. Clearing/removing an override stops future application;
regenerate the workbook to restore the scraped/model value already overwritten
by an earlier application.

#### Hidden attributes

The roster and override workbooks contain nine named hidden columns. The builder
writes their raw bytes unchanged; the visible-rating minimum does not apply.
The game's generic attribute accessors clamp some low raw values, but stock
records themselves contain values such as Dunk Range 10 and Standing Dunk 0.
These are roster generation rules, not experimentally verified gameplay units.

| Column | Generated value | Manual values |
|--------|-----------------|---------------|
| Dunk Range | 10 | Integer 0..99 |
| Standing Dunk | PG/SG/SF: 0; PF/C: 50; C **over** 210 cm: 99 | 0, 50, 99 |
| Offense Clutch | 99 if FG% >=55 **and** turnovers/game <=1; otherwise 75 if FG% >=50 **or** turnovers/game <=1.5; otherwise 50 | 50, 75, 99 |
| Shoot or Pass | `round(99 - 49 * min(assists / (0.75 * FGA), 1))`; higher means less passing; 50 at assists/FGA >=0.75 | Integer 50..99 |
| Defense Clutch | 99 if steals/game **and** blocks/game both strictly exceed league player averages; 75 if either does; otherwise 50 | 50, 75, 99 |
| Emotion | Fresh random integer 0..5 each time ratings are regenerated | Integer 0..15 |
| Fouls per Min | `round(20 + 79 * min(fouls/minute / 0.20, 1))` | Integer 20..99 |
| Consistency | 75 if age >=25 **and** minutes/game >=20; otherwise 50 | 50, 75, 99 |
| Fastbreak | Final generated Speed, clamped to 50..99 | Integer 50..99 |

Age uses the requested season's start year. Defensive averages use the
deduplicated scraped player pool, with recorded games and minutes, before the
per-team workbook player limit. They are means of the pooled per-game numbers,
not totals divided by league games. FGA and foul rates use the same weighted
all-league rating inputs as the existing visible attributes, **not** the
separate ProA-only archived histories. Foul rates divide weighted fouls by
weighted minutes from seasons with available foul counts; missing counts are
never treated as zero.

Without recorded games/minutes: clutch 50, Shoot or Pass 75, Fouls per Min 60,
Consistency 50. Without FGA: Shoot or Pass 75 and Offense Clutch 50. Missing
foul totals with recorded minutes emit a warning and use 60. Position/height,
Emotion and Fastbreak can still be generated without statistics.

Permanent manual values, including Emotion 6..15 and Consistency 99, belong in
`data/overrides.xlsx`. Overrides apply after generation, just like visible
ratings. Ordinary override reapplication, roster builds, ISO publication and
optional card export **never reroll Emotion**.

To migrate an older workbook or deliberately regenerate only its hidden
attributes, use the enriched cache produced by the current scraper:

```powershell
python scripts\player_database.py --refresh-hidden --rating-cache cache\proa_2026_2027\all_rosters.json --rating-year 2026
```

This inserts missing hidden columns before `Headshot ID`, uses the workbook's
current position, height, birth year and Speed, preserves existing visible
ratings/identity cells, reapplies persistent overrides and refreshes Overall
formulas. It fails before saving if a workbook player lacks cached inputs.
Older caches without FGA must first be regenerated by the current scraper.
The normal manual-apply command does not add hidden defaults silently.

Overall predictions in the workbook, roster builder, calibration tools and
website use the actual named hidden values with the existing fitted weights.
The nineteen-visible-feature vector remains unchanged. Historical calibration
datasets can still be read through their old aliases; newly generated
calibration workbooks include matching named values. Conflicting named and
legacy values are rejected, rather than silently selecting one.

#### Manual complexion workflow

After editing `Skin Tone` in the override workbook, run the usual build
(optionally with `--card PATH`, with PCSX2 closed):

```powershell
python build.py
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

The normal build uses archive repacking for both face matching and final texture compilation.
Arm, neck and recoloured face resources can change stored length and scratch;
the texture encoder preserves dimensions and uses the native indexed format.
Complete player-package edits are composed before archive relocation;
only the selected target PID is edited, never the source donor assets.
The plan records its required storage mode; a repacking recipe cannot accidentally
be published through a fixed-span builder. Older fixed-span recipes remain usable.
For standalone planning, use `face_match.py --iso-source ... --repack-archive`,
then pass the same flag to `season_iso.py` for the combined build.

The legs themselves still use the roster's `+0x69` selector for the existing six
stock textures. A failure saying `no compatible arm donor for leg tone ...`
concerns a matching **arm** TXTR, not a leg texture that needs resizing.
Logo master caps in `texture_workspace_ISO/_iso_encoding.json` do not control
player skin resources.

Texture encoding uses indexed palettes. Aggregate archive capacity, runtime
scratch and geometry compatibility still apply;
arbitrary future artwork is not guaranteed to fit an unlimited budget.
Repacking remains experimental pending the consolidated
[runtime review](./ArchiveRepacking.md#batched-runtime-review-gate).
The automatic light reserve generates model-local face, neck and arm masters and
selects light legs. Explicit Skin Tone overrides take precedence. Boot the new
ISO and load models fresh; an old savestate containing loaded models does not
load these ISO edits.

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
`assets/PS_out/<ProA ID>.png`, then rerun `python build.py`.
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
the old inherited-statistics behavior. Building requires an already-updated
schema-v2 archive. The card is written only when explicitly requested.

Labels use season start years: 2026/2027 displays 2026. Years Pro becomes the
contiguous history span, including gaps; zero-game gaps are hidden by the
game. The ISO stage automatically adds the matching season-label anchor.
See the [verified format and rounding limits](roster_payload_format.md#historical-player-statistics).

### ISO-first roster deployment

Export and edit the [all-30-slot colour-control workspace](JerseyTextureWorkflow.md#simple-colour-controls-recommended)
first. The ISO source is the verified untouched European original, not a prior
patched copy:

```powershell
python scrape.py
python build.py
```

The build reapplies `data/overrides.xlsx` without scraping, and names the output
from its build ID. Existing output ISOs are not overwritten. Do not follow it with a standalone
texture build from the pristine ISO: that produces a separate visual-only ISO
and does not carry over the first ISO's roster. Removed overrides may remain in
the existing workbook, as described above.

Add `--card "<Mcd001.ps2>"` to export the same final roster after ISO publication (PCSX2 must be closed).
The card exporter backs up the card, updates CRC/ECC and verifies read-back; it does not rebuild the roster.

ISO mode reads [native logo masters](./NativeLogoWorkflow.md) and exported
[native uniform masters](./NativeUniformWorkflow.md), plus exported
[remaining native textures](./NativeTextureWorkflow.md), from
`texture_workspace_ISO`; export the required manifests before running the pipeline.
The uniform manifest enables clothing, warmup, crowd, cheerleader and other
bundle textures automatically, without running legacy COPY/LOD sync.
A missing/mismatched workspace, invalid palette, compressed edit that does not
fit, or existing output fails rather than publishing an incomplete ISO.

New assignments require a new workspace and explicit palette migration.

Set `uniforms.<variant>.numbers/names.mode` in each team's `colours.json` to `monochrome` and choose `fill` for simple solid
lettering, or use `outlined` with three base colours. `palette` retains legacy
swatch editing. Export refreshes previews; the pipeline derives palettes in memory
from these controls without rewriting them.

The ISO stage embeds the complete final default roster: names, teams, starters, ratings,
PIDs, accessories, colleges, arena names and historical statistics. It also patches shared
number/name RGB, courts with `court.mode=recolour`, the player-card season-label anchor
matching `--season`, requested model-local skin recipes, and the native logo/centerlogo
masters, plus the exported uniform bundles and other native masters. Available
ProA headshots are encoded into native portrait textures selected by the final
roster and take precedence over those portrait masters. Missing headshots and
suppressed portraits are reported.
Shared lettering/artwork resources
are compressed once after decoded edits are composed; conflicting edits fail
explicitly. Number swatches update court and preview
sources together; names remain independent. Artist edits are never overwritten or
derived automatically from the independent jersey/UI settings. Existing output ISOs are refused.
The source remains untouched and an adjacent `.season.json` records roster and visual
patch fingerprints plus full source/output hashes. All changes are composed against the
same pristine source and published once; never chain patchers over previous outputs.
Final roster storage and all patch overlaps are validated before publication.
Archive repacking pools native package sectors without changing filesystem
extents or image size. Runtime review remains pending; see the batched
runtime review in [archive repacking](./ArchiveRepacking.md).

Boot the new ISO **fresh**, with no savestate or old roster loaded. Disable both card
slots for an unambiguous default-roster test. Existing saved rosters can replace disc
defaults when loaded; existing franchise/season saves are not migrated.

Standalone `lettering_workspace.py check/build` remains available for visual-only builds;
its `.lettering.json` output does not embed a roster. Standalone `build_roster.py --base PATH`
retains the legacy save-baseline workflow for experiments; season automation never uses it.

## Ratings website (GitHub Pages)

`.github/workflows/pages.yml` rebuilds and deploys a static site (`site_src/` frontend, built by `scripts/build_site.py`) on every
push to `main` that touches `proa_scraped.xlsx`, `data/proa_stats.json`, `data/overall_model.json`, `assets/PS_out/**`, `site_src/**`
or the build scripts. Nothing is committed back; the site is a deploy artifact.

- Ratings and bio come from `proa_scraped.xlsx` (edit there, commit, push). Overall is computed by `overall_model.py` (same model
  as the workbook's formula column). Stats come from `data/proa_stats.json`, which every scraper run writes
  (`scrape.py --stats-json-only` rebuilds it from the cache without touching the workbook). Team badges are linked live from
  `api.2basketballbundesliga.de/pics2/<season>/lp/<team id>`; portraits are resized from `assets/PS_out/`.
- Local preview: `python scripts/build_site.py --check`, then `python -m http.server -d site`.
- One-time setup: repository Settings -> Pages -> Source = GitHub Actions.

## Pipeline notes

Review `docs/_face_sheets/`, edit `override_pid` in `proa_pid_map.csv` if needed,
then rebuild and cold-boot the ISO.

## Manual prerequisites when the set of clubs changes

1. `TEAM_MAP` in `scrape.py`: site team id -> (display name, sheet name). New ids are listed by
   `scrape.py --teams-only --season S` (marked "NOT IN TEAM_MAP").
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
`colorjersey1/2` remain independent of native cloth artwork; the legacy baseline
cloth generator still reads the original workspace's palette documents.
Edit native uniform masters directly for ISO clothing changes.
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

- New clubs' **jersey artwork**: edit the exported ISO game/preview masters;
  warmups, fans and cheerleaders can be edited in the same slot folders.
  Native mips are generated automatically; see [NativeUniformWorkflow.md](./NativeUniformWorkflow.md).
  Arena props, sponsors/signage and remaining court artwork are editable in
  home-team slot folders; see [NativeTextureWorkflow.md](./NativeTextureWorkflow.md).
- **Arena names** of new clubs (unverified guesses).
- **Player corrections** (`data/overrides.xlsx`): preferred shortened names, handedness, accessories and fixed ratings. Apply with `player_database.py` or re-scrape.
- **Face overrides** after reviewing the contact sheets; **hair** (bald vs. not) is not modelled.
- Players with only the site's **silhouette** portrait (no headshot, no face match): they take whatever pid is left over and
  have no lineup headshot. Fix by providing `assets/PS_out/<proa_id>.png` by hand and re-running.
- Closing PCSX2 before writing the card.

## 2026/27 notes

- Replaced Hagen, Muenster, Leverkusen with Essen (site id 444, ETB Miners), Heidelberg (488, MLP Academics) and Ulm (537,
  OrangeAcademy), taking slots 23 (Rockets), 28 (Warriors) and 13 (Kings). Falcons stay at slot 21.
- Rosters on the site are still being filled (11-15 players per team, 249 total at the time). Ratings are derived from stats pooled over
  several seasons (see "Stats pooling"); new players without any games get defaults. Re-run the update as rosters grow; cached
  players keep their face pid.
- Roster size: a team record holds up to 17 players, and the builder writes the game's roster count byte (`+0x60`, see
  `roster_payload_format.md`). The scraper writes at most 17 players per team (`--top`, default and maximum 17). Larger
  site rosters are triaged: players with the fewest current-season ProA minutes are dropped first, and the youngest go
  first among equal minutes (usually 0:00). Each drop is printed as `Triage: dropped ...`. Any roster change alters the
  skin-plan signature, so re-run `face_match.py` before building.
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
