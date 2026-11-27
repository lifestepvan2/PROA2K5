# PROA2K5

Replace the NBA teams/players of ESPN NBA 2K5 (PS2, SLES-53022, run in PCSX2) with the German ProA
roster. Companion of the 2K26 live-memory project; only its data pipeline is reused.

## Layout
- `proa_scraped.xlsx` - latest scraped roster; `proa.xlsx` and `proa_rosters.xlsx` are older datasets.
- `scrape.py`, `scripts/proa_attr_model.py` - ProA scrape and stats model; the model outputs the 19 NBA 2K5 attributes directly (cached data pipeline from the 2K26 project).
- `scripts/fit_overall.py`, `scripts/overall_model.py` - fit/apply the in-game overall formula (`data/overall_model.json`) from `overall_ratings.xlsx`; see docs/player_record_layout.md.
- `scripts/` PS2 tooling: PCSX2 RAM access (`fast_scan.py`, `full_scan_ps2_base.py`, `pine_client.py`),
  input/screen automation (`pcsx2_controller.py`, `pcsx2_capture.py`), live name patching (`patch_names.py`),
  memory-card roster reader/writer with ECC (`mc_inspect.py`, `mc_write.py`), repack experiment (`repack_test1.py`).
- `docs/` - findings: `poc_findings.md`, `roster_budget_plan.md`, `pcsx2_texture_mapping.md`, `pcsx2_memory_attach.md`.
- `assets/PS_out`, `nba2k_editor/assets` - cached player/team images and name/logo mappings.
- `archive/` - git-ignored leftovers from the 2K26 editor and early experiments (not used).

## Status
- Names: proven live (RAM patch) and via the memory-card roster file (strings may be lengthened/relocated).
- Roster and texture deployment uses one portable ISO built from the pristine European disc.
- Automatic light-reserve recolouring and explicit Skin Tone overrides are embedded as model-local textures.
- Approved per-style created-player low-detail hair is embedded by default, including the final cornrows.
- The conversion build pipeline is feature-complete; manual texture artwork is the remaining conversion work.
  Further automation and quality-of-life improvements are optional. Original PS2 hardware remains unvalidated.

```powershell
python scrape.py
# Make manual edits to data\overrides.xlsx and texture_workspace_ISO.
python build.py
```

The ISO is named `C:\Tools\isos\proa2k5_<build-id>.iso`; existing outputs are not overwritten.
Boot fresh without loading an older roster or savestate. Add `--card PATH` for an additional card export.
Use `--basic-meshes` only to fall back to the three stock low-detail hair meshes.
See [season setup and commands](docs/SeasonUpdateWorkflow.md#iso-first-roster-deployment).
