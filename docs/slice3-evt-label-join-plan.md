# Slice 2b — LF2025 EVT Reference Join Implementation Plan

**Application:** Tribal Forest MapCP
**Status:** Implemented and tested.
**Authority:** `AGENTS.md`, `docs/project-specification.md`  
**Prerequisite:** Slice 2 complete. `inspect_landfire_v2_cover_type_inputs` exists and passes all C-1–C-15 tests.

---

## 1. Objective and scope

Download the LANDFIRE 2025 EVT Attribute Data Dictionary CSV once, cache it
locally, and join five human-readable label columns onto the EVT inventory CSV
and summary JSON produced by `inspect_landfire_v2_cover_type_inputs`.

**In scope:**
- One new internal helper: `_load_lf2025_evt_labels()` — downloads the ADD CSV,
  caches it, records provenance (URL, download date, SHA-256, row count).
- Enrich the `evt_codes_observed` list in the in-memory report with the five
  joined columns.
- Replace the five placeholder columns in the written EVT inventory CSV and the
  summary JSON.
- One new test module `tests/test_slice3_evt_labels.py` (four test cases).
- Update the `_EVT_LABEL_NOTE` constant to reflect that labels are now resolved.

**Out of scope (not in this slice):**
- No classification, crosswalk, or forest/nonforest output.
- No cover-scheme loading or mapping.
- No changes to the public tool signature or the `inspection_status` logic.

---

## 2. Existing behavior to preserve

- All 15 existing tests (C-1–C-15) must continue to pass without modification.
- `inspect_landfire_v2_cover_type_inputs` returns `inspection_status` values
  (`"complete"`, `"partial"`, `"failed"`) under the same conditions as before.
- If the ADD CSV is unavailable (network failure, bad checksum on retry), the
  tool still completes with `label_missing=true` for affected codes and a
  warning — it does not crash or change `inspection_status` to `"failed"`.
- No changes to output file naming.

---

## 3. Source

- **URL (fixed allowlist):**
  `https://landfire.gov/sites/default/files/CSV/LF2025/LF2025_EVT.csv`
- **Encoding:** `utf-8-sig` (BOM-safe UTF-8)
- **Key column:** `VALUE` (integer EVT code)
- **Columns to join:** `EVT_NAME`, `EVT_LF`, `EVT_PHYS`, `EVT_GP_N`, `SAF_SRM`
- **Data dictionary (reference only):**
  `https://landfire.gov/sites/default/files/DataDictionary/LF2025/LF2025_EVTADD.pdf`

---

## 4. New constant and cache path

```
LF2025_EVT_ADD_URL  =  "https://landfire.gov/sites/default/files/CSV/LF2025/LF2025_EVT.csv"
LF2025_EVT_ADD_CACHE_NAME  =  "lf2025_evt_add.csv"   # stored in project data folder
LF2025_EVT_ADD_MAX_BYTES  =  20_000_000               # 20 MB guard
LF2025_EVT_ADD_RETRY  =  2                            # attempts
LF2025_EVT_ADD_TIMEOUT  =  60.0                       # seconds
```

Cache location: `project_data/lf2025_evt_add.csv` (sibling of `cover_schemes/`).  
Provenance record (dict, not written to disk unless reused): URL, ISO-8601
download date (UTC), SHA-256 hex digest, row count, columns present.

---

## 5. Sub-tasks

### Sub-task A — Internal label-loader helper

**Intent:** Download and cache the ADD CSV; expose a function that returns a
`dict[int, dict]` mapping EVT code → `{EVT_NAME, EVT_LF, EVT_PHYS, EVT_GP_N, SAF_SRM}`.

**Expected outcomes:**
- On first call (no cache): downloads, validates checksum guard, writes cache,
  returns populated dict plus provenance metadata.
- On subsequent calls (cache present): reads cache, returns dict plus provenance
  metadata.
- On download failure after retries: returns empty dict and error string; does
  not raise an unhandled exception.
- Provenance dict records `url`, `download_date` (or `"cached"`),
  `sha256`, `row_count`, `contact_email_supplied: false` (no email needed for
  this public CSV).

**Todo list:**
1. Add constants `LF2025_EVT_ADD_URL`, `LF2025_EVT_ADD_CACHE_NAME`,
   `LF2025_EVT_ADD_MAX_BYTES`, `LF2025_EVT_ADD_RETRY`, `LF2025_EVT_ADD_TIMEOUT`
   near the other LANDFIRE constants in `server.py`.
2. Implement `_load_lf2025_evt_labels(cache_dir: Path) -> tuple[dict, dict, str]`
   returning `(label_map, provenance, error_msg)`.
   - Check for `cache_dir / LF2025_EVT_ADD_CACHE_NAME` first.
   - If absent: `httpx.Client(timeout=LF2025_EVT_ADD_TIMEOUT, follow_redirects=False)`,
     2 attempts with 1-second sleep, size guard `LF2025_EVT_ADD_MAX_BYTES`.
   - Compute SHA-256 of the raw bytes before decoding.
   - Decode with `utf-8-sig`; parse with `csv.DictReader`.
   - Build `label_map[int(row["VALUE"])] = {k: row.get(k, "") for k in LABEL_COLS}`.
   - Write cache file as-is (raw bytes).
   - Record provenance.
   - Return graceful error on any exception (empty map, provenance with
     `download_failed: true`, error string).
   - If cache exists: read, compute SHA-256 of cached bytes, parse, return with
     `provenance["source"] = "cache"`.

**Relevant context:**
- Existing HTTPS pattern: `_read_landfire_json()` (Line ~1440) — follow same
  `httpx.Client` / retry / size-guard idiom.
- Cache dir is `Path(project_data_dir)` (already referenced in `server.py`).

**Status:** `[x] done`

---

### Sub-task B — Enrich report and update CSV/JSON writers

**Intent:** Call `_load_lf2025_evt_labels()` inside `_inspect_landfire_v2_inputs()`,
join results onto `evt_codes_observed`, and write them into the CSV and the
summary JSON.

**Expected outcomes:**
- Each entry in `evt_codes_observed` gains five new keys:
  `evt_name`, `evt_lf`, `evt_phys`, `evt_gp_n`, `saf_srm`.
- `label_missing` is `false` when a code is found in the label map; `true` when
  the code is absent from the label map or the map is empty.
- A warning is added for every code where `label_missing=true` (e.g.,
  `"EVT label not found for code 7024 — label_missing=true"`).
- `_EVT_LABEL_NOTE` is updated to reflect that labels are resolved from the
  ADD CSV when available, and unavailable only when the download fails.
- EVT inventory CSV gains five new columns (after `label_missing`):
  `evt_name`, `evt_lf`, `evt_phys`, `evt_gp_n`, `saf_srm`.
- Summary JSON gains the five keys per code and an `evt_add_provenance` block
  at the band level.
- If the label map is empty (download failed), the five new columns are written
  as empty strings; `label_missing=true`; a single aggregate warning is added.
  The tool still returns `inspection_status="complete"` or `"partial"` as
  determined by pre-existing logic.

**Todo list:**
1. Determine and pass `cache_dir` (the `project_data/` folder path) to
   `_load_lf2025_evt_labels()` from inside `_inspect_landfire_v2_inputs()`.
2. Attach `evt_add_provenance` to `report["evt_band"]`.
3. For each entry in `evt_codes_observed`, look up the label map; set the five
   keys and update `label_missing`.
4. Emit per-code `label_missing=true` warnings (or one aggregate warning when
   the entire map is empty).
5. Update `_EVT_LABEL_NOTE` constant to current behavior.
6. Extend `csv.writer` header and rows to include the five new columns (keep
   existing column order intact; append new columns at the right).
7. Confirm `report["csv_artifact_created"]` and `report["evt_inventory_csv"]`
   logic are unchanged.

**Relevant context:**
- CSV writer: Lines 5885–5919 in `server.py`.
- `evt_codes_observed` built: Lines ~5280–5330.
- `label_missing` currently hard-coded `True` at Line 5313.

**Status:** `[x] done`

---

### Sub-task C — Tests

**Intent:** Four focused tests covering the join success path, an unknown code,
a missing/failed download, and checksum recording.

**Expected outcomes:**
All four tests pass. No existing test is modified.

**Todo list:**
1. Create `tests/test_slice3_evt_labels.py`.
2. **T-1 Join success:** Provide a synthetic ADD CSV (in-memory or temp file)
   with rows for all 17 known Mescalero EVT codes. Patch `_load_lf2025_evt_labels`
   to return this map. Run inspection via `inspect_landfire_v2_cover_type_inputs`.
   Assert `label_missing=false` for all 17 codes, all five label columns
   populated, and no per-code label warning.
3. **T-2 Unknown code:** Provide ADD CSV that deliberately omits one EVT code
   present in the synthetic raster. Assert `label_missing=true` for that code,
   a warning naming the code, and `label_missing=false` for codes that were
   found.
4. **T-3 Download failure:** Patch `_load_lf2025_evt_labels` to return empty
   map and an error string. Assert inspection still returns a non-`"failed"`
   status, `label_missing=true` for all codes, and the aggregate download-error
   warning is present. Confirm `inspection_status` is not downgraded to
   `"failed"`.
5. **T-4 Checksum recorded:** Patch the download path to succeed and confirm
   that `evt_add_provenance` in the report contains `sha256` (non-empty string),
   `row_count` (positive integer), `url`, and `download_date`.

**Relevant context:**
- Existing fixture helpers: `_make_minimal_evt_xml()`, `_make_synthetic_manifest()`,
  `_make_full_fixture()` in `tests/test_server.py` (Lines 1374–2040).
  Import or copy-minimally from these rather than duplicating.
- Mescalero 17 EVT codes: already observed in `outputs/inspect_lf2025_3b83d63b_evt_inventory.csv`.

**Status:** `[x] done`

---

## 6. Files changed

| File | Change |
|------|--------|
| `server.py` | Add constants, `_load_lf2025_evt_labels()`, enrich `evt_codes_observed`, update CSV writer and `_EVT_LABEL_NOTE` |
| `tests/test_slice3_evt_labels.py` | New file — four tests |
| `docs/slice3-evt-label-join-plan.md` | This file |

No other files change. `project_data/lf2025_evt_add.csv` is written at runtime (gitignored with `outputs/`).

---

## 7. Acceptance criteria

1. All 17 Mescalero EVT codes resolved with `label_missing=false` when the ADD
   CSV is reachable (demonstrated via T-1 or a local integration run).
2. `EVT_NAME`, `EVT_LF`, `EVT_PHYS`, `EVT_GP_N`, `SAF_SRM` present in the
   written EVT inventory CSV with correct values.
3. `evt_add_provenance` block in summary JSON contains `sha256`, `row_count`,
   `url`, `download_date`.
4. Unknown code → `label_missing=true` plus named warning (T-2 passes).
5. Download failure → tool completes, status not `"failed"`, aggregate warning
   present (T-3 passes).
6. All pre-existing C-1–C-15 tests continue to pass.
7. No credential, email address, or sensitive data written to any artifact.

---

## 8. Risks and constraints

- **Column name stability:** The ADD CSV column names (`VALUE`, `EVT_NAME`,
  `EVT_LF`, `EVT_PHYS`, `EVT_GP_N`, `SAF_SRM`) are taken from the approved
  source. If LANDFIRE changes column names without notice, the join silently
  produces empty labels and `label_missing=true` for all codes — acceptable
  graceful degradation.
- **CSV size:** LF2025 EVT ADD CSV is ~11,000 rows × ~20 columns. The 20 MB
  guard is generous; actual file is well under 5 MB.
- **Cache invalidation:** No TTL logic. Cached file is reused indefinitely until
  manually deleted. This is acceptable for a prototype; a future slice can add
  expiry.
- **Backlog B-2 interaction:** The `_EVT_LABEL_NOTE` update in Sub-task B
  touches a string that B-2 proposes to move into a `notes` field. This slice
  updates the constant only; the field-move remains deferred.
- **No breaking changes:** Existing CSV column order is preserved; new columns
  append to the right. Downstream consumers reading by name are unaffected;
  consumers reading by position gain five new trailing columns.

---

## 9. Rollback

Revert `server.py` (constants + two code blocks) and delete
`tests/test_slice3_evt_labels.py`. No schema migration is needed because the
cache file is regenerated on first use.
