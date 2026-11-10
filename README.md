# PROA2K5

Replace the NBA teams/players of ESPN NBA 2K5 (PS2, SLES-53022, run in PCSX2) with the German ProA
roster. Companion of the 2K26 live-memory project; only its data pipeline is reused.

## Layout
- `proa.xlsx`, `proa_rosters.xlsx`, `proa_scraped.xlsx` - frozen ProA datasets (do not regenerate).
- `scripts/scrape_proa_roster.py`, `scripts/proa_attr_model.py` - ProA scrape and stats model; the model outputs the 19 NBA 2K5 attributes directly (cached data pipeline from the 2K26 project).
- `scripts/fit_overall.py`, `scripts/overall_model.py` - fit/apply the in-game overall formula (`data/overall_model.json`) from `overall_ratings.xlsx`; see docs/player_record_layout.md.
- `scripts/` PS2 tooling: PCSX2 RAM access (`fast_scan.py`, `full_scan_ps2_base.py`, `pine_client.py`),
  input/screen automation (`pcsx2_controller.py`, `pcsx2_capture.py`), live name patching (`patch_names.py`),
  memory-card roster reader/writer with ECC (`mc_inspect.py`, `mc_write.py`), repack experiment (`repack_test1.py`).
- `docs/` - findings: `poc_findings.md`, `roster_budget_plan.md`, `pcsx2_texture_mapping.md`, `pcsx2_memory_attach.md`.
- `assets/PS_out`, `nba2k_editor/assets` - cached player/team images and name/logo mappings.
- `archive/` - git-ignored leftovers from the 2K26 editor and early experiments (not used).

## Status
- Names: proven live (RAM patch) and via the memory-card roster file (strings may be lengthened/relocated).
- Textures: PCSX2 replacement PNGs named after the dump keys work.
- Roster deployment is ISO-first: `scripts/update_season.py` builds from the pristine European disc roster,
  embeds the ProA default roster alongside lettering/court/year/skin patches, and optionally exports the same
  payload to a memory card. Portrait/logo/legacy skin PNGs still require PCSX2 replacements.

```powershell
python scripts\update_season.py --season 2026_2027 --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "C:\Tools\isos\ProA.iso"
```

Use a new output path and boot fresh, without loading an older roster or savestate.
Add `--card PATH` for an additional card export; `--card-only --card PATH` or `--build-only`
are explicit alternatives to ISO publication (both still require `--iso-source`).
See [season setup and commands](docs/SeasonUpdateWorkflow.md#iso-first-roster-deployment).
