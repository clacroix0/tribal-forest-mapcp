# Slice 2 — `inspect_landfire_v2_cover_type_inputs` Implementation Plan

**Application:** Tribal Forest MapCP  
**Status:** Revised draft — awaiting user approval before implementation.  
**Authority:** `AGENTS.md`, `docs/project-specification.md`,
`docs/cover-type-onboarding-plan.md`  
**Prerequisite:** Slice 1 complete. `cover_scheme_models.py` committed. Local
Mescalero cover-scheme config at
`project_data/cover_schemes/mescalero_v1_cover_scheme_v1.json` exists.

---

## 1. Objective and scope

Implement the public MCP tool `inspect_landfire_v2_cover_type_inputs`.

The tool accepts the filename of an existing LFPS v2 collection manifest
(already produced by `collect_landfire_v2_sample_result`), opens the
three-band GeoTIFF and the three co-located XML metadata files it references,
performs read-only raster inspection, and writes three durable artifacts to
`outputs/`. It returns a structured summary to the caller.

**This tool must inspect, not classify.** No candidate class assignment,
forest-land determination, crosswalk application, polygon creation, or
candidate acreage calculation occurs.

**Purpose:** Produce a visible, documented, durable pre-classification review
record — an evidential foundation the forester can review and approve before
any crosswalk or mapping work begins. This satisfies the MVP requirement for
"Mapping-input inspection, including coverage, dates, resolution, CRS, raster
alignment, NoData, source version, and gaps" (project spec §4, §5, §7).

**Scope of this slice:**
- One new internal helper function: `_inspect_landfire_v2_inputs()`.
- One new public `@mcp.tool()`: `inspect_landfire_v2_cover_type_inputs`.
- Three durable output artifacts written to `outputs/` (see §4).
- New unit tests in `tests/test_server.py` using synthetic fixtures.
- No crosswalk creation, no classification, no polygon output.
- No cover-scheme loaded or compared.

**Not in scope of this slice:**
- EVT crosswalk schema or saver (onboarding plan Slice 2).
- Mapping-rules schema (onboarding plan Slice 3).
- Approval record model (onboarding plan Slice 4).
- Any raster classification or candidate output.

**Approved decisions incorporated in this revision:**

| Decision | Resolution |
|---|---|
| D-4: NumPy for statistics | Use NumPy if available (transitive dependency); no new package |
| D-7: EVT code table coverage | Report all observed codes regardless of scheme membership |
| D-8: Cover-scheme not loaded | Inspection is source-only; no scheme comparison in this tool |
| Band order | Never assume by position; identify by description and manifest |

---

## 2. Existing behavior to preserve

- All 16 existing `@mcp.tool()` registrations and their behavior.
- `cover_scheme_models.py` models and save/load functions.
- All existing tests in `tests/test_cover_scheme_models.py` and
  `tests/test_server.py`.
- `OUTPUT_FOLDER`, `MAX_RESPONSE_BYTES`, filename-validation patterns, and
  security posture in `server.py`.
- Filename-length constraints for Windows and OneDrive compatibility.
- The `classification_performed: false` sentinel in every report.

---

## 3. Source files and artifacts verified

| Path | Role |
|---|---|
| `server.py` | Primary change target |
| `tests/test_server.py` | Test target |
| `outputs/lfps_v2_collection_20261005T200127279087Z_3b83d63b-cf47-47a1-8a21-09ee1659cedb.json` | Existing collection manifest (local, Git-ignored) |
| `outputs/lfps_v2_extract_.../jcdfeda68332a4ef6b77f6b2d7677d9be.tif` | Three-band GeoTIFF: EVT / EVC / EVH |
| `outputs/lfps_v2_extract_.../LF2025_EVT_CONUS.xml` | EVT metadata XML — read and verified |
| `outputs/lfps_v2_extract_.../LF2025_EVC_CONUS.xml` | EVC metadata XML — read and verified |
| `outputs/lfps_v2_extract_.../LF2025_EVH_CONUS.xml` | EVH metadata XML — read and verified |

**Confirmed raster characteristics (from collection manifest):**
- Three bands: LF2025_EVT_CONUS, LF2025_EVC_CONUS, LF2025_EVH_CONUS.
- Dimensions: 41 × 41 px. Resolution: 30.0 m × 30.0 m. CRS: EPSG:5070.
- NoData: −9999. Data type: int16.
- `band_order_validation: "requires_metadata_and_arcgis_review"` — band
  position must not be assumed.

**Critical XML domain findings (verified from actual files):**

| Product | XML VALUE domain type | Encoded meaning |
|---|---|---|
| EVT | `<rdom>` 4401–9994; per-code names in external CSV/ADD only | Integer ecological-system codes; not per-code labels in XML |
| EVC | `<rdom>` 11–399; `<udom>` describes encoded class codes | Encoded class codes, not raw percent cover integers |
| EVH | `<rdom>` 11–310; `<udom>` reveals encoding: 101–199 = tree, 201–230 = shrub, 301–310 = herb height classes | Encoded height-class codes, not meters |

These findings drive the parsing strategy and the statistics interpretation
rules in §5.

---

## 4. Tool interface

### Input parameter

`collection_manifest_filename` — the exact generated filename of an LFPS v2
collection manifest already present in `outputs/`. Accepted pattern:

```
lfps_v2_collection_<timestamp>_<UUID>.json
```

No full path is accepted. The tool resolves the file only inside
`OUTPUT_FOLDER`. This follows the filename-only security pattern used by all
existing LFPS v2 tools.

### Three durable output artifacts

All three are written atomically to `outputs/` using the same `job_id` stem.
None overwrites an existing file. File stems are kept short for Windows and
OneDrive compatibility; full provenance lives inside the file content.

| Artifact | Filename pattern | Purpose |
|---|---|---|
| Markdown report | `inspect_lf2025_<job_id>_report.md` | Human-readable review document |
| JSON summary | `inspect_lf2025_<job_id>_summary.json` | Machine-readable structured summary |
| EVT inventory CSV | `inspect_lf2025_<job_id>_evt_inventory.csv` | One row per observed EVT code |

**EVT inventory CSV columns** (required):
`evt_code`, `label_from_xml`, `label_missing`, `cell_count`,
`square_meters`, `acres`, `valid_cell_fraction`, `source_tif`, `source_xml`

### Return value

The JSON summary dict plus `inspection_status`, paths to all three written
artifacts, and all mandatory sentinel fields. On any hard failure, returns a
structured error dict with `inspection_status: "failed"` and all sentinel
fields false.

### Result status field

Every tool response and every output artifact must include:

```json
"inspection_status": "success" | "partial" | "failed",
"classification_performed": false,
"forest_land_determination_performed": false,
"crosswalk_applied": false,
"candidate_cover_types_produced": false,
"candidate_polygons_produced": false
```

`partial` is used when some artifacts were produced but warnings or parse
failures were encountered (e.g., one XML missing, statistics computed but
some labels unavailable). `failed` is used when the raster cannot be opened
or the GeoTIFF path is absent from the manifest.

---

## 5. Required report and summary content

### 5.1 Provenance

- `collection_manifest_file` — absolute path.
- `geotiff_file` — absolute path resolved from the manifest.
- `evt_xml_file`, `evc_xml_file`, `evh_xml_file` — absolute paths resolved
  from the manifest; `null` if absent (triggers warning).
- `job_id`, `api_version` (from manifest).
- `inspected_at_utc` — ISO 8601 timestamp.

For each of EVT, EVC, EVH XML (when parseable):
- `source_product_title` — from `<title>`.
- `source_product_edition` — from `<edition>`.
- `source_product_pubdate` — from `<pubdate>`.
- `source_doi` — first `<onlink>` element containing `doi.org`; `null` if
  not found.
- `value_attr_definition` — text of `<attrdef>` for the `VALUE` attribute
  from `<eainfo>/<detailed>/<attr>`.
- `value_domain_type` — `"range"`, `"enumerated"`, `"unrepresented"`, or
  `"unknown"` — determined by which child element (`<rdom>`, `<edom>`,
  `<udom>`) is present under the VALUE `<attrdomv>`.
- `value_domain_min`, `value_domain_max` — from `<rdom>` if present; `null`
  otherwise.
- `value_domain_description` — from `<udom>` or `<edom>/<edomvd>` if
  present; `null` otherwise.
- `classnames_definition` — text of `<attrdef>` for the `CLASSNAMES`
  attribute if present; `null` otherwise.
- `classnames_domain_description` — `<udom>` text for CLASSNAMES if present;
  `null` otherwise.

### 5.2 Band identification

- `band_identification_method` — always `"description_matching"`.
- For each expected band (EVT, EVC, EVH):
  - `band_index_found` — 1-based index in the GeoTIFF, or `null`.
  - `band_description_stored` — exact string from `src.descriptions`.
  - `match_confidence` — `"exact"`, `"case_insensitive"`, or `"not_found"`.
- `band_identification_status` — `"all_identified"`, `"partial"`, or
  `"failed"`.
- If any required band is `"not_found"` or if multiple bands match the same
  product keyword, set `inspection_status: "failed"` and return immediately.
  Do not attempt raster reads with ambiguous or missing band assignments.

### 5.3 Raster geometry and CRS

For each identified band (drawn from the single shared GeoTIFF):
- Width, height (pixels); total cell count.
- CRS as EPSG code (or `null` if not EPSG-representable) and full WKT string.
- Affine transform (six coefficients: a, b, c, d, e, f).
- Cell size (x, y) in the CRS's native map units.
- `cell_area_map_units_sq` — abs(cell_size_x) × abs(cell_size_y).
- `cell_area_m2` and `cell_area_acres` — computed **only** when the CRS
  authority is EPSG:5070 or another confirmed metre-based equal-area
  projection. If the CRS does not support a safe metre-based planar area
  calculation, set both to `null` and add to `warnings`:
  `"Cell area in square metres and acres cannot be safely calculated for
  the raster CRS. Reported cell counts cannot be converted to acreage."`
- Bounding box in native CRS (west, south, east, north in map units).
- NoData value as stored per band.

### 5.4 Alignment checks

All three bands are in a single multi-band GeoTIFF so they share geometry
by construction. The checks are still required as explicit evidence:
- `dimensions_match` (True/False), `crs_match`, `transform_match`,
  `extent_match`, `resolution_match` — compare across the three identified
  band slots.
- `valid_data_overlap_cells` — count of pixels where all three bands are
  non-NoData simultaneously.
- `valid_data_overlap_acres` — overlap cells × `cell_area_acres`; `null` if
  acreage cannot be computed.
- Any mismatch produces a `warnings` entry.

### 5.5 EVT band — code inventory

- `evt_nodata_value` — as read from the raster.
- `evt_nodata_cell_count`, `evt_nodata_acres` (null if area unavailable).
- `evt_valid_cell_count`, `evt_total_cells`.
- `evt_value_domain_from_xml` — the range or domain extracted from the EVT
  XML VALUE `<rdom>` (`{min, max}`) or `null`; **this is the source-defined
  domain, not a hard-coded threshold**.
- `evt_codes_observed` — one record per unique valid integer code, sorted by
  `evt_code` ascending:
  - `evt_code` — integer.
  - `cell_count` — integer.
  - `square_meters` — cell_count × `cell_area_m2`; `null` if area unavailable.
  - `acres` — cell_count × `cell_area_acres`; `null` if area unavailable.
  - `valid_cell_fraction` — cell_count / evt_valid_cell_count.
  - `label_from_xml` — `null`. The LF2025 EVT XML VALUE domain uses `<rdom>`,
    not per-code `<edom>` entries. Per-code EVT names are available only in
    the external LF ADD CSV, which is not present in this local bundle. This
    is expected and documented.
  - `label_source` — `"none_rdom_only"`.
  - `label_missing` — always `true` for this product version; recorded as a
    known source limitation, not an error.
- `evt_label_availability_note` — a fixed string:
  `"LF2025 EVT per-code labels are available only in the external LF ADD CSV,
  which is not included in the LFPS v2 bundle. Labels cannot be resolved from
  the local XML alone."` This note must appear in the report and in the
  Markdown.
- `evt_codes_outside_xml_domain` — list of observed codes that fall outside
  the XML-declared `<rdom>` range (or outside −9999 and the range bounds);
  warn for each. Do not apply any fixed hard-coded bounds.

### 5.6 EVC band — value distribution

EVC values are **encoded class codes** (source XML `<rdom>` 11–399), not
direct percent-cover integers. This is stated in the XML and must be
reflected in the report.

- `evc_nodata_value`, `evc_nodata_cell_count`, `evc_nodata_acres`.
- `evc_valid_cell_count`, `evc_total_cells`.
- `evc_value_domain_from_xml` — `{min: 11, max: 399}` from the XML `<rdom>`,
  or `null` if not parseable.
- `evc_value_encoding_note` — text extracted from the XML CLASSNAMES `<udom>`
  describing what the encoded values represent (e.g., "Tree cover 10 to
  100%. Shrub cover 10 to 100%. Herb cover 10 to 100%."). `null` if
  not parseable.
- `evc_observed_min`, `evc_observed_max` — over valid cells.
- `evc_codes_outside_xml_domain` — list of observed values outside the
  XML-declared range; warn for each.
- `evc_value_counts` — list of `{evc_code, cell_count, square_meters, acres,
  valid_cell_fraction}` for each unique valid value, sorted ascending.
- `evc_descriptive_statistics` — computed using NumPy over the flat array
  of valid cell values only, and labeled explicitly as statistics of **encoded
  class codes**. Fields: `mean`, `median`, `std`, `min`, `max`. All fields
  are `null` if NumPy is unavailable. A note field
  `evc_statistics_interpretation` must always be present with value:
  `"These are descriptive statistics of encoded EVC class codes, not percent
  canopy cover values. Do not interpret mean or standard deviation as canopy
  cover percentages."` No physical-unit interpretation is made.
- `evc_xml_parse_status` — `"parsed"`, `"partial"`, or `"failed"`.

### 5.7 EVH band — value distribution

EVH values are **encoded height-class codes** (source XML `<rdom>` 11–310).
The XML CLASSNAMES `<udom>` confirms the encoding: 101–199 = tree heights
1–99 m, 201–230 = shrub heights, 301–310 = herb heights. This encoding must
be reflected in the report.

Same structure as EVC:
- `evh_nodata_value`, `evh_nodata_cell_count`, `evh_nodata_acres`.
- `evh_valid_cell_count`, `evh_total_cells`.
- `evh_value_domain_from_xml` — `{min: 11, max: 310}` from XML `<rdom>`.
- `evh_value_encoding_note` — text from EVH XML CLASSNAMES `<udom>`.
- `evh_observed_min`, `evh_observed_max`.
- `evh_codes_outside_xml_domain`.
- `evh_value_counts` — `{evh_code, cell_count, square_meters, acres,
  valid_cell_fraction}`, sorted ascending.
- `evh_descriptive_statistics` — same NumPy stats as EVC, with
  `evh_statistics_interpretation`:
  `"These are descriptive statistics of encoded EVH height-class codes,
  not vegetation height values in metres. Do not interpret mean or standard
  deviation as tree height in metres. See evh_value_encoding_note for the
  class encoding."` All fields `null` if NumPy unavailable.
- `evh_xml_parse_status` — `"parsed"`, `"partial"`, or `"failed"`.

### 5.8 Mandatory sentinel fields

Present in both the JSON summary and the Markdown report:

```json
"inspection_status": "success" | "partial" | "failed",
"classification_performed": false,
"forest_land_determination_performed": false,
"crosswalk_applied": false,
"candidate_cover_types_produced": false,
"candidate_polygons_produced": false
```

### 5.9 Warnings list

`warnings` is a list of strings. Must include entries for:
- Any missing XML file.
- Any XML parse failure (partial or complete).
- Any band identification failure (not_found, ambiguous, duplicate).
- Any alignment mismatch.
- Any EVT, EVC, or EVH code observed outside the XML-declared domain range.
  Warn using the source-defined range, not a hard-coded threshold.
- Any EVC or EVH value absent from any parseable domain description (treated
  as unknown source value, not physically implausible).
- Any `cell_area_m2` / `cell_area_acres` unavailable due to CRS.
- The static no-classification statement (always present):
  `"This report is a pre-classification source inspection only. No candidate
  cover type, forest-land determination, crosswalk, polygon, or stand
  assignment has been made. Professional forestry and GIS review is required
  before any classification work begins."`
- The EVT label availability note (always present — see §5.5).

### 5.10 Markdown report content

The Markdown report (`inspect_lf2025_<job_id>_report.md`) must include all
of the following sections in human-readable form:

1. **Header** — product title, edition, publication date, DOI (per band,
   from XML).
2. **Inspection status** — `inspection_status` value and all sentinel fields.
3. **Band identification** — which band was found at which index; method.
4. **Raster geometry** — dimensions, CRS, transform, cell size, cell area
   (with unit safety note), bounding box.
5. **Alignment check summary** — pass/partial/fail with specifics.
6. **EVT code inventory table** — one row per observed code: code, cell
   count, acres (or "area unavailable"), valid-cell fraction, label (with a
   note that per-code labels are not in the local bundle).
7. **EVT label availability note** — verbatim from §5.5.
8. **EVC value summary** — domain from XML, encoding note, min/max,
   descriptive statistics with explicit interpretation caveat.
9. **EVH value summary** — domain from XML, encoding note, min/max,
   descriptive statistics with explicit interpretation caveat.
10. **NoData summary** — NoData values and counts for each band.
11. **Warnings** — all entries from the warnings list.
12. **Footer** — explicit no-classification statement; timestamp; source
    file references.

---

## 6. Internal helper vs. public tool boundary

`_inspect_landfire_v2_inputs(manifest: dict, manifest_path: Path) -> dict`
— internal helper.

- Accepts the already-parsed manifest dict and its validated `Path`.
- Opens the raster and XML files. Does not make network calls. Does not
  write files. Returns the full report dict.
- Returns `{"inspection_status": "failed", ...sentinel fields...}` (not an
  exception) for recoverable failures: missing GeoTIFF, unreadable raster,
  all XML files absent.
- Raises `ToolError` only for programming-level invariant violations that
  should never occur after the manifest has already been validated.

`inspect_landfire_v2_cover_type_inputs(collection_manifest_filename: str)`
— public `@mcp.tool()`.

- Validates filename pattern and path security (same posture as all existing
  LFPS v2 tools — see server.py lines 4110–4169 for the reference pattern).
- Reads and parses manifest; validates `api_version == "LFPS v2"`.
- Calls `_inspect_landfire_v2_inputs()`.
- If helper returns `inspection_status: "failed"`, returns that dict directly
  without writing any artifacts.
- Otherwise writes all three artifacts. If a write fails, returns a structured
  error dict — does not silently continue.
- Returns JSON summary dict plus artifact paths and `inspection_status`.

---

## 7. Files to change

| File | Change |
|---|---|
| `server.py` | Add `_inspect_landfire_v2_inputs()` helper and `inspect_landfire_v2_cover_type_inputs()` public tool after the last existing tool (line ~4789). |
| `tests/test_server.py` | Add `TestInspectLandfireV2Inputs` test class. |

No other files change. No new dependencies. `rasterio`, `numpy` (transitive
via rasterio/geopandas), `xml.etree.ElementTree` (stdlib), and `csv`
(stdlib) are sufficient.

---

## 8. Sub-tasks

---

### Sub-task A — Internal helper: raster read, XML parse, report assembly

**Intent:** Implement `_inspect_landfire_v2_inputs(manifest, manifest_path)`.
All raster-open, band-identification, array-read, statistics-compute,
XML-parse, alignment-check, and report-assembly logic lives here. No file
writes, no network calls.

**Expected outcomes:**
- Returns a complete dict containing all fields from §5.
- `inspection_status` is always present.
- All sentinel fields always present and always `false`.
- Band identification uses description matching only; fails cleanly if
  any required band is ambiguous or absent.
- EVC/EVH statistics carry the mandatory interpretation notes.
- EVT label unavailability is recorded, not treated as an error.
- EVC/EVH XML domains parsed from `<rdom>` and `<udom>` — not hard-coded.

**Todo list:**

1. **Manifest extraction.** Extract `geotiff_file`, `job_id`,
   `expected_metadata_xml_files` (EVT, EVC, EVH paths) from the manifest
   dict.

2. **Raster open.** Open with `rasterio.open()`. Read: `width`, `height`,
   `count` (band count), `crs`, `transform`, `descriptions`, `nodata` /
   `nodatavals`.

3. **Band identification.** For each of "EVT", "EVC", "EVH", search
   `src.descriptions` case-insensitively for a description containing that
   keyword. Track match count. If any keyword is matched by zero bands or
   more than one band, set `inspection_status: "failed"` and return
   immediately without reading arrays.

4. **CRS area safety check.** Determine whether the CRS supports a safe
   metre-based planar area calculation. For this prototype, EPSG:5070 is the
   confirmed safe case. Any other CRS sets `cell_area_m2 = null`,
   `cell_area_acres = null`, and adds the standard CRS-limitation warning.
   Compute cell area from the affine transform: `abs(transform.a) ×
   abs(transform.e)` — never hard-code 900 m².

5. **EVT array read.** Read EVT band as int16 NumPy array. Compute total
   cells, NoData cell count, valid-cell mask, valid-cell count, unique code
   counts with `numpy.unique()`.

6. **EVT XML parse.** Parse `LF2025_EVT_CONUS.xml` with
   `xml.etree.ElementTree`. Extract `<title>`, `<edition>`, `<pubdate>`,
   first doi.org `<onlink>`. From `<eainfo>/<detailed>/<attr>` where
   `<attrlabl>` == `"VALUE"`: extract `<attrdef>`, and check domain type
   (`<rdom>`, `<edom>`, or `<udom>`); extract `<rdommin>` / `<rdommax>`
   if `<rdom>`. Record that per-code labels are not present in this XML.
   Handle `ParseError` gracefully: record `"failed"` parse status and
   continue with `null` domain fields.

7. **EVT out-of-domain check.** Compare each observed code against the
   XML-declared `<rdom>` range and against −9999. Codes outside either
   bound go to `evt_codes_outside_xml_domain`.

8. **EVC array read and XML parse.** Same structure as EVT. Additionally
   extract the CLASSNAMES `<udom>` text for `evc_value_encoding_note`.
   Compute value counts. Compute descriptive statistics using NumPy over
   the valid-cell flat array; label them as statistics of encoded codes.

9. **EVH array read and XML parse.** Same as EVC. The CLASSNAMES `<udom>`
   for EVH contains the structured class encoding description; extract it
   for `evh_value_encoding_note`.

10. **Alignment checks.** Since all bands are in a single file, compare
    band-level metadata (descriptions, nodata, data type). Check that shared
    file properties (dimensions, transform, CRS) are self-consistent. Produce
    `dimensions_match`, `crs_match`, `transform_match`, `extent_match`,
    `resolution_match`. Compute `valid_data_overlap_cells`.

11. **Assemble report dict.** Collect all fields from §5. Append the static
    no-classification statement and the EVT label availability note to
    `warnings`. Set `inspection_status: "success"` if no hard failures, or
    `"partial"` if any XML parse failed or any domain check produced warnings.

12. **Return report dict.**

**Relevant context:**
- `src.descriptions` — tuple of band descriptions (0-indexed).
- `src.transform` — rasterio `Affine` object; `transform.a` = x cell size,
  `transform.e` = y cell size (negative for north-up rasters).
- `src.nodata` — shared NoData; `src.nodatavals` if per-band.
- `numpy.unique(arr, return_counts=True)` — efficient code counting.
- `xml.etree.ElementTree.parse()` — standard library; no dependency.

**Status:** [ ] pending

---

### Sub-task B — Public MCP tool wrapper and artifact writer

**Intent:** Implement `inspect_landfire_v2_cover_type_inputs` as the public
`@mcp.tool()`. Validates inputs, calls the helper, writes all three
artifacts, returns the structured response.

**Expected outcomes:**
- Registered via `@mcp.tool()`.
- Filename validation and path security match the posture of existing tools.
- Calls `_inspect_landfire_v2_inputs()`.
- Writes Markdown, JSON summary, and EVT inventory CSV.
- Never overwrites existing artifacts (raise `ToolError` if any destination
  exists).
- Returns `inspection_status` plus artifact paths plus all sentinel fields.

**Todo list:**

1. Validate `collection_manifest_filename` with `re.fullmatch()` against
   the LFPS v2 collection manifest pattern.
2. Resolve path inside `OUTPUT_FOLDER`; verify parent == `OUTPUT_FOLDER`.
3. Verify file exists and is ≤ `MAX_RESPONSE_BYTES`.
4. Read and parse manifest JSON; validate `api_version == "LFPS v2"`.
5. Extract `job_id` from manifest (needed for output filenames).
6. Compose three output paths using `job_id`. Check none exists; raise
   `ToolError` if any would be overwritten.
7. Call `_inspect_landfire_v2_inputs(manifest, manifest_path)`.
8. If helper returns `inspection_status: "failed"`, return it directly.
9. Write JSON summary: `json.dumps(report, indent=2)`.
10. Write EVT inventory CSV: iterate `report["evt_codes_observed"]`;
    write header row plus one data row per code; use `csv.writer`.
11. Write Markdown report: construct the Markdown document described in
    §5.10; write as UTF-8 text.
12. Return `{**report, "inspection_report_md": str(md_path),
    "inspection_report_json": str(json_path),
    "evt_inventory_csv": str(csv_path)}`.

**Relevant context:**
- Reference pattern: `collect_landfire_v2_sample_result`, lines 4110–4169.
- Output filename format: `inspect_lf2025_{job_id}_{artifact}.{ext}`.
  Keep total filename ≤ 80 characters.
- `job_id` is a UUID string; use first 8 characters if full UUID makes
  the filename too long on Windows. Full UUID is inside the JSON content.
- `csv.writer` is stdlib; no extra dependency.

**Status:** [ ] pending

---

### Sub-task C — Unit tests

**Intent:** Write tests covering the valid case, band-identification failures,
metadata-domain handling, no-physical-unit-claim enforcement, all three
artifact outputs, affine-based cell area, CRS-unsupported area, and unknown
EVC/EVH values absent from the metadata domain. Use synthetic fixtures only
for committed tests.

**Expected outcomes:**
- All committed tests pass on a fresh clone with no `project_data/` or
  `outputs/` content.
- No test uses or requires the actual Mescalero raster.
- All three artifact files are verified when the test writes to `tmp_path`.
- One optional skip-if-absent test exercises the actual Mescalero manifest.

**Required test list:**

| ID | Test | Verifies |
|---|---|---|
| C-1 | Valid synthetic raster and XMLs | All required fields present; `classification_performed == False`; `inspection_status == "success"`; all sentinel fields false |
| C-2 | Missing EVT XML | `inspection_status == "partial"`; `warnings` contains XML-missing entry; no exception |
| C-3 | EVT code outside XML-declared `<rdom>` | Code appears in `evt_codes_outside_xml_domain` with a warning; does not use hard-coded bounds |
| C-4 | Invalid filename | `ToolError` raised before any file access |
| C-5 | NoData-only EVT band | `evt_valid_cell_count == 0`; `evt_codes_observed` is empty list |
| C-6 | Ambiguous band descriptions (two bands match "EVT") | `inspection_status == "failed"`; no raster reads attempted |
| C-7 | Missing required band description ("EVH" absent from all bands) | `inspection_status == "failed"` |
| C-8 | EVC statistics carry interpretation note | `evc_statistics_interpretation` present and non-empty; mean/std are not labeled as percent cover |
| C-9 | EVH statistics carry interpretation note | `evh_statistics_interpretation` present; values not labeled as metres |
| C-10 | Non-metre CRS (e.g., EPSG:4326 synthetic raster) | `cell_area_m2 == null`; `cell_area_acres == null`; warning present |
| C-11 | EPSG:5070 affine-based cell area | `cell_area_m2` == abs(transform.a) × abs(transform.e); not hard-coded 900 |
| C-12 | Unknown EVC value absent from XML domain | Value appears in `evc_codes_outside_xml_domain`; warning present |
| C-13 | Unknown EVH value absent from XML domain | Value appears in `evh_codes_outside_xml_domain`; warning present |
| C-14 | All three artifact files written and have correct names | MD, JSON, CSV all exist in `tmp_path/outputs`; CSV has expected columns |
| C-15 | EVT label availability note always present | Note in `evt_label_availability_note` and in `warnings` |
| C-16 | Repeat call raises `ToolError` (no overwrite) | Second call on same manifest raises `ToolError` |
| C-opt | Actual Mescalero manifest (skip-if-absent) | `inspection_status != "failed"`; `evt_codes_observed` non-empty; three artifacts written; all sentinels false |

**Synthetic fixture guidance:**

- Create an EPSG:5070 three-band GeoTIFF using `rasterio.MemoryFile` (or
  `tmp_path`) with:
  - Band descriptions set to `LF2025_EVT_CONUS`, `LF2025_EVC_CONUS`,
    `LF2025_EVH_CONUS`.
  - Known pixel values including at least two EVT codes, one NoData cell,
    and one EVC/EVH value outside the XML `<rdom>`.
- Minimal synthetic XMLs:
  - EVT XML: include `<title>`, `<edition>`, `<pubdate>`, doi `<onlink>`,
    and a `<rdom>` VALUE domain with finite `rdommin`/`rdommax`. Include
    a CLASSNAMES `<udom>` referencing an external CSV (mirroring the actual
    file structure).
  - EVC XML: include `<rdom>` VALUE domain, CLASSNAMES `<udom>` text.
  - EVH XML: include `<rdom>` VALUE domain, CLASSNAMES `<udom>` encoding
    text.
- Synthetic collection manifest JSON pointing to the synthetic files, with
  `api_version: "LFPS v2"` and a synthetic `job_id`.

**Relevant context:**
- `rasterio.MemoryFile` + `rasterio.open(..., 'w', ...)` for in-memory
  raster creation.
- `rasterio.transform.from_bounds()` or `rasterio.transform.from_origin()`
  for constructing a valid EPSG:5070 affine transform.
- Pattern for conditional skip: see `tests/test_cover_scheme_models.py`
  lines 37–44.

**Status:** [ ] pending

---

## 9. Acceptance criteria

| # | Criterion | Evidence |
|---|---|---|
| 1 | All sentinel fields always false | Tests C-1 through C-16 and C-opt all verify |
| 2 | `inspection_status` always present and always one of success/partial/failed | All tests |
| 3 | Band identified by description, not position; fails hard on ambiguity | Tests C-6 and C-7 |
| 4 | Cell area derived from affine transform; not hard-coded 900 | Test C-11 |
| 5 | Cell area null for non-metre CRS | Test C-10 |
| 6 | EVC statistics carry encoded-class interpretation note; no percent-cover claim | Test C-8 |
| 7 | EVH statistics carry encoded-class interpretation note; no metres claim | Test C-9 |
| 8 | EVT label unavailability documented as known source limitation, not error | Test C-15 |
| 9 | Out-of-domain values warned using XML-declared range, not hard-coded thresholds | Tests C-3, C-12, C-13 |
| 10 | Missing XML produces partial/warned result, not crash | Test C-2 |
| 11 | All three artifacts written with correct names and columns | Test C-14 |
| 12 | No overwrite on repeat call | Test C-16 |
| 13 | All existing tests continue to pass | `pytest` clean run |
| 14 | Actual Mescalero raster runs without error (local only) | Test C-opt |

---

## 10. Risks and rollback

- **Risk:** EVT XML `<eainfo>` structure varies by LANDFIRE version or
  extraction method.
  **Mitigation:** XML parser records `"failed"` or `"partial"` parse status
  and continues with null domain fields. The actual XML structure has been
  read and verified for the VALUE attribute.

- **Risk:** NumPy not importable in the Bob environment.
  **Mitigation:** Wrap `import numpy` in a try/except inside the helper.
  If unavailable, set all descriptive statistics fields to `null` with a
  warning. Min, max, and value counts do not require NumPy.

- **Risk:** `job_id` UUID in output filename exceeds path length on Windows
  with deep OneDrive sync paths.
  **Mitigation:** Output filename uses full UUID in the stem; total is ≈78
  characters. If this becomes a problem in testing, use first 8 hex chars
  in the filename and record full UUID inside the content.

- **Risk:** EVC/EVH CLASSNAMES `<udom>` text varies across LANDFIRE updates.
  **Mitigation:** Text is recorded verbatim from the XML, never parsed or
  interpreted as code boundaries by the tool. The report consumer reads the
  raw text.

- **Rollback:** All additions are purely additive. No existing tool or test
  is touched. Removing the new helper and tool restores prior state exactly.

---

## 11. Status

| Sub-task | Status |
|---|---|
| A — Internal helper: raster read, XML parse, report assembly | [ ] pending |
| B — Public tool wrapper and artifact writer | [ ] pending |
| C — Unit tests | [ ] pending |
