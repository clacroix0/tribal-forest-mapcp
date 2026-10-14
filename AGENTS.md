# Tribal Forest MapCP — Coding Assistant Instructions

Last scope revision: 2026-10-09

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
This file governs coding behavior; the specification governs product scope.

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
installing dependencies, downloading data, deploying, changing permissions or
networking, committing, pushing, or performing external writes.

Do not bypass configured permission controls.
Do not treat plan approval as permission for unrelated work.
Explain consequential commands before execution.

If the user applies code manually, provide precise insertion/replacement
instructions or complete file replacements as requested.

Avoid unrelated rewrites, architectural migrations, and new frameworks.
Preserve working behavior and existing tests.
Do not require a large refactor merely to finish the hackathon prototype.

## Submission scope

Candidate cover-type mapping is the central product and a required feature.

Required:
- Public boundary discovery, selection, and validation.
- Public mapping-input inspection.
- Candidate cover-type raster.
- Companion candidate forest-land output.
- Raw connected same-class patch polygons.
- Separate generalized candidate cover-type review polygons.
- Original-class composition and patch membership for generalized units.
- Acreage summaries, review flags, provenance, parameters, QC, and methods.
- ArcGIS Pro-compatible review package.
- Verified artifact transfer and ArcGIS review.
- A visual preview understandable without ArcGIS.
- Tests, actual evaluation, and documentation.
- A bounded conversational-agent demonstration using the implemented tools.

Generalized review polygons are required for completing this submission.
Raw polygons alone do not satisfy the final polygon deliverable.

Deferred:
- Candidate stand delineation.
- Physical-accessibility screening.
- Interactive merge negotiation or map-click/chat integration.
- Generic cover-scheme onboarding for arbitrary projects.
- FIA-informed calibration.
- AlphaEarth enhancements.
- Change detection, inventory strata, and post-fire analysis.

Do not implement deferred features without a separate scope approval.

## Evidence and status

Distinguish:
- Required.
- Proposed.
- Implemented but unverified.
- Demonstrated locally.
- Verified in the submission environment.
- Deferred.

Plans, filenames, comments, documentation, and prior chat are not proof that
a feature works in the current repository.

Inspect current MCP registration separately from processing implementation.
A function can exist without being exposed to an agent.

Do not claim completion from successful source acquisition alone.
Do not claim generalized mapping from raw polygon generation alone.
Do not claim host integration from MCP Inspector tests alone.

## Forestry safeguards

Ask for approval before changing:
- Geography or planning objective.
- Forest-land policy.
- Cover classes or code meanings.
- Crosswalks.
- EVC/EVH roles or thresholds.
- Disturbance treatment.
- NoData, unknown-code, or conflict treatment.
- Minimum mapping unit or merge rules.
- Generalized-unit labeling or composition rules.

Do not transfer Mescalero-specific decisions to another geography.

Preserve uncertain, mixed, conflicting, disturbed, nonstocked, riparian,
water, unknown-code, and NoData information.

Keep NoData and unknown status distinct from nonforest.
Do not infer disturbance history that has not been evaluated.
Do not convert approved nonstocked forest land to nonforest solely because
current canopy is low.

Public-source vegetation labels are not measurements of species-specific
crown cover, basal area, overstory/understory composition, productivity,
merchantability, or field-verified forest type.

Do not invent confidence scores or accuracy percentages.

Do not infer ownership, trust status, jurisdiction, legal access, commercial
status, productivity, Tribal approval, or management authority.

All outputs remain preliminary and require professional review.

## Generalization guardrails

Preserve:
1. Native classified raster.
2. Raw patch polygons.
3. Generalized review polygons as a separate versioned artifact.

Use actual projected polygon area.
The approved threshold is strictly less than 10,000 square meters.
Patches equal to or larger than the threshold are not small-patch candidates.

For the bounded Mescalero trial:
- Allow eligible small P/PJ patches to become inclusions in an edge-sharing
  P/PJ review unit.
- Preserve original class membership and acreage.
- Do not broaden eligible classes without approval.
- Preserve protected patches and flags.
- Do not treat corner contact as shared-edge adjacency.
- Respect supplied, approved hard boundaries.
- Disclose missing or unevaluated boundary constraints.

Do not invent recipient ranking, tie-breaking, processing order, or dominant
label rules. Obtain approval and record them before implementation.

The threshold is a target for eligible generalization, not permission to
eliminate every sub-threshold feature.

Generalization must not silently reclassify the native raster.
The full area of a mixed P/PJ unit must not be reported as one original class.

Generalized review polygons are not stands.

## MCP tool surface

Expose only tools needed by the submitted workflow.
There is no requirement to expose all historical tools or exactly seven tools.

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
Never expose arbitrary shell, code, SQL, URLs, or unrestricted filesystem access.

A model-supplied approval string is not proof of human approval.
Bind consequential actions to an explicit approval workflow and the exact
reviewed inputs.

## Security and source handling

Use public prototype data only.
Exclude sensitive Tribal information and nonpublic plots.

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
Keep secrets and generated outputs out of Git.

Locally approved configuration files are not automatically public.
Publish only deliberately reviewed and curated examples.

## Environment and host integration

Keep core Python portable.
Do not hardcode workstation-specific paths.
Do not copy a virtual environment between machines.

Verify OS, Python, packages, storage, HTTPS access, permissions, and file transfer
before migration or deployment.

Watsonx Orchestrate is the planned conversational host.
Its integration is not complete until actually tested.

Do not assume the coding assistant is the end-user interface.
Do not assume a cloud host can read laptop paths.
Do not expose the user's workstation publicly to simplify integration.

Use approved sandbox hosting and vendor support for environment blockers.

## Testing and completion

Test:
- Valid, invalid, ambiguous, missing-data, and partial-coverage inputs.
- Service failures and malformed responses.
- Crosswalk/schema/version mismatches.
- Unknown codes, NoData, and conflict handling.
- Raster alignment and acreage.
- Raw polygon geometry and topology.
- Eligible and protected small-patch behavior.
- Shared-edge versus corner-only contact.
- Threshold equality.
- Membership/composition retention.
- Generalization reproducibility.
- Export completeness and advertised MCP tools.

Report actual commands, results, skips, runtime, artifacts, and limitations.
Label fixtures and simulated failures.
Never fabricate results.

Toolset completion requires the acceptance criteria in the specification,
including generalized review polygons and export.

Submission completion additionally requires host interaction, artifact delivery,
evaluation, presentation, and repository evidence.

Close each work item with:
- Changed files or proposed replacements.
- Tests actually run and results.
- Artifacts.
- Acceptance status.
- Known limitations.
- Required next review.

Propose a commit only after relevant review and tests.
Do not commit or push without approval.