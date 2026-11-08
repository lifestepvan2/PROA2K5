# Team palettes

Edit `000/colours.json` through `029/colours.json`: one document per **NBA roster
slot**, not arena filename. ProA assignments are in
[team_slots.csv](../../data/team_slots.csv). All 30 slots and all 79 existing
uniform variants are supported. Existing lettering edits were migrated unchanged.

## JSON schema

```json
{
  "schema": 1,
  "team": {
    "colorjersey1": "#B51514",
    "colorjersey2": "#000000",
    "colorui1": "#B51514",
    "colorui2": "#000000"
  },
  "uniforms": {
    "home": {
      "names": {
        "mode": "monochrome",
        "fill": "#FFFFFF",
        "outline1": "#000000",
        "outline2": "#FFFFFF"
      },
      "numbers": {
        "mode": "outlined",
        "fill": "#FFFFFF",
        "outline1": "#B51514",
        "outline2": "#000000"
      }
    }
  },
  "court": {
    "mode": "recolour",
    "primary": "#B51514",
    "secondary": "#000000",
    "lines": "#FFFFFF"
  }
}
```

Every RGB value is six hexadecimal digits, optionally prefixed by `#`. No alpha
authoring is exposed. Keep all actual variants (`home`, `away`, and `alt` where
present); the abbreviated example shows only `home`.

| Value | Effect |
|---|---|
| `team.colorjersey1` | Generated jersey cloth: home trim/stripes, away body |
| `team.colorjersey2` | Generated away jersey trim/stripes |
| `team.colorui1`, `team.colorui2` | Two roster/UI RGB triplets; independent of cloth and lettering |
| `uniforms.<variant>.names.fill` | Jersey name-letter fill |
| `uniforms.<variant>.numbers.fill` | Jersey-number fill, shared by gameplay and team-select preview |
| `outline1`, `outline2` | Source-relative first/second outline blend colours in `outlined` mode |
| `court.primary` | Apron / outer court colour bands; some arenas link these to paint |
| `court.secondary` | Plain zone paint and filled-circle/key masks |
| `court.lines` | Common thin-line colour, plus Hornets' apron stripe |

Lettering modes: `palette` reads the existing `<variant>/*.palette.png` RGB
swatches; `monochrome` uses `fill`; `outlined` uses all three colours. Names and
numbers are independent. The JSON stores all authoring controls, but palette mode
still intentionally uses the editable PNGs.

Court mode: `original` leaves the entire court untouched (default); `recolour`
applies all three slots. Original-mode values are representative source colours,
not a promise to reproduce the original court when switched to recolour.
Overwritten plain paint loses authored vertex RGB/opacity gradients; original
material alpha, mask alpha, hardwood, lighting, reflections and geometry remain.
Logos/lettering textures are not recoloured. Neutral hardwood-overlay materials
are left alone.

**Arena profiles deliberately differ.** Raptors/Baskets (022): primary controls
linked apron/paint regions; secondary controls linked dark floor/key regions.
No material splitting is required. Hornets (011): primary merges the original
teal/purple/gold apron bands, lines replaces its white stripe, and mip mixtures
are regenerated. Full/half-circle paint masks use secondary. Some arenas have
no separate plain zone layer; the tool does not invent one.

**Hawks (009):** uses a reduced **material-tint** profile to fit its tight
compression allocation: primary/secondary recolour the existing materials; lines
tints the original masks without replacing their palettes. Originally coloured
segments therefore retain their source hue influence rather than becoming an exact
requested RGB. Authored vertex colour/opacity is retained in this profile.
Two distinct three-colour presets passed the fixed-span checks.
Every build still verifies its exact requested profile and refuses overflow
without publishing an ISO; no controls are silently ignored or downgraded.

## Commands (repository root)

```powershell
# Export missing assets and refresh lettering previews, preserving edits:
python scripts\lettering_workspace.py export --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso"
# Validate combined lettering + court edits without changing the workspace:
python scripts\lettering_workspace.py check --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso"
# Publish a verified new ISO (never overwrite source or an existing output):
python scripts\lettering_workspace.py build --iso-source "C:\Tools\isos\ESPN NBA 2K5 (Europe).iso" --iso-out "C:\Tools\isos\team-colours.iso"
```

`build_roster.py` reads the UI colours here; `create_baseline_jersey.py` reads the
cloth colours here. `proa_teams.csv` now contains only names/arena metadata.
Season updates accept `--team-palettes PATH` (the old `--lettering-workspace`
spelling is an alias) and use the same directory for roster and ISO generation.
`reset --slot N` resets only lettering controls/swatches, **not** team/court colours.
`check`/`build` do not refresh previews. There is no generated full-court preview.
Boot a published ISO fresh; texture reload and old save states do not establish
that its court resources were freshly loaded.

Only the JSONs and this README are versioned. Original swatches, editable PNGs,
previews and the source manifest remain local; export them from the pristine ISO
when setting up a fresh checkout.
