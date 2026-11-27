# Command cheat sheet

1. Update the roster and headshots: `python scrape.py`
2. Make manual edits in `data\overrides.xlsx` and `texture_workspace_ISO`.
3. Build the portable ISO: `python build.py`

For another season, pass the same `--season YYYY_YYYY` to both commands.

Optional: `python build.py --basic-meshes` maps the supported created hairstyles
to the three stock low-detail hair meshes. Without the flag, the game retains
its original low-detail selection; custom low-detail meshes are not yet integrated.

The build reads `C:\Tools\isos\ESPN NBA 2K5 (Europe).iso` and writes
`C:\Tools\isos\proa2k5_<16-digit-build-id>.iso` plus a `.season.json` manifest.
Existing output files are not overwritten. The title image is stamped only in
the ISO. The build ID is derived from the creation timestamp, not the payload;
identical inputs produce different IDs. Roster portrait and requested skin
masters are regenerated in the workspace. For other textures, edited masters take precedence over overlapping
generated colour controls; alternate uniform copies preserve edited resources.
Automatic light-reserve recolouring and explicit Skin Tone overrides generate
model-local skin textures. Explicit overrides take precedence.

Optional: `python scripts\create_baseline_jersey.py --dry-run` previews baseline
uniform generation; omit `--dry-run` to update unedited native masters. Manually
edited jerseys are always preserved.

Optional: `python build.py --card "C:\path\to\card.ps2"` also writes the final
roster to a memory card after the ISO succeeds. Close PCSX2 first.

