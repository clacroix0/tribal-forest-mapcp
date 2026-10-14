# Boundary preflight/preparation slice — 2026-10-13

Use the ZIP copies as a matched pair. No existing sample, classification,
raw-patch or generalization files need to be replaced.

## Placement

- boundary_mapping_preflight.py beside server.py.
- tests/test_boundary_mapping_preflight.py inside tests/.
- Paste server_boundary_preflight_wrapper.txt into server.py at top level,
  after existing tool wrappers and before a startup block, if present.
  Add it once; do not replace server.py.

## Scope and limits

Generic boundary filename and project title, not hardcoded Mescalero geometry.
Valid Polygon/MultiPolygon GeoJSON FeatureCollections; nonoverlapping multi-feature
boundaries are supported. Overlaps and invalid geometry fail without repair.
Inputs must remain directly inside outputs; no arbitrary URLs or filesystem paths.
Version 1 is bounded to the lower-48 bounding extent, EPSG:5070, and the existing
LF2025 EVT/EVC/EVH CONUS product profile. It is not universal geographic support.
It does not consume a cover scheme or crosswalk, so geometry/preparation is
independent of local cover-type definitions.

The product/API profile is based on the previously inspected sample workflow;
it is not reverified online by this operation. Preparation writes files but makes
no HTTP calls, sends no email, downloads nothing, and submits no job.

## Test first

From the correct repository folder:

    .\.venv\Scripts\python.exe -m pytest tests/test_boundary_mapping_preflight.py -q -rs
    .\.venv\Scripts\python.exe -m pytest tests -q -rs

Thirty synthetic cases pass in the sandbox. Windows may skip the symlink test.
The full user repository suite and actual boundary were not run in the sandbox.

## Prepare the selected boundary

    .\.venv\Scripts\python.exe .\boundary_mapping_preflight.py mescalero_apache_lar_20261002T183410878068Z.geojson --project-name "Mescalero full-boundary candidate mapping"

Any other supported public project can pass its own controlled filename and title.
The input GeoJSON is hashed before/after processing and preserved.

## MCP input after wrapper addition/server restart

{
  "request": {
    "boundary_filename": "mescalero_apache_lar_20261002T183410878068Z.geojson",
    "project_name": "Mescalero full-boundary candidate mapping",
    "product_profile": "lf2025_evt_evc_evh_conus"
  }
}

Tool: prepare_full_boundary_mapping_request
Actual MCP registration/host execution must still be tested.

## Result

Success is prepared_review_required, request_prepared true, execution_ready false,
job_submitted false, rasters_downloaded false, classification_performed false.
It writes a new boundaryprep_* folder with:

- boundary_request.json
- boundary_preflight.json
- REVIEW_BEFORE_SUBMISSION.txt

Estimates use the projected geographic download rectangle, with documented
planning padding, not a known service grid origin. Polygon-area-equivalent
cell counts are not exact raster counts. Raw array scenarios exclude GDAL,
geometry, copies, ZIP compression, and other peak-memory/disk overhead.
Local free disk is measured, but total storage requirements are not verified.

## Stop before submission

Do not feed this document to submit_landfire_v2_sample_job. Do not rename or edit
it to impersonate a sample request. Existing sample prepare/submit/collection
limits are NOT removed. The next approved slice must verify current service
contract/limits and implement a boundary-aware acquisition adapter.

After acquisition, additional stages must inspect all source codes, review
crosswalk gaps, mask/clip the actual polygon, account for inside-boundary missing
data separately from outside-boundary cells, and support full-area polygon
processing and generalization. No claim of full-reservation mapping is made by
this preparation result.

## Review evidence

Keep the proposal and estimates with the reviewed boundary and sample results.
Public-boundary checks do not establish land ownership/trust/legal authority.
The recorded sandbox evidence is synthetic; real boundary, ArcGIS, live MCP,
watsonx, actual service limits, and full-area runtime remain unverified.
