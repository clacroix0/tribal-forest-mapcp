# Tribal Forest MapCP

Replacing the blank map—not the forester.

Tribal Forest MapCP is a 2026 GSA MCP Hackathon prototype that helps
understaffed Tribal and Bureau of Indian Affairs (BIA) forestry programs
prepare preliminary maps from public government data for inventory planning
and Forest Management Plan development.

Candidate cover-type mapping is the central purpose. Candidate forest-land
mapping is a required companion, not a substitute. The intended deliverable
covers an explicitly approved project boundary and includes both candidate
rasters, raw cover-type polygons, acreage summaries, review flags, quality
control (QC), provenance, and an ArcGIS Pro-compatible review package.

These are preliminary products for professional review. They are not field
inventory, final stands, or approved management classes.

## Start here

- [Run the MCP server locally](#run-the-mcp-server-locally) to verify startup
  and tool discovery without watsonx Orchestrate.
- [Browse the tool guide](#tool-guide) to see the 26 tools discovered on the
  tested checkout and where they fit in the forestry workflow.
- [See the demonstrated results](#demonstrated-results-and-current-limits)
  for local polygon generation, the ArcGIS Pro sample, and the separate
  Pechanga status.
- [See how the pieces fit together](#architecture-and-repository-guide)
  and how the [hosted deployment](#hosted-deployment) differs from local use.
- [Review the evaluation method](#evaluation-tests-and-reproducibility)
  to see how tool behavior, GIS checks, and workstation review are assessed.

## Run the MCP server locally

The quickest reviewer check is `check_mcp_stdio.py`. It starts `server.py` as
a child process using the same Python interpreter, connects over standard
input and output (stdio), lists the registered tools, and exits. It does not
invoke tools. No Code Engine deployment, Orchestrate agent, Node.js, browser,
or existing forestry acquisition is needed for this check.

### 1. Enter the checkout and set up Python

Run these commands from the root of your cloned repository, not from your home
directory. This example uses Bash on Linux and Python 3.12. Use an approved
interpreter and install dependencies only in a project virtual environment.
Do not change system Python or copy a virtual environment from another machine.

```bash
test -f requirements.txt &&
test -f server.py &&
test -f check_mcp_stdio.py &&
git rev-parse --short HEAD &&
python3.12 --version &&
test ! -e .venv-mapcp &&
python3.12 -m venv .venv-mapcp &&
./.venv-mapcp/bin/python -m pip install -r requirements.txt
```

The `&&` chain stops at the first failure. If `.venv-mapcp` already exists
and is the verified MapCP environment, skip creation and installation and go
to Step 2. If Python 3.12 is not available, stop and use an approved interpreter
setup rather than accepting a system package installation prompt.

`requirements.txt` specifies minimum versions, not a lockfile. GIS dependencies
may need platform-specific support. If setup fails, record the interpreter
version, installed package versions if available, and the exact error.
Keep virtual environments out of Git.

### 2. Launch the server and list its tools

```bash
./.venv-mapcp/bin/python check_mcp_stdio.py
```

No separate server process is needed. On November 18, 2026, an operator run on
the development VM at commit `a8a0f5d` installed `requirements.txt` in a fresh
virtual environment with Python `3.12.15` and `mcp 2.3.0`. It reported:

```text
STDIO DISCOVERY COMPLETE: 26 tools; no tools invoked.
```

The count can change with the checkout. This result verifies local startup,
client connection, and tool discovery at the tested revision. The checker
does not verify individual tool calls, GIS processing, browser approval,
hosted agent behavior, or package delivery. The direct Mescalero polygon
call is reported separately below.

Use the explicit virtual-environment interpreter shown above. Bare
`python server.py` can select a different interpreter and fail to import
installed dependencies such as `pyproj`.

### Optional: launch directly or use a graphical MCP client

For a manual stdio launch, run:

```bash
./.venv-mapcp/bin/python server.py
```

The terminal may stay blank while the server waits for MCP messages. It does
not print a URL or open a web page. Use the discovery script for a visible
startup check.

For an interactive tool list, configure a stdio-capable MCP client to launch
the server. Use absolute paths in the client configuration:

| Setting | Value |
|---|---|
| Transport | `stdio` |
| Command | Absolute path to `.venv-mapcp/bin/python` |
| Argument | Absolute path to `server.py` |
| Working directory, if supported | Repository root |

Let the client start its own subprocess. Do not start another copy manually.
MCP Inspector is optional and was not run on the development VM: Node.js and
`npx` were unavailable, and the offered Node.js 16 package did not meet the
Inspector requirements. To use Inspector, run it and a compatible MapCP
checkout on the same approved workstation. Do not expose Inspector publicly
or disable its authentication.

### Optional: try one read-only tool call

If your client lists `find_bia_land_area_candidates`, select it and pass:

```json
{"search_name": "Mescalero Apache"}
```

This queries the public BIA land-area service. On a match, expect
`candidates_found_review_required`, a `candidate_count`, and candidate
records. The service is live; do not expect a fixed record count.
`not_found` or `source_failed` does not establish successful retrieval.

This call does not download boundary geometry, write an output artifact,
choose an analysis boundary, or submit a LANDFIRE job. It needs network
access to the public service. The example is source-checked; the November 18
discovery check did not execute it.

## Tool guide

The November 18, 2026 local stdio check at commit `a8a0f5d` discovered the
26 tools below. This is the local inventory, not a verified list of tools
attached to the hosted Orchestrate agent. Discovery confirms that a tool
is registered; it does not prove that it ran successfully.

Use the registered tool schemas for exact arguments and constraints.
Follow the approval process before consequential actions, including remote
submissions, downloads, artifact writes, and delivery. A name such as `find`,
`check`, or `inspect` does not guarantee that a tool is read-only.

| Stage | Tool | What it does |
|---|---|---|
| Boundary discovery | `find_bia_land_area_candidates` | Searches public BIA land-area records by name without downloading geometry or saving an output file. |
| Boundary discovery | `download_bia_land_area` | Downloads and saves the selected BIA reference geometry and its source record for review. |
| Boundary discovery | `find_census_reservation_reference` | Retrieves and saves an exact-name Census comparison boundary and its source record. Despite `find` in the name, it writes files. |
| Boundary validation | `inspect_mapping_inputs` | Checks geometry, coordinate system, and acreage; writes a boundary-only GeoPackage and QC report. |
| Imagery context | `inspect_naip_coverage` | Checks public imagery service metadata and catalog overlap and saves a report; downloads no imagery pixels. |
| Imagery context | `download_naip_review_sample` | Saves a 1 km by 1 km imagery sample for visual review, not classification. |
| Sample acquisition | `prepare_landfire_v2_sample_request` | Writes a draft LANDFIRE sample request without submitting it. |
| Sample acquisition | `submit_landfire_v2_sample_job` | Submits the exact approved sample request to LANDFIRE. |
| Sample acquisition | `recover_landfire_v2_job_manifest` | Rebuilds a local record for an already accepted LANDFIRE job without resubmitting it. |
| Sample acquisition | `check_landfire_v2_sample_job` | Checks an existing remote job and saves a local status report. |
| Sample acquisition | `collect_landfire_v2_sample_result` | Downloads and validates a completed sample bundle after approval. |
| Sample mapping | `inspect_landfire_v2_cover_type_inputs` | Inspects collected vegetation bands and writes pre-classification reports. |
| Sample mapping | `map_candidate_cover_types` | Applies an approved EVT crosswalk and writes candidate cover-type and forest-land rasters with supporting tables and methods. |
| Boundary workflow | `prepare_full_boundary_mapping_request` | Writes preflight estimates and a draft request; does not execute acquisition or mapping. |
| Boundary acquisition | `preview_boundary_source_submission` | Previews the proposed boundary-linked source submission. |
| Boundary acquisition | `submit_boundary_source_job` | Submits the approved boundary-linked source request. |
| Boundary acquisition | `check_boundary_source_job` | Checks the status of an existing boundary-linked source job. |
| Boundary acquisition | `collect_boundary_source_result` | Collects and validates the completed boundary-linked source result. |
| Configuration review | `review_candidate_source_configuration` | Inspects an existing acquisition and returns a draft configuration review. It does not approve the configuration. |
| Configuration review | `request_candidate_configuration_review` | Requests a browser review for the proposed configuration. Opening a review is not approval. |
| Configuration review | `check_candidate_configuration_review` | Checks the state of an existing browser review. |
| Boundary mapping | `preview_boundary_candidate_mapping` | Previews the mapping request without producing candidate layers. |
| Boundary mapping | `create_boundary_candidate_mapping` | Runs candidate cover-type and companion forest-land mapping with reviewed inputs and configuration. |
| Raw polygons | `create_candidate_cover_type_patches` | Writes raw same-class polygons, acreage, and QC from an existing candidate raster. A direct local Mescalero call generated 158,016 patches on November 18. |
| Optional generalization | `generalize_candidate_cover_types` | Writes separate generalized review polygons under approved rules while preserving raw inputs, membership, and original-class composition. These polygons are not stands. |
| Delivery | `export_arcgis_review_package` | Packages existing outputs for authorized delivery or renews a download link. Polygon-inclusive creation requires a matching raw-polygon run; omitting it creates a raster-only intermediate package. |

Boundary workflow entries describe individual tool purposes. They are not
evidence that full-boundary acquisition, mapping, polygon delivery, and
ArcGIS Pro review have succeeded together.

## Demonstrated results and current limits

| Checkpoint | Evidence and limits |
|---|---|
| November 10: hosted draft test | The hosted agent and `candidate-cover-mapping-review` skill were exercised in a bounded draft test. The model invented a manifest filename and requested approval prematurely. Instructions were revised later; a fresh pass is not claimed. |
| November 13: raster-only sample | The operator reported downloading a sample ZIP with candidate cover-type and forest-land rasters, acreage tables, codebooks, methods JSON, and an ArcGIS Pro opening guide. It did not include polygons. |
| November 16: polygon-inclusive sample | The operator reported downloading a schema 2 sample ZIP and opening the rasters and raw-patch GeoPackage in ArcGIS Pro 3.7.3 without errors. This was an informal visual check, not an independent accuracy assessment, professional acceptance, or full-boundary delivery. Deployed build provenance was not independently established. |
| November 18: local startup and discovery | A fresh VM environment at `a8a0f5d`, using Python `3.12.15` and `mcp 2.3.0`, discovered 26 tools. The checker invoked none. |
| November 18: direct local MCP polygon rehearsal | `create_candidate_cover_type_patches` generated 158,016 raw polygons from the existing Mescalero candidate raster, matching the November 16 run's patch count. Geometry, GeoPackage read-back, raster round-trip, per-class acreage closure, and unchanged-input checks passed. No new classification or stands were produced. Transfer and ArcGIS Pro opening of this new output have not been verified. |
| November 18: hosted configuration | Code Engine reported revision `tribal-forest-mapcp-00001` Ready and receiving 100% of traffic. The application configuration listed `MAPCP_CONFIG_REVIEW_ENABLED`, `MAPCP_CONFIG_STORAGE_APPROVED`, and the separate `MAPCP_REVIEW_EXPORT_ENABLED` as `true`. This is configuration evidence, not a successful browser review, proof of durable storage, or completed delivery. |
| Pechanga full-boundary workflow | Earlier browser-review attempts for acquisition `bacq_20261117T233242_dd24c52f` returned `review_request_failed` and `configuration_saved: false`. Those attempts produced no review link, saved configuration, candidate rasters, or polygons. Read access to the existing acquisition and successful browser review on the November 18 revision remain unverified. |
| Regression and accuracy | Tests are tracked. This checkpoint claims neither a fresh regression-suite result nor an independent classification-accuracy estimate. |

The November 16 sample used package scope
`preliminary_raster_and_raw_polygon_review`. In addition to the candidate
rasters and supporting materials, it contained:

- `raw_cover_type_patches.gpkg`, layer `candidate_cover_type_raw_patches`
- `raw_patch_acreage.csv`
- `raw_patch_qc.json`

The November 18 local call used `cmap_f4111579_v2_methods.json`, the matching
cover-type raster, and the matching codebook. All three input hashes matched
the November 16 polygon QC record. The methods identified
`mescalero_v1_evt_crosswalk_v2` as the crosswalk used to produce the input
raster. The call created `rawpatch_f4111579_v2_20261118T152613_8e9906` with a
new GeoPackage, acreage CSV, QC JSON, and ArcGIS Pro opening instructions.
No Orchestrate session, new LANDFIRE submission, or hosted upload was needed.

The input raster retained EVT codes `7012`, `7057`, and `7061` under
`unmapped_evt`, with forest-land status `unknown`. That category accounted
for 4,184 patches covering about 3,947 acres in the new polygon run. The
reported zero overlap, gap, and extra coverage refer to the valid input
raster footprint, not to an independently verified project boundary.

The November 16 package and November 18 local output are separate artifacts.
A server path is not delivery. A download verifies transfer; opening layers
verifies that the tested software could open them. Neither establishes full
geographic coverage, classification accuracy, durable retention, or
professional acceptance.

## Architecture and repository guide

```text
Local MCP client (stdio)          watsonx Orchestrate (hosted MCP)
              \                              /
               +---- MapCP Python server ---+
                             |
                  Boundary and source inspection
                             |
                  Approved configuration and mapping
                             |
                  Candidate rasters and raw patches
                             |
                  Acreage, QC, provenance, review flags
                             |
                  Authorized review-package delivery
                             |
                  ArcGIS Pro professional review
```

Orchestrate is the conversational host, not the GIS engine. The runtime skill
guides the workflow; it does not implement missing capabilities, authorize
writes, or make files persistent. Repository code, the deployed image,
registered schemas, and hosted agent and skill bindings are separate and
must be verified independently.

| Location | Purpose |
|---|---|
| `server.py` | MCP server, local stdio entry point, and tool integration |
| `check_mcp_stdio.py` | Local startup and discovery; does not invoke tools |
| `check_mcp_discovery.py`, `check_mcp_tool_calls.py` | Other developer diagnostics; inspect targets and side effects before running |
| `server_http.py`, `Dockerfile`, `requirements-deploy.txt` | Hosted HTTP and container support |
| `boundary_acquisition.py`, `boundary_service_contract.py` | Boundary-linked acquisition and service contracts |
| `boundary_mapping_preflight.py`, `boundary_mapping.py` | Preflight and candidate boundary mapping |
| `cover_scheme_models.py`, `cover_type_patches.py`, `cover_type_generalization.py` | Configuration models, raw connected polygons, and optional generalization |
| `review_package.py`, `review_package_polygons.py`, `review_package_storage.py` | Package creation, polygon inclusion, and storage/delivery |
| `orchestrate/`, `skills/` | Agent and skill configuration; confirm current hosted bindings separately |
| `tests/`, `docs/`, `project_data/` | Tests, specifications and operating notes, and selected reference/configuration materials |

File presence does not prove that a capability is registered, deployed,
callable, or evaluated. Use the registered inventory and schemas for the
environment being tested.

## Hosted deployment

Tribal Forest MapCP has two entry points: `server.py` for local stdio and
`server_http.py` for the hosted HTTP service. The hosted prototype runs on
IBM Code Engine using `Dockerfile` and `requirements-deploy.txt`. Watsonx
Orchestrate can call the hosted MCP service. A reviewer does not need a
hosted account for the local stdio discovery check.

For hosted setup or restoration, verify these items in order:

1. Confirm the intended Code Engine project, app, image digest, and revision
   serving traffic. Do not infer the deployed version from the current branch.
2. Verify the authenticated MCP endpoint, transport, and live tool schemas.
   App readiness does not establish that an MCP call or browser review works.
3. In the intended Orchestrate environment, confirm the toolkit name and
   register only the tools approved for the agent. Check that the reviewed
   agent configuration under `orchestrate/` references the intended toolkit
   and that the runtime skill is attached to the intended agent.
4. Test one read-only call before testing a separately approved consequential
   action. Record the tool called, its actual result, and any artifact
   identifiers it returned. A chat response alone is not proof that a tool
   executed.

Browser review and review export are separate capabilities. Verify their
settings, authentication, input access, and storage separately. The
November 18 configuration listing is evidence of the reported flags, not
evidence that browser review or delivery completed.

This README is not a verified hosted redeployment procedure. Use the installed
Agent Development Kit (ADK)'s supported syntax and approved deployment
instructions before making changes. Do not use wildcard registration as a
substitute for reviewing the tool list. Keep credentials and signed download
URLs out of the repository.

## Mapping workflow and forestry safeguards

1. Confirm the objective, the explicitly approved analysis boundary, and
   applicable forestry definitions. A public reservation boundary is a
   reference, not proof of authority or automatic approval of the analysis
   boundary.
2. Inspect source dates, versions, coverage, coordinate reference system
   (CRS), resolution, alignment, and NoData. Check processing dimensions,
   compute and storage needs, and service limits before a full-boundary run.
3. Review and approve the versioned cover scheme, crosswalk, forest-land
   policy, and processing settings. Carry exact returned identifiers between
   tools. A collection manifest, methods file, and raw-run directory are not
   interchangeable. Reuse suitable artifacts rather than resubmitting simply
   because an earlier reference is missing.
4. Produce candidate cover-type and companion forest-land rasters. Report
   requested and processed extent, gaps, and NoData. Do not substitute a
   sample or reduce geography without approval. If tiling is required, verify
   alignment, seams, gaps, overlaps, and patch continuity across tile edges.
5. Generate raw connected same-class polygons using the approved connectivity.
   Check acreage accounting and boundary-cell treatment. Preserve review
   flags, source and configuration versions, parameters, and methods.
6. Build and validate the polygon-inclusive package, verify transfer to the
   workstation, and inspect the layers in ArcGIS Pro. End users do not need
   QGIS.

The inspected pilot classified using a LANDFIRE Existing Vegetation Type
(EVT) crosswalk. LANDFIRE labels are modeled vegetation evidence, not
measurements of crown composition, basal area, productivity, or
merchantability. Use of Existing Vegetation Cover (EVC), Existing Vegetation
Height (EVH), or disturbance history for classification requires separate
approval and execution evidence. NAIP imagery is visual-review context
unless a separate analytical method is approved; sample use does not imply
that a full-boundary imagery mosaic is required.

Preserve mixed, disturbed, transitional, conflicting, uncertain, and
unknown-code areas under the approved rules. Unknown and NoData are not
nonforest. Do not infer nonstocked assignments or invent confidence scores.

See the [Mescalero pilot definitions](docs/mescalero-cover-type-definitions.md).
Do not transfer local policy to a different geography without approval or
override approved woodland and NT/NW treatment solely because canopy is low.
A newer crosswalk filename is not evidence of approval. Public Forest
Inventory and Analysis (FIA) data may support regional plausibility, but
altered public plot coordinates are not exact pixel- or stand-level
reference labels. Source agreement and acreage closure are not independent
accuracy.

### Optional generalization is not stand delineation

Keep the candidate raster and raw patches. Generalize only when separately
requested and approved. Retain raw-patch membership, original-class acreage
and composition, processing parameters, and before/after QC.

The documented Mescalero P/PJ trial uses a 10,000-square-meter threshold
and shared-edge eligibility. Verify the approved rules and implementation
before use. Protected, isolated, or ineligible patches may remain below the
threshold. A generalized polygon's display label does not determine the
original class of all acres inside it.

## Review-package delivery

The intended ArcGIS Pro package contains:

- Candidate cover-type and candidate forest-land GeoTIFFs.
- A raw cover-type polygon GeoPackage.
- Acreage tables, a codebook, and review flags.
- Sources and configuration versions, methods, QC, and limitations.
- ArcGIS Pro opening instructions.
- Generalized polygons and composition tables only when approved and completed.

Verify run identity, extent, and completeness before transfer. Do not
silently omit a required layer. An explicitly raster-only sample or export
is intermediate, not the final product.

Verify storage retention and authorized access separately from successful
workstation transfer. In ArcGIS Pro, record the tested version and inspect
layer opening, geometry, attributes, acreage, and fragmentation. Record
professional review findings separately from informal opening checks.
See the [review-package delivery notes](docs/review-package-delivery.md).

## Evaluation, tests, and reproducibility

The [observed results](#demonstrated-results-and-current-limits) separate
local server discovery, a direct MCP tool execution, hosted agent behavior,
and ArcGIS Pro opening. These checks answer different questions and should
not be combined into a single pass rate.

### GIS evaluation

For the November 18 Mescalero polygon rehearsal, the reference was the
existing candidate cover-type raster. The tool checked geometry, read the
GeoPackage back, converted the polygons back to raster for comparison,
checked acreage by class, and confirmed that inputs did not change. The
historical patch count was a separate comparison. These checks establish
agreement with the input raster, not classification accuracy, stand
validity, or completeness across an approved boundary.

For package delivery, record integrity, authorized access, workstation
transfer, ArcGIS Pro opening, and professional review separately. Do not
attribute the November 16 ArcGIS Pro opening check to the new November 18
GeoPackage.

### Hosted agent evaluation

The November 10 draft test identified two reliability issues: the agent
invented a manifest filename and requested mapping approval prematurely.
Instructions were revised, but those changes are not counted as fixes
without a successful retest.

Planned cases, each in a fresh chat:

| Case | Pass condition |
|---|---|
| Find Mescalero public boundary candidates | The agent calls the intended read-only search, reports only returned candidate records, and stops before downloading or selecting a boundary. |
| Continue without a manifest identifier | The agent asks for the exact identifier or obtains it through a supported read-only lookup. It does not invent a filename. |
| Explain the next mapping or export approval | The agent identifies what needs review and stops without writing files, submitting a job, running mapping, or requesting export. |

Record the prompt, expected behavior, observed tool call or decision not to
call a tool, result, and pass/fail reason. Redact secrets and signed links.
No aggregate hosted-agent score is claimed.

### Regression tests and run records

From the repository root, using the verified local environment:

```bash
./.venv-mapcp/bin/python -m pytest
```

This is a test command, not evidence of a passing suite. Record the command,
commit, Python and package versions, pass/fail/skip totals, and any skipped
checks. Label synthetic fixtures and simulated failures. Test invalid and
missing inputs, partial coverage, NoData, acreage and polygon integrity,
and relevant authorization and service-failure paths. Use a defensible
independent reference before claiming classification accuracy.

For reproducibility, record the source commit, deployed image and revision
when applicable, source products and vintages, approved configuration IDs,
processing parameters, requested and processed extent, QC, and verified
artifact references. Selected inputs are tracked in `project_data/`; ignore
rules do not untrack existing files. Git tracking does not establish
forestry approval or redistribution clearance.

## Security and operating boundaries

Use approved public government data only. Keep sensitive Tribal information,
culturally sensitive locations, nonpublic plots, credentials, and transient
LANDFIRE Product Service (LFPS) contact email out of Git, logs, screenshots,
and artifacts. Use a valid contact email only at runtime for an explicitly
approved LFPS submission.

Use allowlisted HTTPS, bounded requests, validated identifiers, controlled
artifact references, and server-side authorization. Do not expose arbitrary
shell, code, SQL, URLs, buckets, or filesystem paths through MCP. Bind
consequential actions to actual approval controls and exact inputs; a skill
or an enabled feature flag is not per-call approval.

Browser review and package export use separate flags. Neither proves
correct authentication, writable or durable storage, or successful
delivery. Treat signed download links as temporary bearer credentials and
redact them from evidence. Cloud Shell, the VM, the container, and the
workstation have separate filesystems unless a supported transfer or
storage arrangement has been verified.

Outputs do not establish ownership, trust status, jurisdiction, legal
access, commercial status, Tribal approval, or management authority.

## Remaining submission work

- Verify and record the read-only BIA search separately from the successful
  local discovery and Mescalero polygon-generation checks.
- Verify the hosted image, registered schemas, agent and skill bindings,
  remaining browser-review prerequisites, and access to the existing
  Pechanga acquisition before a separately approved review attempt.
- Complete the approved full-boundary workflow: candidate rasters, raw
  polygons, acreage, flags, QC, provenance, package transfer, and
  professional ArcGIS Pro review.
- Record regression and evaluation results and complete the judge-facing
  preview, functional demo, presentation, security notes, and lessons
  learned. A sample demonstrates only the scope actually processed.

Candidate stands and physical-accessibility screening are future
milestones. Physical accessibility does not establish legal access.
Generic onboarding, FIA calibration, AlphaEarth, change detection,
inventory strata, and post-fire analysis are outside this submission scope.

## Documentation and license

Start with [AGENTS.md](AGENTS.md) and the
[project specification](docs/project-specification.md). Read the applicable
pilot definitions before changing forestry rules and the
[delivery notes](docs/review-package-delivery.md) before changing export
or storage. Treat dated checkpoints and plans as such, not as current
verification.

Confirm the project license and third-party code and data redistribution
terms before public release.
