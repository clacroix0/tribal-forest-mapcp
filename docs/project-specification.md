# Tribal Forest MapCP — Project Specification

Scope revision: 2026-11-13
Previous scope revision: 2026-10-09
Status: Hackathon completion specification and dated progress record; not a claim
that all requirements are implemented or accepted.

## 1. Mission

Help understaffed Tribal and BIA forestry programs replace a blank starting map
with transparent, preliminary candidate cover-type mapping for forest inventory
planning and Forest Management Plan development.

Tagline: Replacing the blank map—not the forester.

The central product is actual cover-type mapping with acreage, uncertainty,
provenance, and professional-review information. Candidate forest-land mapping
is a required companion, not a substitute for cover types.

Outputs are preliminary and require professional forestry and GIS review.
They do not constitute Tribal approval, Realty verification, field inventory,
management authority, authoritative ownership or trust-status determination,
legal-access determination, or final management classes.

## 2. Submission endpoint and geographic scope

The intended submission workflow produces the following across an explicitly
approved full project boundary:

- Candidate cover-type mapping.
- Companion candidate forest-land mapping.
- Raw same-class patch polygons.
- Acreage, QC, review flags, methods, and provenance.
- An ArcGIS Pro-compatible downloadable review package.
- A judge-friendly visual preview.
- A bounded AI-agent demonstration of the implemented workflow.

Generalized candidate cover-type review polygons are optional and require
separate approval. When generalization is requested, include raw-patch
membership, original-class composition, generalization parameters, and
before/after QC.

Raw patches and generalized review polygons are not candidate stands or
approved management units.

### Geographic completeness

The required deliverable covers the approved analysis boundary, not merely a
sample within a broader reference boundary.

The approved analysis boundary must be explicitly identified. A public
reservation reference polygon does not automatically establish the appropriate
forestry project boundary or its legal authority.

Small samples remain useful for internal development, testing, and method
review. Sample success does not satisfy a request for full-boundary delivery.

If a full-boundary request cannot be completed, return an explicit limitation
or partial result with coverage information. Do not silently substitute a sample
or label partial mapping as the full product.

A smaller final project geography may be used only with explicit user approval
and must be described accurately. Do not reduce geography without approval
merely to satisfy a completion claim.

Full-boundary support for the approved pilot does not establish arbitrary-
geography support.

## 3. Deferred scope

Not required for this submission:

- Stand delineation.
- Physical-accessibility screening.
- Interactive merge negotiation.
- Map-click integration with chat.
- Generic cover-scheme onboarding.
- FIA calibration.
- AlphaEarth.
- Change detection.
- Inventory strata.
- Post-fire analysis.

Candidate stands and physical-accessibility screening remain next core
milestones after the required mapping and delivery workflow.

Generalization is optional for this submission. Existing generalization work
and tests should be preserved, but it must not delay required full-boundary
cover-type mapping and polygon-inclusive delivery.

Deferred features must not delay the required endpoint.

## 4. Authority and user decisions

The user approves:

- Project objective and analysis boundary.
- Forestry definitions and candidate forest-land policy.
- Cover scheme and source-to-class crosswalks.
- Thresholds and source roles.
- Disturbance treatment.
- Unknown-code and NoData treatment.
- Connectivity, polygon rules, and acreage tolerances.
- Generalization, minimum mapping units, and merge rules when requested.

User approval of a pilot configuration does not establish Tribal approval or
management authority.

Local definitions are documented separately. This specification does not
redefine local cover-type codes.

Mescalero-specific decisions are not defaults for another Tribe or geography.

The user reviews, applies, and runs changes directly with AI-assisted research,
planning, code review, and troubleshooting. Do not assume IBM Bob is in use.

Before major work, provide a short plan, preferred approach, affected files,
risks, acceptance criteria, and sequential guidance. Inspect current source and
tests before proposing implementation changes.

Obtain approval before implementation and consequential commands, installations,
remote submissions, storage writes, configuration changes, deployment, cleanup,
commits, or pushes. Approval of a plan does not authorize unrelated actions.

## 5. Input requirements

Validate and record:

- Public boundary source and selected record.
- Geometry validity and feature identifiers.
- Approved analysis extent versus broader reference boundary.
- CRS, units, and projected area.
- Source product, version, acquisition date, and lineage.
- Raster resolution, alignment, bands, coverage, and NoData.
- Actual EVT codes and metadata.
- Crosswalk, scheme, and rule versions.
- Missing inputs, partial coverage, and limitations.

Use public government sources for the core workflow.

NAIP is visual-review context unless a separate analysis method is approved.
Do not require a full-boundary NAIP mosaic unless the approved analytical method
actually depends on it.

LANDFIRE EVT is the initial classification basis. EVC/EVH roles must match the
approved rules. Do not claim that encoded EVC/EVH classes are direct physical
measurements or that their presence proves they were used in classification.

Do not claim independent validation from modeled products with shared lineage.

### Full-boundary readiness

Before full-boundary execution, inspect:

- Coverage of required inputs over the approved analysis boundary.
- Expected raster dimensions and cell count.
- Estimated memory, disk, processing time, and service-request requirements.
- Source-service limits and permitted acquisition methods.
- Storage persistence and artifact-transfer arrangements.
- Need for tiled acquisition or processing.
- Existing sample-only assumptions in mapping and polygon code.

Do not scale the workflow solely by removing processing limits.

Use bounded requests and tiled processing where needed. Maintain consistent CRS,
grid alignment, class rules, and NoData treatment across tiles.

If polygon processing is tiled, reconcile tile-edge patches and validate that
tile boundaries do not introduce artificial gaps, overlaps, or fragmented
same-class patches.

A rectangular source download is not proof of complete mapping within the
approved analysis boundary. Record boundary clipping and edge-cell area methods.

## 6. Candidate classification

Use saved, versioned, approved pilot configurations and crosswalks.
Validate their identifiers and compatibility before mapping.

Reject or return an explicit approval-required status for missing or unapproved
configuration. Do not silently fall back to a different scheme.

Initial classification assigns one primary candidate class per source cell.

Required safeguards:

- Candidate labels, not field-verified labels.
- Unknown source codes remain identifiable.
- NoData remains distinct from nonforest.
- Uncertain/conflicting evidence is retained and flagged.
- Species-specific crown cover and overstory/understory are not claimed as
  measured.
- Disturbance history is not inferred from a vegetation label alone.
- Confidence percentages are not invented.

For the approved Mescalero pilot:

- Woodland classes are candidate forest land.
- Approved NT and NW classes are candidate forest land.
- Low canopy alone does not override that policy.
- Unsupported assignment to NT/NW must not be invented.
- Unknown forest-land status is not false/nonforest.

Use the approved pilot treatment for consolidated riparian classes.
Do not claim unresolved local riparian subtypes are mapped.

Candidate cover-type and forest-land mapping may share processing and evidence.
Document their relationship rather than introduce inconsistent classification
logic.

## 7. Polygon products

### 7.1 Native classified raster

Preserve the classified raster unchanged.

Record its relationship to source products, the approved crosswalk, the
analysis boundary, and any clipping or masking operation.

If separate derived rasters are needed, preserve the original run artifacts
and document the derivation.

### 7.2 Raw patch polygons — required

Create connected same-class patches using the documented approved connectivity.
Preserve stable patch identifiers within the run.

Retain:

- Original candidate class.
- Candidate forest-land status.
- Area and acreage.
- Review flags.
- Run and source references.

Validate geometry, gaps, overlaps, raster correspondence, and class acreage.

For full-boundary processing, validate coverage against the approved analysis
boundary. Explicitly represent or account for NoData, unknown, unsupported, and
unmapped areas; do not silently remove them from acreage closure.

Document expected boundary-cell differences between raster and vector acreage
and use approved tolerances.

### 7.3 Generalized review polygons — optional

Create a separate generalized review layer only when requested and separately
approved.

The purpose is to reduce impractical fragmentation while retaining source
evidence. Generalization groups raw patches; it does not change the native
raster or convert candidate polygons into stands.

Required outputs when generalization is performed:

- Generalized polygon geometry.
- Stable review-unit identifiers within the run.
- Raw-patch-to-unit membership table.
- Per-unit original-class composition table.
- Generalization parameters and rule version.
- Before/after QC and summaries.

If generalization is not requested, record it as not requested or not performed.
Its absence must not be represented as a failed required workflow stage.

## 8. Approved bounded generalization trial — optional workflow

The existing Mescalero trial allows eligible small P and PJ patches to be
absorbed as inclusions into edge-sharing P/PJ review units.

This trial is not automatically authorized for every mapping request or for
full-boundary execution. Verify the current approved configuration, implemented
rules, tests, and processing limits before use.

### Eligibility

- Original patch area must be strictly less than 10,000 m².
- Use actual projected polygon area, not approximate cell count.
- Exactly 10,000 m² is not eligible under the small-patch threshold.
- Source and recipient must satisfy the approved P/PJ compatibility rule.
- Shared-edge adjacency is required; corner-only contact is insufficient.
- Protected patches and protected flags are excluded.
- Supplied approved hard boundaries must not be crossed.

The trial does not authorize merges involving other classes.

### Protected information

Preserve:

- NT and NW.
- Riparian classes.
- Water.
- Known disturbance-review features.
- Mixed/conflicting or uncertain features.
- Unknown source codes and NoData.

If disturbance or hard-boundary information is unavailable, record that it was
not evaluated. Do not claim protection based on absent data.

Never automatically merge:

- Forest or woodland with nonforest.
- Riparian with upland.
- Water with land.
- Nonstocked forest with nonforest.
- Unknown/NoData with a confident class.

### Implementation choices requiring an approved record

Verify and retain explicit approval for:

- Recipient ranking among multiple eligible neighbors.
- Tie-breaking.
- Processing order.
- Whether eligibility uses frozen original patch area throughout the pass.
- Whether merged units may receive subsequent inclusions.
- Treatment of an eligible patch with no eligible recipient.
- Display label for a unit containing both P and PJ.

Some choices may already be implemented or approved. Inspect the current source,
configuration, and approval record rather than assuming they remain unresolved.

Implement only approved choices. Save them as parameters or versioned rules,
not undocumented code behavior.

Do not introduce smoothing, simplification, buffering, hole filling, or
reclassification without separate approval.

### Composition and labeling

When generalization is performed, each raw patch must belong to exactly one
generalized unit.

Retain original-class area and percentage for each unit.
A generalized unit containing P and PJ must disclose both.

Keep separate:

- Original classification acreage.
- Generalized-unit footprint acreage.
- Any approved display/primary label.

Do not count a mixed unit's entire area as its display class.

A display label is a cartographic summary, not a new measured classification.

### Minimum mapping unit limitation

The 10,000 m² threshold is a rule for eligible patches, not a guarantee that
all final polygons exceed one hectare.

Protected, isolated, or ineligible small features may remain.
Report why they remain rather than force a merge.

## 9. Generalization acceptance criteria — when requested

Required when generalization is performed:

1. Native raster remains unchanged.
2. Raw patches remain available.
3. Output is deterministic for identical inputs and parameters.
4. Every raw patch has exactly one unit membership.
5. No patch is lost or duplicated.
6. Total footprint area closes within a documented tolerance.
7. Original-class acreage is preserved within documented tolerance.
8. Protected features are not silently absorbed.
9. Edge adjacency and barrier constraints are enforced as implemented.
10. Geometry, overlaps, and gaps pass QC.
11. Unmerged eligible patches have an explicit reason.
12. Review flags and provenance are retained.
13. Visual review in ArcGIS Pro is recorded.

A lower polygon count alone does not demonstrate success.
Do not invent a target reduction percentage.

These criteria do not make generalization mandatory for the core deliverable.

## 10. Final review package

### Required contents

- Validated analysis boundary and public reference information.
- Candidate cover-type GeoTIFF.
- Candidate forest-land GeoTIFF.
- GeoPackage containing raw candidate cover-type patch polygons.
- Cover-type and forest-land acreage CSVs.
- Codebook.
- Source manifest.
- Parameters and approved configuration references.
- Methods, QC, limitations, and review flags.
- Coverage and completeness information for the approved analysis boundary.
- ArcGIS Pro opening instructions.
- A static map preview readable without GIS software.

Candidate forest-land status may be an attribute of the raw cover-type polygons
where appropriate. Do not create duplicate geometry layers solely for each
attribute.

### Conditional contents

When generalization is requested and completed, also include:

- Generalized candidate cover-type review polygons.
- Raw-patch-to-unit membership table.
- Generalized-unit original-class composition table.
- Generalization summary and unmerged-patch reasons.
- Generalization parameters and before/after QC.

Clearly record whether optional layers were not requested, completed, failed,
or unavailable.

### Export behavior and validation

Use controlled filenames and run identifiers.
Do not overwrite existing outputs automatically.

Export must verify required artifacts exist, are valid, and belong to the
intended project/run and requested geographic extent.

Do not accept arbitrary filesystem paths, object keys, buckets, or URLs as a
substitute for controlled artifact references.

Export must not package missing outputs as if the workflow succeeded.
A raster-only package may be delivered as an explicitly labeled intermediate
result, but it does not satisfy the required polygon-inclusive final package.

Never silently omit a failed, unfinished, or unavailable required layer.

Verify transfer from the execution environment to the ArcGIS workstation.
A remote filesystem path is not a completed download mechanism.

Verify actual ArcGIS Pro opening, CRS, geometry, attributes, class interpretation,
NoData, acreage, and layer usability. Record reviewer, date, software version,
findings, and limitations.

## 11. MCP interface

Expose a coherent set of tools needed to finish the approved mapping workflow.
Do not enforce an arbitrary tool count.

Workflow capabilities include:

- Boundary discovery and selection.
- Input validation and source inspection.
- Full-boundary readiness/preflight.
- Necessary source preparation/acquisition.
- Asynchronous job submission, status, and collection where required.
- Candidate mapping.
- Required raw polygon generation.
- Optional polygon generalization.
- Review-package export and authorized retrieval.

Exact registered names are determined from the current repository.
A capability listed here is not proof that its tool exists.

Prefer extending existing mapping, polygon, and export components before adding
new public tools. Add execution/status interfaces only when justified by actual
processing and host constraints.

Preflight is not execution. An accepted readiness request does not establish
that mapping has run or that artifacts exist.

Retain useful developer diagnostics and recovery functions internally or in a
separate developer interface.
Exclude deprecated source routes from the submitted agent workflow.

Before hiding any tool:

- Identify its callers and output consumers.
- Preserve required workflow dependencies.
- Retain useful tests.
- Verify the advertised MCP tool list.

Use validated schemas, precise descriptions, bounded responses, explicit
statuses, warnings, metrics, and artifact references.

Keep source-service requests, downloads, tiling, GIS processing, and storage
operations internal to the appropriate forestry-outcome capability.

Expose no unrestricted shell, code, SQL, URLs, or filesystem operations.

## 12. Conversational interaction

Watsonx Orchestrate is the current conversational host. Hosted-agent access and
bounded draft behavior have been observed, and the user confirmed a sample
download. These observations do not establish complete end-to-end reliability
or that the hosted agent matches the latest version-controlled configuration.

The agent should:

- Resolve the approved project boundary, objective, and required artifacts.
- Distinguish a full-boundary product request from an internal sample test.
- Explain available data, geographic coverage, and limitations.
- Use approved pilot configurations.
- Reuse suitable existing artifacts.
- Carry exact returned artifact identifiers between tools.
- Request explicit approval for consequential actions.
- Invoke real tools and respect their actual schemas.
- Explain actual acreage, coverage, and QC results.
- Provide a usable package handoff.
- Clearly label intermediate and incomplete packages.
- Present an actual returned download link when delivery is requested.
- Never invent filenames, artifact existence, processing results, or links.
- Never describe raw patches or generalized units as stands.

Do not force a sample-delivery workflow when the user requested the full product.
If current tools cannot perform the full request, state the limitation rather
than imply a sample satisfies it.

Do not build interactive merge negotiation for this submission.
When generalization is requested, an approved deterministic run and professional
GIS review are sufficient.

Human approval must be bound to the reviewed action and inputs.
A model-generated approval phrase alone is insufficient.

Runtime skills and instructions guide behavior; they do not implement missing
backend capabilities, persistent storage, authorization, or file transfer.

## 13. Reliability, privacy, and portability

Use:

- Allowlisted HTTPS sources.
- Timeouts and bounded retries.
- Processing/resource limits.
- Safe downloads and extraction.
- Validated artifact identifiers.
- Controlled directories.
- Explicit partial-failure handling.
- Reproducible parameters and source references.
- Tiled raster processing where required by the approved extent.

Keep core Python portable.
Verify dependencies, permissions, persistence, and transport in each environment.
Do not copy virtual environments between machines.

Cloud Shell, the VM, the deployed container, and the workstation have separate
filesystems unless a specific transfer or storage arrangement is verified.

LFPS contact email is used only for approved submission.
Do not persist raw email in artifacts, logs, documentation, tests, or Git.
Accept valid email domains without an agency-domain restriction.

Use only public prototype data.
Review local configurations before publishing curated examples.
Keep secrets and generated outputs out of Git except deliberately curated,
approved public examples.

Do not publish unauthenticated endpoints or expose government workstations.

### Export configuration and delivery safeguards

Eric confirmed that the deployed Code Engine application has:

    MAPCP_REVIEW_EXPORT_ENABLED=true

This is an administrator enablement setting, not per-call human approval,
evidence of package completeness, or proof that source-code defaults changed.

Preserve and verify required configuration during deployment changes.
Do not assume a replacement application inherits it.

Keep storage credentials in approved runtime secrets.
Signed download URLs are temporary bearer credentials. Share them only for
requested delivery; exclude them from Git, documentation, evaluation records,
and diagnostic logs. Redact them from shared troubleshooting evidence.

Do not infer approved credential scope, retention, overwrite protection, or
tenant isolation from a successful download.

The current deployment's bearer access and package identifiers do not by
themselves establish individual-user or multi-tenant authorization.

See `docs/review-package-delivery.md` for the documented export contract,
historical tests, concurrency limitations, deployment observations, and
remaining live acceptance checks.

## 14. Evaluation

Evaluate separately:

- Tool/request validity.
- Workflow completion and failures.
- Geographic completeness.
- GIS correctness.
- Generalization behavior when performed.
- Agent tool selection.
- Artifact delivery.
- ArcGIS compatibility.
- Reproducibility and runtime.

Test:

- Valid and invalid requests.
- Ambiguous references.
- Missing and partial data.
- Service failures.
- Schema and configuration mismatch.
- Unknown codes and NoData.
- Required-input coverage over the approved boundary.
- Boundary clipping and acreage closure.
- Tile alignment, seams, and edge-patch reconciliation where applicable.
- Repeated-run determinism.
- Export completeness and run identity.
- Honest reporting of intermediate or incomplete packages.
- Authorized download and renewal behavior where supported.

When generalization is implemented and exercised, also test:

- Threshold equality.
- Shared-edge and corner-only contact.
- Protected patches.
- Multiple candidate recipients and ties.
- Unmergeable patches.
- Membership and composition closure.

Use synthetic fixtures for controlled cases and label them clearly.
Record actual tests, runtime, skips, failures, and review evidence.

Historical test results are dated evidence for the tested version and
environment. They are not fresh results for recovered source or a later
deployment.

Measure classification accuracy only with defensible independent references.
Do not confuse computational QC, source agreement, acreage closure, or visual
plausibility with measured accuracy.

Public FIA may support regional ecological plausibility and future calibration.
Altered public plot coordinates are not exact pixel-level or stand-level
reference labels.

## 15. Completion gates

### Local toolset ready for complete host workflow

- Approved boundary and input configurations are validated.
- Required inputs cover the approved extent, or gaps are explicitly represented.
- Candidate mapping is reproducible over the approved full boundary.
- Required raw polygons meet geometry, raster-correspondence, and acreage checks.
- Tiled operations, if used, pass alignment and seam checks.
- Required polygon-inclusive export package is complete.
- Relevant tests pass and failures/skips are explained.
- Advertised tools match the implemented workflow.
- Documentation matches current implementation.
- No sample is presented as satisfying a full-boundary request.

### Optional generalization accepted

When generalization is requested:

- Approved merge choices are recorded.
- Generalized polygons meet the applicable acceptance criteria.
- Membership and composition outputs are complete.
- Original rasters and raw patches remain available.
- Generalization QC and ArcGIS Pro review are recorded.

This gate does not block the core product when generalization is not requested.

### Submission ready

Additionally:

- Host connection and actual agent calls are demonstrated.
- Full approved-boundary workflow completion is demonstrated.
- Artifact retrieval and workstation transfer are verified.
- Actual ArcGIS Pro review and limitations are recorded.
- Actual evaluation is documented.
- Repository includes reproducible instructions and curated public examples.
- Presentation and recorded demonstration are prepared.
- Judges can understand outputs without ArcGIS.
- Security notes and lessons learned are included.
- The reviewed version is committed.

If the user explicitly approves a smaller final project boundary, record that
scope decision and demonstrate completion across that approved boundary.
Do not silently substitute a sample or claim broader coverage.

## 16. Implementation status — November 13, 2026

This section summarizes reported progress and supplied evidence, not a fresh
repository audit, regression run, or independent GIS acceptance review.

### Demonstrated or reported pilot progress

- Source acquisition and inspection have been demonstrated locally.
- Candidate cover-type and forest-land raster mapping have been demonstrated
  in the pilot workflow.
- Raw patch generation has been demonstrated in the pilot workflow.
- Generalization and composition source and associated tests were reported
  tracked at the November 10 checkpoint; current execution and acceptance
  require verification.
- A hosted Orchestrate agent and registered runtime skill were accessed and
  exercised in a bounded draft-preview test.
- That draft test still showed invented artifact details, unnecessary
  prerequisite expansion, and premature approval requests.
- The user confirmed successful download of a sample-area raster review ZIP
  on November 13.
- The downloaded package contains candidate cover-type and forest-land
  rasters, acreage tables, codebooks, methods JSON, and an ArcGIS Pro guide.
- Eric confirmed the deployed export-enablement setting.
- The user reported that recovered export code and supporting deployment
  requirements were merged into `main` and the VM synchronized.

### Current limitations and verification gaps

| Capability | Current status |
|---|---|
| Sample raster mapping | Demonstrated in the pilot; current regression and artifact checks remain separate requirements. |
| Raw patch generation | Previously demonstrated in the pilot; the currently reported deployed GeoPackage requires availability and identity verification. |
| Generalization | Optional; source/test presence does not establish current execution, QC, or acceptance. |
| Full-boundary readiness | Related modules were reported tracked; preflight is not full-boundary execution. |
| Full-boundary mapping | Not yet demonstrated across the approved full project boundary. |
| Raster review download | User confirmed successful sample-package download. |
| Polygon-inclusive export | Not implemented by the current raster-only exporter. |
| Final package completeness | Not accepted; required full-boundary and polygon deliverables remain unresolved. |
| ArcGIS Pro final-package acceptance | Not yet established for the delivered package. |
| Host approval enforcement | Not established by the enabled export switch or download success. |
| Storage safeguards and renewal | Require explicit evidence for the documented controls and live acceptance cases. |
| Fresh regression verification | Not established for the current recovered source and deployed image by this update. |
| Independent classification accuracy | No defensible independent accuracy estimate is claimed. |
| Candidate stands and accessibility | Deferred from this submission; next core milestones. |

### Preferred next implementation objective

Inspect the current committed acquisition, preflight, mapping, polygon, and
export code. Identify the smallest approved changes needed to:

1. Process the approved full project boundary with bounded resources.
2. Produce matching candidate cover-type and forest-land outputs.
3. Generate and validate raw cover-type polygons.
4. Package those outputs with coverage, acreage, QC, methods, and provenance.
5. Deliver and verify the package in ArcGIS Pro.

Use internal small-area tests before an approved full-boundary run, without
making sample delivery the intended end-user product.

Do not assume that two new public tools are required, that existing processing
must be replaced, that full-boundary NAIP mosaics are mandatory, or that raising
all limits is an acceptable implementation.

Update status only with identifiable source, test, artifact, deployment, and
review evidence. Never infer completion from filenames, module presence,
instructions, plans, or model-generated claims.
