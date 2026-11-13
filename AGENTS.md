# Tribal Forest MapCP — Coding Assistant Instructions

Last scope revision: 2026-11-13

## Purpose and working relationship

Tribal Forest MapCP is a 2026 GSA MCP Hackathon prototype supporting
understaffed Tribal and BIA forestry programs with preliminary cover-type
mapping for inventory planning and Forest Management Plan development.

Tagline: Replacing the blank map—not the forester.

The user is a BIA forestry subject-matter expert who builds with AI assistance.
Do not assume the user is currently using Bob or any particular coding agent.

The current working arrangement is:
- The AI assistant advises, reviews, and drafts code, tests, and documentation.
- The user reviews changes, applies approved changes, and runs them.
- The user makes forestry judgments and inspects GIS outputs.

Do not claim to have modified local files, run tests, inspected ArcGIS, or
committed changes unless those actions actually occurred.

Read docs/project-specification.md before major work.
Read relevant local-definition and onboarding documents when needed.
Read docs/review-package-delivery.md before changing export, storage, or
delivery behavior.

This file governs coding behavior; the specification governs product scope.
If instructions conflict, identify the conflict and request clarification
rather than silently changing requirements.

## Work control

Before a substantive change:
1. Inspect the current source, dependencies, relevant tests, and documentation.
2. State a short plan and preferred approach.
3. Identify affected files, assumptions, risks, and acceptance criteria.
4. Obtain approval before implementation or consequential actions.
5. Make only the approved changes.
6. Test success and relevant failure cases.
7. Report evidence and remaining limitations.

Where tools can execute actions, require approval before modifying files,
installing dependencies, downloading data, submitting jobs, writing to remote
storage, deploying, changing permissions or networking, deleting artifacts,
committing, pushing, or performing other consequential actions.

Do not bypass configured permission controls.
Do not treat plan approval as permission for unrelated work.
Explain consequential commands before execution.
If scope, targets, inputs, or risks change, obtain fresh approval.

If the user applies code manually, provide precise insertion/replacement
instructions or complete file replacements as requested.

Avoid unrelated rewrites, architectural migrations, and new frameworks.
Preserve working behavior and existing tests.
Do not require a large refactor merely to finish the hackathon prototype.

Build one testable vertical slice at a time:
- Approve the plan and acceptance criteria.
- Implement the approved change.
- Test success and relevant failures.
- Inspect applicable GIS outputs.
- Record evidence and limitations.
- Update documentation.
- Propose a commit for approval.

## Submission scope

Candidate cover-type mapping is the central product and a required feature.
Candidate forest-land mapping is a required companion, not a substitute.

Required:
- Public boundary discovery, selection, and validation.
- Explicit approval of the analysis boundary and mapping objective.
- Public mapping-input inspection.
- Candidate cover-type raster.
- Companion candidate forest-land output.
- Raw connected same-class patch polygons.
- Acreage summaries, review flags, provenance, parameters, QC, and methods.
- Coverage and completeness reporting for the approved analysis boundary.
- Polygon-inclusive ArcGIS Pro-compatible review package.
- Verified artifact transfer and ArcGIS Pro review.
- A visual preview understandable without ArcGIS.
- Tests, actual evaluation, and documentation.
- A bounded conversational-agent demonstration using implemented tools.

### Geographic scope

The intended final product covers the approved full project boundary.
A public reservation reference boundary is not automatically the approved
forestry analysis boundary.

Small samples are internal development, testing, and method-review aids.
Do not treat sample delivery as satisfying a full-boundary request.

If current tools cannot complete the requested extent:
- State the limitation.
- Identify missing capability or input coverage.
- Label any partial result accurately.
- Do not silently substitute a sample.
- Do not claim full coverage from a rectangular source download or preflight.

A smaller final project boundary requires explicit user approval and accurate
documentation. Full support for one approved pilot does not establish
arbitrary-geography support.

### Optional generalization

Generalized candidate cover-type review polygons are optional and require
separate approval.

When generalization is requested:
- Preserve native rasters and raw polygons.
- Produce separate generalized review polygons.
- Preserve raw-patch membership and original-class composition.
- Record approved rules, parameters, and before/after QC.
- Apply the relevant specification acceptance criteria.

Generalization must not delay the required full-boundary mapping and raw-polygon
delivery workflow when it is not requested.

### Deferred scope

Deferred:
- Candidate stand delineation.
- Physical-accessibility screening.
- Interactive merge negotiation or map-click/chat integration.
- Generic cover-scheme onboarding for arbitrary projects.
- FIA-informed calibration.
- AlphaEarth enhancements.
- Change detection, inventory strata, and post-fire analysis.

Candidate stands and physical-accessibility screening remain next core
milestones after the required mapping and delivery workflow.

Do not implement deferred features without a separate scope approval.

## Evidence and status

Distinguish:
- Required.
- Optional and separately approved.
- Proposed.
- Implemented but unverified.
- Demonstrated on a sample.
- Demonstrated locally.
- Reported artifact—not independently verified.
- Verified in the submission environment.
- Not yet demonstrated across the approved boundary.
- Not yet accepted in ArcGIS Pro.
- Deferred.

Plans, filenames, comments, documentation, and prior chat are not proof that
a feature works in the current repository or deployment.

Use prior reports as dated context, not substitutes for current acceptance
evidence. Attribute user-reported results clearly.

Inspect current MCP registration separately from processing implementation.
A function can exist without being exposed to an agent.

Do not claim completion from successful source acquisition alone.
Do not claim generalized mapping from raw polygon generation alone.
Do not claim host integration from MCP Inspector tests alone.
Do not claim full-boundary execution from preflight acceptance.
Do not claim final delivery from a server-side path.
Do not claim package completeness or accuracy from download success.

Historical test results apply to the version and environment tested.
Do not present them as fresh results for recovered source or a later image.

Obtain exact commit IDs, image references, and deployed revisions from actual
evidence. Do not invent or label them verified based on an earlier assistant
summary.

## Forestry safeguards

Ask for approval before changing:
- Geography or planning objective.
- Forest-land policy.
- Cover classes or code meanings.
- Crosswalks.
- EVC/EVH roles or thresholds.
- Disturbance treatment.
- NoData, unknown-code, or conflict treatment.
- Raster connectivity or polygon area methods.
- Minimum mapping unit or merge rules.
- Generalized-unit labeling or composition rules.
- Acreage and topology acceptance tolerances.

Do not transfer Mescalero-specific decisions to another geography.

Preserve uncertain, mixed, conflicting, disturbed, nonstocked, riparian,
water, unknown-code, and NoData information.

Keep NoData and unknown status distinct from nonforest.
Do not infer disturbance history that has not been evaluated.
Do not convert approved nonstocked forest land to nonforest solely because
current canopy is low.
Do not invent unsupported NT/NW assignments.

Public-source vegetation labels are not measurements of species-specific
crown cover, basal area, overstory/understory composition, productivity,
merchantability, or field-verified forest type.

Do not invent confidence scores or accuracy percentages.

Public FIA may support regional ecological plausibility and approved future
calibration. Altered public plot coordinates are not exact pixel-level or
stand-level reference labels.

Check source lineage before claiming independent validation.
Computational QC, source agreement, and acreage closure are not accuracy
estimates.

Do not infer ownership, trust status, jurisdiction, management responsibility,
legal access, commercial status, productivity, Tribal approval, or management
authority.

All outputs remain preliminary and require professional review.
They do not constitute Realty verification, field inventory, or approved
management classes.

## Full-boundary processing guardrails

Inspect existing acquisition, preflight, mapping, polygon, and export code
before designing replacements.

Prefer extending existing components and preserving approved classification
logic. Do not assume that two new public tools or a large rewrite are required.

Before full-boundary execution, verify:
- Approved analysis boundary and objective.
- Required source coverage and missing areas.
- CRS, resolution, grid alignment, and NoData.
- Expected dimensions and cell counts.
- Available memory, disk, runtime, and persistent storage.
- Source-service limits.
- Existing sample-only assumptions.
- Artifact transfer and recovery arrangements.

Do not scale solely by removing processing limits.
Use bounded acquisition and tiled processing where needed.

Maintain consistent class rules and grid alignment across tiles.
Reconcile tile-edge patches when polygon generation is tiled.
Check for artificial seams, gaps, overlaps, or fragmented same-class patches.

Record boundary clipping and edge-cell acreage methods.
Account for unknown, NoData, unsupported, and unmapped areas in coverage and
acreage reporting.

NAIP is visual-review context unless a separate analytical method is approved.
Do not require a full-boundary NAIP mosaic merely because a sample workflow
used NAIP.

Preflight validates readiness; it does not execute mapping.
Long-running execution/status interfaces require an explicit design based on
actual processing and host constraints.

## Generalization guardrails — when requested

Apply these rules only to a requested, separately approved generalization run.

Preserve:
1. Native classified raster.
2. Raw patch polygons.
3. Generalized review polygons as a separate versioned artifact.

Use actual projected polygon area.

For the approved bounded Mescalero trial, the small-patch eligibility threshold
is strictly less than 10,000 square meters. Patches equal to or larger than the
threshold are not small-patch candidates.

For that trial:
- Allow eligible small P/PJ patches to become inclusions in an edge-sharing
  P/PJ review unit.
- Preserve original class membership and acreage.
- Do not broaden eligible classes without approval.
- Preserve protected patches and flags.
- Do not treat corner contact as shared-edge adjacency.
- Respect supplied, approved hard boundaries.
- Disclose missing or unevaluated boundary constraints.

Do not automatically apply bounded-trial approval to full-boundary processing
or another geography.

Verify existing approval records for recipient ranking, tie-breaking,
processing order, frozen-area eligibility, subsequent inclusions, unmergeable
patch treatment, and display labels.

Do not invent missing rules. Obtain approval and record them before
implementation.

The threshold is an eligibility rule, not permission to eliminate every
sub-threshold feature or a guarantee that all final polygons exceed one hectare.

Generalization must not silently reclassify the native raster.
The full area of a mixed P/PJ unit must not be reported as one original class.

Each raw patch must have exactly one generalized-unit membership when
generalization is performed.

Do not introduce smoothing, simplification, buffering, hole filling, or
reclassification without separate approval.

Generalized review polygons are not stands.

## MCP tool surface

Expose only tools needed by the submitted workflow.
There is no requirement to expose all historical tools or exactly seven tools.

Design public tools around forestry outcomes rather than individual REST
endpoints or GIS commands.

Retain useful diagnostic, recovery, and lower-level processing functions
internally or in a developer-only interface.

Do not delete working implementations merely to reduce tool count.
Check dependencies before removing MCP registrations.
Test the actual advertised tool list.

Do not expose deprecated LANDFIRE submission routes for new work.
Keep asynchronous submission, status, and collection separate unless an
approved, tested alternative preserves reliability and approval controls.

Use validated inputs and structured outputs.
Descriptions must explain purpose, prerequisites, limitations, outputs,
side effects, and failure behavior.

Return bounded summaries and controlled artifact references.
Save large outputs as files.

Carry exact returned identifiers between tools.
Do not interchange collection manifests, mapping methods files, package IDs,
and raw-run directories.

Never expose arbitrary shell, code, SQL, URLs, object keys, buckets, or
unrestricted filesystem access.

A model-supplied approval string is not proof of human approval.
Bind consequential actions to an explicit approval workflow and the exact
reviewed inputs.

## Export and delivery guardrails

Inspect current export contracts before changing input schemas or packaging.
Do not invent supported export parameters.

The current documented exporter is raster-only. Extending it to include
required polygons is an implementation task, not an agent-instruction change.

Required final packaging must:
- Include completed candidate rasters and raw cover-type polygons.
- Include matching acreage summaries, codebook, QC, methods, and provenance.
- Validate project/run identity and requested geographic extent.
- Identify missing or failed required layers.
- Record optional generalization status.
- Use controlled artifact references.
- Preserve original artifacts and avoid automatic overwrites.

A raster-only sample package may be delivered as an explicitly labeled
intermediate result. It does not satisfy the full polygon-inclusive product.

A server-side GeoPackage path is not evidence that the user can retrieve it.
Verify artifact existence, identity, availability, packaging, and transfer.

Do not promise SCP access or another transfer route without checking the actual
environment and approved transfer mechanism.

Verify final package opening and usability in ArcGIS Pro.
A VM-only test or included opening guide is not ArcGIS acceptance.

### Export enablement and approval

Eric confirmed that the deployed Code Engine application has:

    MAPCP_REVIEW_EXPORT_ENABLED=true

This is administrator enablement, not per-call approval, proof of secure storage,
or evidence that source-code defaults changed.

Do not treat enablement as authorization to change configuration, deploy, write
new storage objects, weaken safeguards, or process a larger extent.

Preserve and verify required configuration during deployment changes.
Do not assume replacement applications inherit it.

The current documentation records unresolved approval, concurrency, storage,
renewal, and acceptance checks. Do not mark them complete from download success.

## Security and source handling

Use public prototype data only.
Exclude sensitive Tribal information, culturally sensitive locations, and
nonpublic plots.

Use allowlisted HTTPS sources, timeouts, bounded retries, processing limits,
safe ZIP extraction, and explicit failure reporting.
Never hide a failed source.

Use LFPS v2 only with a verified API contract.
Do not reuse legacy submission patterns.

LFPS contact email:
- Accept any valid email domain.
- Use only for the explicitly approved submission.
- Never persist the raw email in code, artifacts, logs, tests, documentation,
  screenshots, or Git.
- Record only contact_email_supplied: true/false.
- Avoid exposing credentials or contact details in conversation.

Use controlled directories and validated filenames/artifact identifiers.
Do not overwrite previous runs automatically.
Keep secrets and generated outputs out of Git except deliberately curated,
approved public examples.

Locally approved configuration files are not automatically public.
Publish only deliberately reviewed and curated examples.

Keep storage credentials in approved runtime secrets.
Do not print SDK configuration or expose raw credential-bearing exceptions.

Signed download URLs are temporary bearer credentials:
- Share them only for requested delivery.
- Do not store them in Git, documentation, evaluation records, or logs.
- Redact them from shared troubleshooting evidence.
- Do not fabricate or reconstruct them from guessed paths.

Do not infer credential scope, retention, overwrite protection, individual-user
authorization, or tenant isolation from a working link.

Preserve reviewed, redacted evidence in approved storage rather than committing
raw traces.

## Environment and host integration

Keep core Python portable.
Do not hardcode workstation-specific paths.
Do not copy a virtual environment between machines.
Do not change system Python to solve a project-level dependency problem.

Verify OS, Python, packages, compute, storage, HTTPS access, permissions, and
file transfer before migration or deployment.

Cloud Shell, the VM, the deployed container, and the workstation have separate
filesystems unless a specific sharing or transfer arrangement is verified.

Do not assume container outputs survive revision replacement.
Preserve necessary artifacts before deployment or cleanup.
Do not remap merely to restore an export when existing artifacts can be
recovered safely.

Watsonx Orchestrate is the current conversational host.
Hosted access, bounded draft behavior, and a sample download have been observed
or user-reported. These do not establish complete end-to-end reliability.

Verify current agent bindings, registered schemas, runtime skill, and hosted
configuration before claiming they match Git.

Do not assume the coding assistant is the end-user interface.
Do not assume a cloud host can read laptop paths.
Do not expose the user's workstation publicly to simplify integration.

Use approved hosting and vendor support for environment blockers.
Do not bypass security controls.

## Testing and completion

Test required workflow behavior:
- Valid, invalid, ambiguous, missing-data, and partial-coverage inputs.
- Service failures and malformed responses.
- Crosswalk/schema/version mismatches.
- Unknown codes, NoData, and conflict handling.
- Raster alignment and acreage.
- Coverage over the approved analysis boundary.
- Boundary clipping and acreage closure.
- Tile seams and edge-patch reconciliation where applicable.
- Raw polygon geometry, topology, and raster correspondence.
- Repeated-run reproducibility.
- Export completeness, run identity, and geographic extent.
- Honest handling of missing or changed artifacts.
- Advertised MCP tools and actual host selection.
- Authorized delivery, expired links, and renewal where supported.

When generalization is implemented and exercised, also test:
- Eligible and protected small-patch behavior.
- Shared-edge versus corner-only contact.
- Threshold equality.
- Multiple recipients and deterministic tie-breaking.
- Unmergeable patches.
- Membership/composition retention and closure.
- Generalization reproducibility.

Report actual commands, results, skips, runtime, artifacts, and limitations.
Label fixtures and simulated failures.
Never fabricate results.

Do not install packages into or alter the live application container merely
to run tests. Use an approved development or test environment.

Toolset completion requires the applicable acceptance criteria in the
specification, including full approved-boundary mapping, required raw polygons,
and polygon-inclusive export.

Generalization acceptance is required only when generalization is requested.

Submission completion additionally requires actual host interaction, artifact
delivery, ArcGIS Pro review, evaluation, presentation, and repository evidence.

Close each work item with:
- Changed files or proposed replacements.
- Commands actually run.
- Tests actually run and results.
- Artifacts.
- Acceptance status.
- Known limitations.
- Required next review.

For documentation-only changes, state that no code tests were run when that is
the case. Do not imply that editing status documentation verifies implementation.

Propose a commit after applicable review and tests.
Do not commit or push without approval.
