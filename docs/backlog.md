# Tribal Forest MapCP — Deferred Work Backlog

Items in this file are explicitly deferred. They must not be implemented
without a separate approved plan and implementation slice.

---

## B-1 — Fold `inspect_landfire_v2_cover_type_inputs` into `inspect_mapping_inputs`

**Deferred from:** Slice 2 approval session.

Consolidate the LF2025 input inspection logic into `inspect_mapping_inputs`
as an internal helper, so a single public outcome tool handles all input
validation (boundary, NAIP, and vegetation rasters). The public
`inspect_landfire_v2_cover_type_inputs` tool would become internal-only.

**Blocked on:** Finalising the `inspect_mapping_inputs` input contract and
deciding whether the seven public tools map one-to-one with the workflow
steps or whether input inspection is a single composite tool.

**Risk:** Changing the `inspect_mapping_inputs` signature is a breaking change
to existing tests and to any client that already calls it.

---

## B-2 — Move fixed warning notes into a `notes` or `limitations` field

**Deferred from:** Slice 2 approval session.

The no-classification statement and the EVT label availability note currently
appear in the `warnings` list on every successful run, not only when a
problem occurs. They are informational notes rather than diagnostic warnings.

Proposed change: add a `notes` or `limitations` field to the inspection
report and tool response, and move the two static strings there, leaving
`warnings` for genuinely variable diagnostic messages only.

**Blocked on:** Agreement on the output schema change and whether downstream
consumers (tests, ArcGIS Pro) need to be updated.

---

## B-3 — Split `server.py` into modules

**Deferred from:** Slice 2 approval session.

`server.py` has grown to approximately 5,900 lines. Split it into
topic-focused modules (e.g., `boundary_tools.py`, `naip_tools.py`,
`landfire_tools.py`, `inspection_tools.py`, `cover_scheme_models.py`)
with a thin `server.py` that imports and registers all tools.

**Blocked on:** Agreeing on the module boundary design and confirming that
the MCP registration pattern works with imported tool functions.

**Risk:** Import-order or circular-dependency issues during module split;
test patches that reference `server.OUTPUT_FOLDER` or similar globals must
be updated.

---

## B-4 — Document and verify the Mescalero optional test skip condition

**Deferred from:** Slice 2 approval session.

The test `test_copt_mescalero_manifest_runs_without_error` in
`tests/test_server.py` is decorated with `@pytest.mark.skipif` and runs
only when the local LFPS v2 collection manifest is present in `outputs/`.

**Work required:**
1. Confirm the exact skip condition: the test uses `_find_mescalero_manifest()`
   which globs `outputs/lfps_v2_collection_*.json` and checks that
   `api_version == "LFPS v2"` and `geotiff_file` is populated.
2. Verify the skip fires correctly on a fresh clone (no `outputs/` content).
3. Document the skip condition in `tests/test_server.py` with a comment
   above the `@pytest.mark.skipif` decorator and record the expected
   skip behavior in `docs/project-specification.md` §14.
4. Add a CI-friendly note: the optional test is expected to be skipped in
   automated pipelines and only runs locally with the actual Mescalero data.

# Backlog

Deferred items. Each needs an approved plan before implementation.

1. Fold `inspect_landfire_v2_cover_type_inputs` into `inspect_mapping_inputs`
   as an internal helper, so the agent sees one goal-oriented inspection tool.
2. Move fixed notes (EVT label availability, no-classification statement)
   out of `warnings` into a `notes` or `limitations` field, so warnings mean
   real problems.
3. Split `server.py` into modules (boundary, NAIP, LANDFIRE, inspection,
   export) without changing tool behavior.
4. Confirm whether the real Mescalero test is skipped when local data is
   absent, and document the skip condition.
5. Expand `_METRE_EPSG_SAFE` beyond EPSG:5070 only under an approved change.
