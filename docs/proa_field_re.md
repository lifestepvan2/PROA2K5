# ProA Excel Field — Reverse Engineering Exchange Document

**Purpose:** Track decode/encode status for every column in the ProA roster Excel export.  
**Workflow:** Fill in the "Observed Values" tables below with raw↔display pairs you document  
in-game (e.g. using the live editor with memory reading). Hand the file back to get the  
codebase updated with new encode/decode logic.

---

## Legend

| Status | Meaning |
|--------|---------|
| ✅ Confirmed | Encode/Decode works end-to-end, round-trip tested |
| ⚠️ Probable | Logic implemented, needs in-game verification |
| ❓ Unknown | Raw value only; decoding not implemented |
| 🚫 Not Exported | Field exists in game but not yet in export columns |

---

## Current Export Columns — Status Overview

| Column Header | Actual Field Name | Category | Status | Notes |
|---|---|---|---|---|
| First Name | First Name | Vitals | ✅ Confirmed | UTF-16LE string |
| Last Name | Last Name | Vitals | ✅ Confirmed | UTF-16LE string |
| Position | Position | Vitals | ✅ Confirmed | Enum: 0=PG 1=SG 2=SF 3=PF 4=C |
| Secondary Position | Secondary Position | Vitals | ✅ Confirmed | Enum: 0=PG 1=SG 2=SF 3=PF 4=C 5=N/A 6=NULL |
| Jersey Number | Jersey Number | Vitals | ⚠️ Probable | Raw int 0–99; assumed raw=display |
| Age | Age | Vitals | ⚠️ Probable | Raw int; assumed raw=display (years). **Needs verification** |
| Years Pro | Years Pro | Vitals | ⚠️ Probable | Raw int; assumed raw=display. **Needs verification** |
| Height | Height | Vitals | ✅ Confirmed | Encoded via formula; decode=`raw_height_to_inches` |
| Weight | Weight | Vitals | ✅ Confirmed | IEEE-754 float (lbs) |
| Close Shot | Close Shot | Attributes | ✅ Confirmed | Rating 0–99 via `convert_raw_to_rating` |
| Midrange Shot | Midrange Shot | Attributes | ✅ Confirmed | Rating 0–99 |
| 3pt Shot | 3pt Shot | Attributes | ✅ Confirmed | Rating 0–99 |
| Free Throws | Free Throws | Attributes | ✅ Confirmed | Rating 0–99 |
| Driving Layup | Driving Layup | Attributes | ✅ Confirmed | Rating 0–99 |
| Driving Dunk | Driving Dunk | Attributes | ✅ Confirmed | Rating 0–99 |
| Standing Dunk | Standing Dunk | Attributes | ✅ Confirmed | Rating 0–99 |
| Post Hook | Post Hook | Attributes | ✅ Confirmed | Rating 0–99 |
| Post Fade | Post Fade | Attributes | ✅ Confirmed | Rating 0–99 |
| Post Moves | Post Moves | Attributes | ✅ Confirmed | Rating 0–99 (formerly called "Post Control" in UI) |
| Draw Foul | Draw Foul | Attributes | ✅ Confirmed | Rating 0–99 |
| Shot IQ | Shot IQ | Attributes | ✅ Confirmed | Rating 0–99 |
| Offensive Consistency | Offensive Consistency | Attributes | ✅ Confirmed | Rating 0–99 |
| Ball Control | Ball Control | Attributes | ✅ Confirmed | Rating 0–99 |
| Speed with Ball | Speed with Ball | Attributes | ✅ Confirmed | Rating 0–99 |
| Pass Accuracy | Pass Accuracy | Attributes | ✅ Confirmed | Rating 0–99 |
| Passing IQ | Passing IQ | Attributes | ✅ Confirmed | Rating 0–99 |
| Passing Vision | Passing Vision | Attributes | ✅ Confirmed | Rating 0–99 |
| Interior Defense | Interior Defense | Attributes | ✅ Confirmed | Rating 0–99 |
| Perimeter Defense | Perimeter Defense | Attributes | ✅ Confirmed | Rating 0–99 |
| Steal | Steal | Attributes | ✅ Confirmed | Rating 0–99 |
| Block | Block | Attributes | ✅ Confirmed | Rating 0–99 |
| Offensive Rebound | Offensive Rebound | Attributes | ✅ Confirmed | Rating 0–99 |
| Defensive Rebound | Defensive Rebound | Attributes | ✅ Confirmed | Rating 0–99 |
| Help Defense IQ | Help Defense IQ | Attributes | ✅ Confirmed | Rating 0–99 |
| Defensive Consistency | Defensive Consistency | Attributes | ✅ Confirmed | Rating 0–99 |
| Speed | Speed | Attributes | ✅ Confirmed | Rating 0–99 |
| Agility | Agility | Attributes | ✅ Confirmed | Rating 0–99 |
| Strength | Strength | Attributes | ✅ Confirmed | Rating 0–99 |
| Vertical | Vertical | Attributes | ✅ Confirmed | Rating 0–99 |
| Stamina | Stamina | Attributes | ✅ Confirmed | Rating 0–99 |
| Hustle | Hustle | Attributes | ✅ Confirmed | Rating 0–99 |
| Intangibles | Intangibles | Attributes | ✅ Confirmed | Rating 0–99 |
| Potential | Potential | Attributes | ✅ Confirmed | Rating 0–99 |

---

## Fields Needing In-Game Verification

### Age

The raw value is exported directly. Assumption: raw integer = age in years.

**To verify:** Find a player whose age is known. Record the raw value the editor shows.

| Raw value | Display (age) | Verified by |
|-----------|---------------|-------------|
| *(fill in)* | *(fill in)* | |

**Expected formula:** `display = raw` (no transformation)  
**If wrong:** Describe the transformation you observe (e.g. `raw = birth_year`, `raw = current_year - age`, etc.)

---

### Years Pro

Same as Age — assumed raw = years pro.

| Raw value | Display (years pro) | Verified by |
|-----------|---------------------|-------------|
| *(fill in)* | *(fill in)* | |

---

### Jersey Number

Assumed raw = jersey number displayed.

| Raw value | Display (number) | Verified by |
|-----------|------------------|-------------|
| *(fill in)* | *(fill in)* | |

---

## Fields Not Yet Exported — Candidates for Future Columns

These fields exist in the game / editor but are not in the current ProA export. Add RE data here if you want them added.

### Appearance / Physical

| Field Name | Category | Status | Known Encoding | Notes |
|---|---|---|---|---|
| Skin Tone | Vitals | ❓ Unknown | Raw int (range unknown) | Likely 0–N index |
| Face ID | Vitals | ❓ Unknown | Integer ID | Probably references a face model asset |
| Headshot ID | Vitals | ❓ Unknown | Integer ID | |
| Wingspan | Vitals | ❓ Unknown | Same formula as Height? | `raw_height_to_inches`? **Needs verification** |
| Dominant Hand | Vitals | ✅ Enum known | 0=Left, 1=Right | Not included because rarely changed for ProA |

#### Template — add your RE data for these:

```
### [Field Name]
- **Category**: [Category]
- **Offset (2K26)**: 0x?????
- **Length**: ? bits

| Raw | Display value | Game context |
|-----|---------------|--------------|
| 0   | ?             | Player: [name], observed in [screen] |
| 1   | ?             | |
| ... |               | |

**Formula (if scaled):** e.g. `display = raw * 0.5 + 30`
```

---

### Tendencies (selected)

Tendencies are available via the editor but excluded from ProA export to keep the sheet manageable.  
They are stored as ratings using `convert_tendency_raw_to_rating`. No RE needed — formula is known.  
Add a column header matching the exact field name to include any tendency in the export.

---

### Potential (min/max)

| Field | Category | Status | Notes |
|---|---|---|---|
| Minimum Potential | Vitals | ✅ Known | `convert_raw_to_minmax_potential` |
| Maximum Potential | Vitals | ✅ Known | `convert_raw_to_minmax_potential` |

These use a different formula than player ratings. They could be added to the export; let me know.

---

### Signature Animations (advanced)

These are enum fields that select NBA player animations. They are already decoded as enum labels by the editor.  
They are excluded from the basic ProA export since ProA players won't use NBA signatures.

| Field | Category | Example Values |
|---|---|---|
| Post Fade (Signature) | Signatures | Big, Small, Basic, Normal, Pro, Kobe Bryant, ... |
| Post Hook (Signature) | Signatures | Small, Basic, Normal, Pro, Kareem Abdul-Jabbar, ... |
| Free Throw (Signature) | Signatures | (free throw animation selector) |

---

## How to Add New Fields to the Export

1. Confirm the exact field name using the editor (Vitals/Attributes tab) or by checking the values above.
2. Add the field name string to `_PROA_PLAYER_COLUMNS` in `nba2k_editor/importing/excel_import.py`.
3. If the decode is non-standard (not already handled by `decode_field_value`), implement it in  
   `_decode_field_value_from_record` and `_coerce_field_value` in the same pattern as Height/Weight.
4. If an enum has a custom mapping not in `dropdowns.json`, add it to  
   `nba2k_editor/Offsets/dropdowns.json` under the correct canonical_category/normalized_name/2K26 entry.

---

## Raw Value Datapoint Submission Format

When handing this document back for a code update, fill tables like this:

```
### [Field Name] — UPDATE REQUEST

| Raw | Display | Context |
|-----|---------|---------|
| 0   | 25      | ProA player, freshly exported, Age shown as 25 in editor |
| 127 | 36      | Another player |

Formula derived: display = raw - 2   (or whatever you determined)
```

Then I'll implement the transformation in `decode_field_value` / `_coerce_field_value` and update this document.
