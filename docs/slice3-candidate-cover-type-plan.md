# Slice 3 — Candidate Cover-Type and Forest-Land Raster Plan

**Application:** Tribal Forest MapCP  
**Status:** Draft — awaiting user approval before implementation.  
**Authority:** `AGENTS.md`, `docs/project-specification.md`,
`docs/mescalero-cover-type-definitions.md`  
**Prerequisites:**
- Slice 2 complete: `inspect_landfire_v2_cover_type_inputs` passes all tests.
- Slice 2b complete: `_load_lf2025_evt_labels()` helper present and tested.
- Local collected sample: `outputs/lfps_v2_extract_3b83d63b-cf47-47a1-8a21-09ee1659cedb/`
- Local reference cache: `project_data/reference_data/landfire/LF2025_EVT.csv`
- Local cover scheme: `project_data/cover_schemes/mescalero_v1_cover_scheme_v1.json`

---

## 1. Objective and scope

Produce the first actual candidate cover-type and candidate forest-land rasters
from the collected Mescalero LF2025 EVT sample, using the approved 17-code
EVT crosswalk below.

**In scope:**
- One new crosswalk approval record (JSON, versioned).
- One new internal helper: `_apply_evt_crosswalk()`.
- One new public `@mcp.tool()`: `map_candidate_cover_types`.
- Six durable output artifacts written to `outputs/`.
- New test module `tests/test_slice3_cover_type_map.py`.

**Out of scope:**
- No patches, polygon generalization, stand delineation, or accessibility.
- No EVC/EVH classification thresholds.
- No disturbance product.
- No FIA calibration.
- No ArcGIS Pro opening confirmed by Bob — user performs that check.

---

## 2. Source inputs (verified locally)

| Item | Path | Notes |
|------|------|-------|
| GeoTIFF | `outputs/lfps_v2_extract_3b83d63b-.../jcdfeda68332a4ef6b77f6b2d7677d9be.tif` | 41×41 px, EPSG:5070, 30 m, 3 bands, int16, NoData=-9999 |
| Collection manifest | `outputs/lfps_v2_collection_20261005T200127279087Z_3b83d63b-....json` | job_id=3b83d63b |
| EVT ADD CSV cache | `project_data/reference_data/landfire/LF2025_EVT.csv` | SHA-256 recorded in Slice 2b |
| Cover scheme | `project_data/cover_schemes/mescalero_v1_cover_scheme_v1.json` | scheme_id=mescalero_v1, version=v1 |

---

## 3. Proposed output integer-code table (codebook v1)

All outputs are **preliminary, candidate, and review-required**. Not field
inventory. Not Tribal-approved management classes.

| Raster int | Output label | candidate_forest_land | Source EVT codes |
|---|---|---|---|
| 1 | candidate_P | true | 7054 |
| 2 | candidate_PJ | true | 7025 |
| 3 | candidate_RIP_WOODY | true | 9035 |
| 4 | candidate_BR | false | 7086, 7104, 7107, 7121 |
| 5 | candidate_G | false | 7146, 7256, 9810, 9828 |
| 6 | candidate_RIP_NONFOREST | false | 9017, 9829 |
| 7 | candidate_RIP_UNCERTAIN | null (unknown) | 9329, 9519, 9535 |
| 8 | candidate_UNCERTAIN_PINE_OAK | null (unknown) | 7024 |
| 255 | unmapped_evt (valid, unexpected code) | null | any observed code not in crosswalk |
| -9999 | nodata | — | EVT NoData pixels |

**Forest-land raster codes:**

| Raster int | Meaning |
|---|---|
| 1 | candidate_forest_land = true |
| 0 | candidate_forest_land = false |
| 2 | candidate_forest_land = unknown (null) |
| -9999 | nodata |

`candidate_UNCERTAIN_PINE_OAK` (int 8) is a processing/review outcome, not a
Mescalero forestry type. It is not added to the cover scheme. It is documented
in the codebook with an explicit note: "EVT 7024 — source does not establish
local timber-species proportions required for P, PM, or MC. Preserve for
professional review."

---

## 4. Approved 17-code crosswalk

**Crosswalk version:** `mescalero_v1_evt_crosswalk_v1`  
**Approval context:** User approval provided in this session. Approval message
recorded as `crosswalk_approval_note` in the crosswalk JSON.

### 4.1 Complete crosswalk table

| EVT | EVT_NAME (from ADD CSV) | Output label | int | Forest land | Row-specific review flags |
|---|---|---|---|---|---|
| 7024 | Madrean Lower Montane Pine-Oak Forest and Woodland | candidate_UNCERTAIN_PINE_OAK | 8 | null | `pine_oak_local_type_unresolved` |
| 7025 | Madrean Pinyon-Juniper Woodland | candidate_PJ | 2 | true | `species_composition_not_directly_measured`, `crown_cover_percentage_not_directly_measured` |
| 7054 | Southern Rocky Mountain Ponderosa Pine Woodland | candidate_P | 1 | true | `species_composition_not_directly_measured`, `crown_cover_percentage_not_directly_measured` |
| 7086 | Rocky Mountain Lower Montane-Foothill Shrubland | candidate_BR | 4 | false | _(none additional)_ |
| 7104 | Mogollon Chaparral | candidate_BR | 4 | false | _(none additional)_ |
| 7107 | Rocky Mountain Gambel Oak-Mixed Montane Shrubland | candidate_BR | 4 | false | `oak_brush_vs_oak_woodland_review_required` |
| 7121 | Apacherian-Chihuahuan Semi-Desert Shrub-Steppe | candidate_BR | 4 | false | `shrub_grass_mixture_not_resolved` |
| 7146 | Southern Rocky Mountain Montane-Subalpine Grassland | candidate_G | 5 | false | _(none additional)_ |
| 7256 | Apacherian-Chihuahuan Semi-Desert Grassland | candidate_G | 5 | false | _(none additional)_ |
| 9017 | Rocky Mountain Alpine-Montane Wet Meadow | candidate_RIP_NONFOREST | 6 | false | `riparian_feature_preserved` |
| 9035 | North American Warm Desert Lower Montane Riparian Woodland | candidate_RIP_WOODY | 3 | true | `riparian_feature_preserved`, `riparian_subtype_not_resolved`, `species_composition_not_directly_measured`, `crown_cover_percentage_not_directly_measured` |
| 9329 | Western North American Ruderal Wet Shrubland | candidate_RIP_UNCERTAIN | 7 | null | `riparian_feature_preserved`, `riparian_forest_land_status_unresolved`, `ruderal_source_class` |
| 9519 | Rocky Mountain Lower Montane-Foothill Riparian Shrubland | candidate_RIP_UNCERTAIN | 7 | null | `riparian_feature_preserved`, `riparian_forest_land_status_unresolved` |
| 9535 | North American Warm Desert Lower Montane Riparian Shrubland | candidate_RIP_UNCERTAIN | 7 | null | `riparian_feature_preserved`, `riparian_forest_land_status_unresolved` |
| 9810 | North American Warm Desert Ruderal Planted Grassland | candidate_G | 5 | false | `ruderal_source_class` |
| 9828 | Interior Western North American Temperate Ruderal Grassland | candidate_G | 5 | false | `ruderal_source_class` |
| 9829 | Western North American Ruderal Wet Meadow Marsh | candidate_RIP_NONFOREST | 6 | false | `riparian_feature_preserved`, `ruderal_source_class` |

### 4.2 Flags applied to every output pixel

- `overstory_understory_not_modeled`
- `disturbance_not_evaluated`
- `professional_forestry_review_required`

### 4.3 Policies carried through

- EVC/EVH: preserved as source evidence only. No EVC/EVH classification
  thresholds applied.
- Disturbance: `disturbance_status = not_evaluated` on every pixel.
- NoData: preserved as -9999, distinct from uncertain, distinct from nonforest.
- Unmapped valid codes: integer 255 (`unmapped_evt`), `source_evt_code_unmapped`
  flag, `candidate_forest_land = null`. Do not silently assign nonforest.
- NT/NW: not present in this 17-code sample; policy unchanged.

---

## 5. Files to create or modify

### New files

| File | Purpose |
|------|---------|
| `project_data/crosswalks/mescalero_v1_evt_crosswalk_v1.json` | Machine-readable approved crosswalk, approval note, version, provenance |
| `tests/test_slice3_cover_type_map.py` | New test module (see §7) |

### Modified files

| File | Change |
|------|--------|
| `server.py` | New internal `_apply_evt_crosswalk()` helper; new public `map_candidate_cover_types` tool |

### Generated artifacts (at runtime, in `outputs/`)

| Artifact | Description |
|----------|-------------|
| `cmap_3b83d63b_v1_cover_type_30m.tif` | Candidate cover-type raster, int16, EPSG:5070, 30 m |
| `cmap_3b83d63b_v1_forest_land_30m.tif` | Candidate forest-land raster, int16, EPSG:5070, 30 m |
| `cmap_3b83d63b_v1_cover_type_codebook.csv` | Integer codes, labels, forest-land status, flags |
| `cmap_3b83d63b_v1_cover_type_acreage.csv` | Per-class acreage, cell count, fraction |
| `cmap_3b83d63b_v1_forest_land_acreage.csv` | Per-forest-land-status acreage, cell count |
| `cmap_3b83d63b_v1_methods.json` | Provenance, parameters, QC, limitations, approval record |

Filename prefix `cmap_<job_id>_<crosswalk_version>` is stable and short. Never
overwrite existing artifacts.

---

## 6. `map_candidate_cover_types` tool contract

**Input:** `collection_manifest_filename` (same pattern as the inspection tool)

**Prerequisites check (before any raster work):**
1. Manifest exists and is a valid LFPS v2 record.
2. GeoTIFF path resolves and file is readable.
3. No existing output artifacts for this job_id + crosswalk version.
4. Crosswalk file present and crosswalk version matches input parameter.
5. Cover scheme file present.

**Processing (internal helper `_apply_evt_crosswalk`):**
1. Read EVT band from GeoTIFF by description matching (same approach as Slice 2).
2. Build output arrays, filled with `unmapped_evt` (255) for valid, NoData for NoData pixels.
3. For each pixel: look up EVT code in crosswalk dict; assign integer output code.
4. Separately derive forest-land raster from output code lookup table.
5. Compute per-class cell counts and acres (EPSG:5070, same `_safe_cell_area` logic).
6. Verify acreage closure: sum of all output-class acres + NoData acres == total raster extent acres.
7. Verify output grid is identical to input grid (shape, transform, CRS, NoData value).

**Output rasters:**
- Same shape, transform, CRS, and NoData value (-9999) as source EVT band.
- dtype int16 (output codes 1–8, 255, -9999 all fit in int16).
- Written with rasterio, driver GTiff.

**Sentinels always False:**
- `classification_performed` is set `True` here — this is the first slice that
  intentionally sets it True. All other sentinels remain False.
- `crosswalk_applied = True`
- `candidate_cover_types_produced = True`

**Limitations block (required in every output):**
- Outputs are preliminary candidate assignments. Not field inventory. Not
  Tribal-approved management classes.
- Species composition and crown-cover criteria not directly measured.
- EVC/EVH not used for classification in this pass.
- Disturbance not evaluated.
- NT/NW policy preserved; neither assigned in this sample.
- ArcGIS Pro review by the forester required before any management use.

---

## 7. Tests

**New file:** `tests/test_slice3_cover_type_map.py`  
All tests use synthetic fixtures. No Mescalero GeoTIFF required for the
committed test suite.

| Test ID | What it verifies |
|---------|-----------------|
| M-1 | Valid synthetic raster: output arrays have same shape as input EVT band |
| M-2 | Known mapped EVT code → correct integer output code |
| M-3 | Known unmapped EVT code → integer 255, `unmapped_evt` flag |
| M-4 | NoData pixels → -9999 in both output rasters, not reassigned |
| M-5 | Forest-land raster: forest-land=true codes → int 1; false → 0; null → 2; NoData → -9999 |
| M-6 | Acreage closure: sum of per-class acres + NoData acres == total raster extent acres |
| M-7 | Output grid identical to source (shape, transform, CRS, NoData) |
| M-8 | Codebook CSV contains all 17 source EVT codes and the unmapped/NoData rows |
| M-9 | Crosswalk sentinels: `crosswalk_applied=True`, `candidate_cover_types_produced=True`, `forest_land_determination_performed=False` (EVT-only, no field determination), `candidate_polygons_produced=False` |
| M-10 | Methods JSON contains: `crosswalk_version`, `cover_scheme_id`, `evt_add_sha256`, `approval_note`, `provenance` block |
| M-opt | Conditional: runs on actual Mescalero sample when manifest present. Checks all 17 codes accounted for, acreage closure, output files exist. |

**Execution command:**
```
PYTHONPATH=. .venv\Scripts\pytest tests/test_slice3_cover_type_map.py -v
```

---

## 8. Crosswalk approval record

The crosswalk JSON file
`project_data/crosswalks/mescalero_v1_evt_crosswalk_v1.json` will contain:

```json
{
  "crosswalk_id": "mescalero_v1_evt_crosswalk_v1",
  "crosswalk_version": "v1",
  "cover_scheme_id": "mescalero_v1",
  "cover_scheme_version": "v1",
  "source_product": "LF2025_EVT",
  "approved_by": "user",
  "crosswalk_approval_note": "17-code EVT crosswalk approved by user in MapCP planning session. 7107→BR (oak_brush_vs_oak_woodland_review_required). 7024 retained as UNCERTAIN_PINE_OAK (pine_oak_local_type_unresolved). 9329, 9519, 9535 → RIP_UNCERTAIN (riparian_forest_land_status_unresolved). No EVC/EVH classification thresholds approved. Disturbance not evaluated.",
  "geographic_applicability": "Mescalero Apache Reservation pilot only",
  "evt_add_url": "https://landfire.gov/sites/default/files/CSV/LF2025/LF2025_EVT.csv",
  "evt_add_sha256": "5ccc130b250dbe709340afb2cc02ecdb3c4c374e2dba19cec91e2c2713e4963d",
  "entries": [ ... 17 entries per §4.1 ... ],
  "change_control": "Changes require a new crosswalk version file. Do not overwrite approved entries."
}
```

---

## 9. Acceptance criteria

1. All 17 observed EVT codes assigned per crosswalk table; no code silently dropped.
2. Unmapped-code and NoData handling verified by tests M-3, M-4.
3. Acreage closure verified by test M-6 and confirmed in the methods JSON.
4. Output GeoTIFFs exist, readable, same grid as source (M-7).
5. Codebook CSV complete, consistent with integer-code table in §3.
6. Methods JSON contains approval note, crosswalk version, evt_add sha256,
   cover scheme id, and provenance.
7. All M-1 through M-10 tests pass.
8. Conditional M-opt test runs on actual Mescalero sample and passes.
9. ArcGIS Pro check: user opens both output TIFs and confirms they display
   correctly. This step is recorded by the user; Bob does not claim it occurred.
10. No field in the output claims final, authoritative, or field-verified status.

---

## 10. Unresolved blockers

**None that block implementation.** One documentation discrepancy to note:

- `AGENTS.md` §"Approved Mescalero pilot decisions / Target cover scheme" lists
  29 codes including P, PM, MC, etc., but does not list `RIP_WOODY`,
  `RIP_NONFOREST`, or `RIP_UNCERTAIN` explicitly. The cover-scheme JSON
  (`mescalero_v1_cover_scheme_v1.json`) does contain all three as first-pass
  consolidation outputs. The plan treats the JSON as the authoritative record.
  AGENTS.md can be updated in a separate documentation pass.

- The existing `inspect_lf2025_3b83d63b_evt_inventory.csv` uses the pre-Slice 2b
  schema (has `label_from_xml`, lacks the new label columns). Slice 3 reads the
  GeoTIFF directly via the collection manifest and does not depend on the old
  inventory CSV for classification input.

---

## 11. Risks

- The 41×41 sample is very small (~375 valid acres). Acreage figures in the
  outputs will be reported accurately but are not representative of the full
  reservation. All outputs are labeled "sample" in artifact names.
- Integer 255 for unmapped codes fits int16 without overflow. The NoData value
  -9999 is preserved unchanged.
- `_safe_cell_area` currently supports EPSG:5070 only. The source raster is
  EPSG:5070, so this is not a blocker.
