# Tribal Forest MapCP

Replacing the blank map—not the forester.

Tribal Forest MapCP is a 2026 GSA MCP Hackathon prototype that helps
understaffed Tribal and BIA forestry programs create preliminary candidate
cover-type mapping from public government data.

The intended result is a transparent, ArcGIS Pro-compatible review package
for forest inventory planning and Forest Management Plan development.

## Submission scope

The hackathon product includes:
- Public boundary discovery, selection, and validation.
- Input coverage and source inspection.
- Candidate cover-type raster.
- Companion candidate forest-land raster.
- Raw connected same-class patch polygons.
- Generalized candidate cover-type review polygons.
- Patch membership and original-class composition tables.
- Acreage, review flags, provenance, parameters, and QC.
- An ArcGIS-compatible export package.
- A visual preview readable without ArcGIS.
- A bounded conversational-agent demonstration.

Generalized review polygons are part of the required product.
They are not candidate stands or approved management units.

## Current status

This is an active prototype, not a completed production service.

Reported local progress includes:
- Public-boundary discovery and validation.
- NAIP coverage inspection and bounded review sampling.
- LFPS v2 request preparation, submission, status checking, and collection.
- LANDFIRE raster and metadata inspection.
- Pilot candidate cover-type and forest-land raster generation.
- Raw cover-type polygon generation.

The following remain to be verified complete:
- Deterministic generalized review polygons.
- Membership and class-composition outputs.
- Final review-package export.
- Curated public MCP tool surface.
- Full regression and end-to-end evaluation.
- Watsonx Orchestrate interaction.
- Artifact retrieval from the execution environment.

Status reflects reported pilot progress and must be checked against the
current source, tests, and artifacts.

The demonstrated pilot does not establish full-reservation processing,
arbitrary-geography support, or measured classification accuracy.

## Why this project exists

Many forestry programs need a useful starting map before they can plan an
inventory or develop a management plan.

MapCP aims to automate public-data acquisition, preliminary classification,
acreage calculation, and transparent documentation so professionals can begin
with a reviewable map rather than a blank workspace.

It supports professional judgment; it does not replace it.

## Mapping approach

The bounded pilot workflow:
1. Identifies and reviews public boundary references.
2. Validates the selected analysis extent.
3. Inspects public imagery and vegetation inputs.
4. Uses an approved, versioned pilot cover scheme and EVT crosswalk.
5. Produces candidate cover-type and forest-land rasters.
6. Generates raw connected same-class patches.
7. Creates separate generalized review polygons under approved rules.
8. Preserves original-class composition and raw-patch membership.
9. Packages maps, summaries, QC, provenance, and limitations.

NAIP provides visual-review context unless a separate method is approved.
LANDFIRE classification remains modeled source evidence, not field inventory.

## Polygon generalization

The native classified raster and raw polygons are preserved.

The approved bounded Mescalero trial permits eligible P/PJ patches smaller
than 10,000 m² to become inclusions in edge-sharing P/PJ review units.

Generalization:
- Uses actual projected area.
- Requires shared edges, not corner-only contact.
- Preserves protected and uncertain features.
- Retains original class acreage and patch membership.
- Does not silently reclassify the native raster.
- Records parameters and limitations.

A generalized unit may contain both P and PJ.
Its display label must not be confused with its original-class composition.

Protected, isolated, or ineligible small patches may remain below one hectare.
The threshold is not permission to remove every small feature.

Recipient selection, tie-breaking, processing order, and unit labeling must be
approved and documented before implementation.

Generalized cover-type review polygons are not candidate stands.

## Mescalero pilot safeguards

Local definitions are recorded in:
docs/mescalero-cover-type-definitions.md

Pilot-specific policies include:
- Woodland is candidate forest land.
- Approved NT and NW classes remain candidate forest land.
- Low current canopy alone does not override that policy.
- Initial mapping uses candidate labels.
- One primary candidate class is assigned per cell.
- Unsupported local distinctions remain flagged or uncertain.

Public inputs do not directly measure:
- Species-specific crown-cover proportions.
- Exact overstory/understory composition.
- Basal area.
- Merchantability.
- Productivity.
- Field-verified stand composition.

Mescalero definitions and rules are not defaults for another geography.

## Intended deliverables

The review package will contain:
- Analysis boundary/reference information.
- Candidate cover-type and forest-land GeoTIFFs.
- Raw and generalized polygon layers in a GeoPackage.
- Membership and composition tables.
- Acreage CSVs and codebook.
- Generalization summary.
- Source manifest and parameters.
- QC, methods, limitations, and review flags.
- ArcGIS Pro opening instructions.
- A static map preview.

The GIS package is intended for professional use.
The preview and demonstration let reviewers understand the result without
installing ArcGIS.

Outputs remain preliminary and review-required.

## AI-agent interaction

Watsonx Orchestrate is the planned conversational host.

The intended agent will guide the user through the bounded workflow, call the
implemented MCP tools, explain actual results and limitations, and provide
the review package.

Host integration and file delivery must be demonstrated before they are
described as complete.

MCP Inspector is a development/testing interface, not proof of completed
conversational integration.

A remote artifact path alone is not a usable download.
The transfer mechanism must be verified.

## MCP tools

Only tools needed by the submitted workflow should be exposed to the agent.

Useful diagnostics, recovery functions, and lower-level processing code may
remain available to developers without being advertised to end users.

The current registered tool inventory must be obtained from the running
server and kept consistent with documentation.

Do not assume every historical tool is part of the submission.
Do not assume all intended tool names already exist.

Deprecated LANDFIRE routes are not used for new submissions.

## Deferred features

Future work:
- Candidate stand delineation.
- Physical-accessibility screening.
- Interactive merge negotiation.
- Map-click/chat integration.
- Generic cover-scheme onboarding.
- FIA-informed calibration.
- AlphaEarth enhancements.
- Change detection.
- Inventory strata.
- Post-fire analysis.

These are not required to complete this hackathon submission.

## Local development

Use a project-specific Python virtual environment.
Verify the declared dependencies and installed MCP package version.

Do not copy a virtual environment between workstations and VMs.
Do not assume cloud-hosted tools can read local laptop files.

For the existing Windows development workflow, activate the project environment
before running the installed MCP development command.

Example, subject to verification in the current environment:

    .\.venv\Scripts\Activate.ps1
    mcp dev server.py:mcp

If the command resolves to another Python installation, use the verified
environment-specific invocation rather than changing unrelated code.

Inspect requirements.txt and current environment compatibility before
installation or migration.

Run tests using the project environment:

    python -m pytest

Record results, skips, and environment details.
A test command shown here is not a claim that it has been run.

## Review in ArcGIS Pro

Open the completed package and check:
- Coordinate system and layer extent.
- Candidate class attributes.
- Generalized-unit membership and composition.
- Protected features.
- Fragmentation and unmerged-patch explanations.
- Acreage summaries.
- Geometry and QC results.
- Source and rule versions.
- Limitations and review flags.

Record the software version and actual review findings.

End users do not need QGIS.

## Evaluation

Evaluation distinguishes:
- Computational and GIS correctness.
- Generalization behavior.
- Agent tool selection and error handling.
- Reproducibility.
- Artifact delivery.
- Classification accuracy.

Synthetic tests and simulated failures are labeled as such.
Classification accuracy is claimed only when supported by defensible
independent references.

Visual review and acreage closure do not establish measured accuracy.

## Security and privacy

Use only public prototype data.
Do not include sensitive Tribal information, nonpublic plots, or credentials.

Sources and download locations are allowlisted.
Filesystem access is restricted to approved project directories.

LFPS contact email is used only for explicitly approved submission.
Do not persist raw email in code, logs, artifacts, screenshots, tests, or Git.
Valid email domains are not restricted to government addresses.

Generated outputs and locally approved configurations are excluded from Git
unless deliberately curated for public sharing.

Do not publish a local government workstation or expose an unauthenticated
endpoint to simplify integration.

## Limitations

MapCP does not establish:
- Ownership or trust status.
- Jurisdiction.
- Legal access.
- Commercial status or productivity.
- Tribal approval.
- Management authority.
- Field-verified cover types.
- Final stand boundaries.

Disturbance or barrier screening is not claimed where the relevant data and
method were not implemented.

Public modeled data may contain errors, scale limitations, and source-date
differences. Professional review remains necessary.

## Project documentation

- AGENTS.md: coding-assistant behavior and approval controls.
- docs/project-specification.md: scope, methods, outputs, and acceptance criteria.
- docs/mescalero-cover-type-definitions.md: local pilot reference definitions.
- Cover-type onboarding plan: future/general onboarding design; not proof of
  current implementation.

The current specification defines the bounded hackathon scope.
Older plans must not silently expand it.

## Completion

The local toolset is ready for host integration only when candidate mapping,
raw and generalized polygons, composition/membership, export, tests, and
ArcGIS review meet the specification.

The submission is ready only after agent interaction, artifact delivery,
evaluation, presentation, and the reviewed repository version are complete.

## License

License selection must be confirmed before public release.
Do not assume third-party code, dependencies, or data have identical licenses.