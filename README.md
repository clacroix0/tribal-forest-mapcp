# Tribal Forest MapCP

Replacing the blank map—not the forester.

Tribal Forest MapCP is a 2026 GSA MCP Hackathon prototype helping understaffed
Tribal and BIA forestry programs prepare preliminary candidate forest-land and
cover-type mapping from public government data for inventory planning and Forest
Management Plan development.

Candidate cover-type mapping is the central purpose. Forest/nonforest screening
is a required companion, not a substitute. Outputs require professional review;
they are not field inventory, final stands, or approved management classes.

The intended end-user deliverable covers the explicitly approved project boundary
and includes candidate mapping layers, cover-type polygons, acreage summaries,
review flags, QC, provenance, and an ArcGIS Pro-compatible review package.
Small samples support development and testing; they are not the final product
for a full-boundary request.

## Status — November 13, 2026

This is an active prototype, not a production service. Status below separates
source-code presence, historical checkpoints, user-reported results, and observed
integration tests. November 10 observations remain dated evidence; they were not
automatically revalidated by the November 13 update.

| Component | Evidence and current limitation |
|---|---|
| Historical repository checkpoint | On November 10, the VM working copy was clean at commit `0a8983e`. After `git fetch origin`, local `main` and `origin/main` had zero unique commits on either side. This is a historical checkpoint, not the latest revision. |
| Source recovery | The user reported that recovered export code, supporting modules, and deployment requirements were committed and merged into `main`, and the VM was synchronized. Obtain exact current revision identifiers from Git history. Source synchronization does not establish which revision is deployed. |
| Pilot acquisition and mapping | Previously reported local progress includes public-boundary discovery/validation, NAIP review sampling, LFPS v2 collection, raster inspection, candidate cover-type/forest-land rasters, and raw patches. These results were not rerun during the November 10 documentation session. |
| Generalization and composition | Source and associated tests are tracked. Current test execution, output QC, and ArcGIS review must be checked before reporting completion. Generalization is optional and separately approved. |
| Boundary expansion | Acquisition, service-contract, mapping, and preflight modules and tests are tracked. File presence and successful preflight do not establish a demonstrated full-boundary workflow. |
| HTTP/container integration | `server_http.py`, `Dockerfile`, and deployment requirements are tracked. Commit history records an authenticated launcher and container GIS-import checks. A sample-package download subsequently worked, but this does not constitute a complete deployment or security regression test. |
| Orchestrate agent | An existing hosted MapCP agent with tools and knowledge attached was accessed through ADK 2.19.1 during the November 10 checkpoint. Agent configuration was exported. Verify the current hosted version against the reviewed repository configuration. |
| Runtime skill | During the November 10 checkpoint, `candidate-cover-mapping-review` was registered, attached, updated, selected automatically in a tested draft request, and its revised instructions appeared in the subsequent model input. Verify the current binding before relying on that historical result. |
| Agent reliability | The November 10 tested model response invented a manifest filename, expanded the initial checklist unnecessarily, and requested mapping approval prematurely. Later instructions were revised, but resolution of these reliability issues requires new tests. |
| Export and file delivery | On November 13, the user confirmed successful download of a sample-area review ZIP containing candidate cover-type and forest-land rasters, acreage tables, codebooks, methods JSON, and an ArcGIS Pro guide. The current exporter is raster-only. |
| Export configuration | Eric confirmed that `MAPCP_REVIEW_EXPORT_ENABLED=true` was set in the deployed Code Engine application configuration. This enables the existing exporter; it does not add mapping or polygon-packaging capabilities. |
| Geographic completeness | The downloaded package covers a sample area, not the approved full project boundary. Full-boundary mapping and delivery have not been demonstrated. |
| Polygon delivery | The agent reported a raw-patch GeoPackage, but its current availability and inclusion in a downloadable package have not been independently verified. A reported server-side path is not delivery. |
| ArcGIS acceptance | Successful ZIP download is not evidence that all packaged layers have been opened, checked, and accepted for professional review in ArcGIS Pro. Record that review separately. |
| Regression/accuracy | No fresh regression-suite result or defensible independent classification-accuracy estimate is claimed by this checkpoint. |

The observed skill behavior is a bounded draft-preview test, not proof of
end-to-end mapping reliability or of the deployed agent using the same revision.

Successful sample delivery does not establish full-boundary coverage, complete
polygon packaging, durable artifact retention, classification accuracy, or final
product acceptance.

## Architecture

```text
Forester in watsonx Orchestrate
          |
          | MCP tool calls using attached tool schemas
          v
MapCP Python server / approved HTTP deployment
          |
          +-- public boundary and source acquisition
          +-- input validation and approved classification configuration
          +-- candidate rasters and raw cover-type patches
          +-- optional approved generalized review polygons
          +-- QC, acreage/composition, provenance, review artifacts
          |
          v
Supported review-package creation and authorized delivery
          |
          v
Verified workstation transfer -> professional ArcGIS Pro review
```

Orchestrate is the conversational host, not the GIS processing engine. The runtime
skill supplies procedures; it does not implement missing tools, persistent storage,
server authorization, or file transfer. Coding assistants are not required for
end-user operation.

Repository code, the deployed container, hosted agent instructions, registered
tool schemas, and runtime skill configuration are separate components. Verify
their versions and bindings rather than assuming a change to one updates the
others.

## Mapping workflow and geographic scope

The intended end-user deliverable covers the explicitly approved project boundary.
Small samples remain useful for internal development and testing, but they do not
satisfy a full-boundary request.

The current demonstrated downloadable product is sample-only. Full-boundary
execution must retain bounded processing, resource checks, and explicit coverage
reporting rather than simply remove sample limits.

1. Establish geography, extent, objective, and approved forestry definitions.
2. Discover, select, and validate the public reference boundary.
3. Inspect source coverage, dates/version, CRS, resolution, alignment, and NoData.
4. Confirm the approved cover scheme, crosswalk version, and processing settings.
5. Produce candidate cover-type and companion candidate forest-land rasters.
6. Create raw connected same-class patches from the candidate raster.
7. If requested and separately approved, create generalized review polygons under
   the approved pilot rules.
8. When generalization is used, preserve raw-patch membership and original-class
   composition and acreage.
9. Review actual QC, provenance, uncertainty, parameters, and limitations.
10. Create the supported review package and separately verify delivery and ArcGIS
    use.

Use existing artifacts when available and suitable. Carry exact returned identifiers
between tools; collection manifests, methods JSON files, and raw-run directories
are not interchangeable. Do not repeat collection or remote submission simply
because an earlier artifact reference is missing.

Only tools attached to the current host are callable. Obtain the actual registered
inventory and schemas rather than treating this workflow or module names as proof
that every stage is exposed.

Respect current processing limits. Sample success does not prove full-boundary
processing support, and a successful preflight is not a completed mapping run.
Report requested extent, processed extent, coverage gaps, and NoData explicitly.
Do not present a sample as a full-boundary product.

Source requirements must follow the implemented, approved method. Do not assume
full-boundary NAIP imagery is required merely because NAIP was used for sample
visual review.

## Forestry method and pilot limitations

The pilot uses government-source evidence and approved, versioned configuration.
NAIP supplies visual-review context unless a separate analytical method is approved.
LANDFIRE classes are modeled vegetation evidence, not direct measurements of
species-specific crown cover, basal area, merchantability, or productivity.

Mescalero policies and class definitions are recorded in
`docs/mescalero-cover-type-definitions.md`. Approved woodland and NT/NW treatment
must not be overridden solely because current canopy is low. Do not transfer these
local rules to another geography without approval.

The inspected pilot classification used EVT crosswalking; EVC/EVH classification
and disturbance-history analysis must not be claimed without implementation and
execution evidence. Preserve NoData, unknown, mixed, disturbed, transitional, and
conflicting evidence according to approved rules.

Public FIA can support regional ecological plausibility and calibration. Altered
public plot coordinates are not exact pixel-level or stand-level reference labels.
Source agreement and acreage closure are not independent accuracy estimates.

Do not invent confidence percentages or treat modeled-source agreement as
field verification.

## Generalized review polygons are not stands

Preserve the native candidate raster and raw patches separately. Generalization
is an optional, separately approved operation, not a prerequisite for retaining
or delivering raw cover-type polygons.

The documented bounded Mescalero P/PJ trial uses a 10,000-square-meter threshold
and shared-edge eligibility, with protected/excluded features and deterministic
rules requiring review against the current implementation and approved
configuration.

A generalized unit may contain more than one original class. Its display label
must not be used as though all unit acreage belongs to the label's class. Use
membership and composition tables for original-class totals. Protected, isolated,
or ineligible small patches may remain below the threshold.

Do not imply smoothing, barrier protection, disturbance analysis, or final stand
delineation when the relevant method was not implemented and evaluated.

## Repository organization

Tracked components include:

- `server.py`: MCP server/tool integration.
- `server_http.py`, `Dockerfile`, `requirements-deploy.txt`: HTTP/container support.
- `review_package.py`, `review_package_storage.py`: review-package construction
  and storage/delivery support. The current exporter produces a raster-only
  package; verify current contracts and tests before extending it.
- `boundary_acquisition.py`, `boundary_mapping.py`,
  `boundary_mapping_preflight.py`, `boundary_service_contract.py`: boundary-related
  implementation; verify each current contract before use.
- `cover_scheme_models.py`, `cover_type_patches.py`,
  `cover_type_generalization.py`: configuration and polygon-processing components.
- `check_mcp_discovery.py`, `check_mcp_stdio.py`, `check_mcp_tool_calls.py`:
  development diagnostics; inspect side effects before invocation.
- `tests/`: automated tests; presence is not a passing test result.
- `docs/`: specifications, pilot definitions, installation notes, delivery
  documentation, plans, and backlog.
- `project_data/`: configuration/reference materials; see the tracking caveat below.

Agent YAML and runtime skills should be version-controlled as reviewed configuration,
separately from authentication files. Preserve deployment-specific bindings needed
for restoration in approved storage; do not publish secrets to improve portability.

Inspect the current repository before relying on this inventory. A tracked module
is not proof that its functions are registered, deployed, callable, or evaluated.

## Configuration tracking and reproducibility

The current `.gitignore` excludes new `project_data/` content by default, but the
November 10 Git inventory shows these files already tracked:

- `project_data/cover_schemes/mescalero_v1_cover_scheme_v1.json`
- `project_data/crosswalks/mescalero_v1_evt_crosswalk_v1.json`
- `project_data/crosswalks/mescalero_v1_evt_crosswalk_v2.json`
- `project_data/crosswalks/crosswalk_v2_review.csv`
- `project_data/reference_data/landfire/LF2025_EVT.csv`

Ignore rules do not stop tracking existing files. Inclusion in Git is not proof of
forestry approval, public-release clearance, or selection for the active run. Record
the actual version used; do not silently promote v2 because its filename is newer.
Review tracked content and licenses before publication. New local configurations and
important generated artifacts need a separate approved backup or deliberate curation.

For reproducible runs, record the source-code revision, source products and versions,
approved configuration identifiers, processing parameters, geographic extent, QC
results, and output artifact references. Record the deployed image/revision
separately where available; do not infer it from the current Git branch.

## Development and testing

The user reviews, applies, and runs changes directly with AI-assisted research,
planning, code review, and troubleshooting. Do not assume IBM Bob is in use or
required. Confirm the actual working environment before giving environment-specific
instructions.

Use the actual project environment and inspect `requirements.txt` and
`requirements-deploy.txt` before installation. GIS libraries may require OS runtime
dependencies. Do not copy virtual environments between machines or change system
Python to resolve a project-level problem.

From the repository root, using the verified project interpreter:

```bash
python -m pytest
```

This is an example command, not evidence it was run. Record interpreter/package
versions, command, test totals, failures/skips, and relevant GIS checks. Keep
synthetic fixtures and simulated failures clearly labeled.

Inspect the current launchers and deployment documentation for startup commands;
do not assume an old `mcp dev` example matches the installed MCP package. Cloud
Shell, the VM, the container, and the workstation have separate filesystems.

For Orchestrate, record the tested ADK version and active environment. Export the
current agent, import/update the skill, verify the agent binding, and test draft
behavior before any separately approved deployment. Never put API keys into the
agent YAML, skill, terminal command arguments, or repository.

Before major changes, define the plan, affected files, acceptance criteria, risks,
and tests. Obtain approval before implementation and consequential actions. Preserve
working behavior and avoid unrelated rewrites.

## Deployed review-export configuration

On November 13, Eric confirmed that review export was enabled in the deployed
Code Engine application using:

```text
MAPCP_REVIEW_EXPORT_ENABLED=true
```

Configuration location:

```text
Code Engine project ce-550000w6t0
> Applications
> tribal-forest-mapcp
> Configuration
> Environment variables
```

The exact variable name is `MAPCP_REVIEW_EXPORT_ENABLED`. This is application
configuration, not evidence that the source-code default has changed.

Preserve and verify this configuration during deployment changes. Do not assume
that a recreated application or a separate environment inherits it. Changes to
agent instructions or skill configuration do not replace backend configuration.

The flag enables existing export functionality. It does not independently
establish correct storage configuration, authorization enforcement, package
completeness, full-boundary coverage, polygon inclusion, independent mapping
accuracy, or professional GIS acceptance.

Keep deployment details in the relevant delivery documentation. Do not store
credentials, secret values, or signed download URLs in the README or repository.
Do not change deployment or weaken security controls solely to match a documented
example.

## Review package and evaluation

The required outcome is a preliminary ArcGIS Pro-compatible package covering the
approved project boundary, with completed candidate forest-land and cover-type
layers, cover-type polygons, acreage/composition CSVs, source/configuration
versions, methods, QC, limitations, review flags, and opening instructions.

Prefer a GeoPackage for completed vector review layers, with required rasters
provided in ArcGIS-compatible formats. Include generalized review polygons only
when requested, approved, and completed. Identify optional or unavailable layers
explicitly rather than silently omitting them.

### Current demonstrated export

The November 13 downloaded sample ZIP contains:

- Candidate cover-type and forest-land rasters.
- Acreage tables.
- Codebooks.
- Methods JSON.
- An ArcGIS Pro opening guide.

The current exporter does not include candidate cover-type polygons or a polygon
GeoPackage. The package is sample-area output, not a full-boundary deliverable.

A static preview remains a submission target; its existence and fidelity must be
demonstrated before claiming delivery.

### Separate acceptance checks

Verify these separately:

- Processing and artifact integrity.
- Requested extent versus actual processed coverage.
- Package contents and completeness.
- Durable storage and authorized download access.
- Transfer to the workstation.
- ArcGIS Pro opening, geometry/attributes, acreage, fragmentation, and professional
  review.

End users must not need QGIS. Record ArcGIS/software versions and actual findings.
Evaluate computational correctness, error handling, tool selection, reproducibility,
GIS quality, and delivery separately from independent classification accuracy.

A successful download is evidence of that transfer, not proof of long-term
retention, complete geographic coverage, correct classification, or usable polygon
layers.

## Security and safeguards

Use only approved public prototype data. Exclude sensitive Tribal information,
culturally sensitive locations, nonpublic plots, credentials, and transient contact
email from Git, logs, screenshots, and artifacts. Use contact email only for the
explicitly approved LFPS request; do not restrict valid email domains arbitrarily.

Use allowlisted HTTPS sources, bounded requests/retries, validated identifiers,
controlled output directories, and server-side authorization. Written approvals and
skills do not replace actual permission enforcement. Do not expose arbitrary
shell/code/SQL/filesystem operations through MCP.

Do not upload `.env`, Cloud Shell/Orchestrate credential configuration, virtual
environments, raw unreviewed traces, or signed download URLs. A private repository
is not permission to store credentials or restricted data.

Treat signed download URLs as temporary bearer credentials. Share them only for
requested delivery and redact them from troubleshooting evidence and evaluation
records.

Outputs establish no authoritative ownership, trust status, jurisdiction, legal
access, commercial status, productivity, Tribal approval, or management authority.

## Remaining work and scope

Complete and evaluate an end-to-end workflow across the approved full project
boundary, including candidate cover-type and forest-land mapping, cover-type
polygons, acreage summaries, review flags, QC, provenance, and a downloadable
ArcGIS Pro-compatible review package.

Use bounded internal tests and staged implementation without treating sample
delivery as the final product. Inspect and extend the existing acquisition,
mapping, polygon, and export implementations before adding new public tools.
Determine whether longer-running processing needs a job/status interface from
actual execution requirements, not assumptions.

Priority gaps include:

1. Verify the current committed code, deployed implementation, registered schemas,
   hosted instructions, and runtime skill.
2. Establish acceptance criteria for the approved full-boundary product.
3. Implement or complete full-boundary acquisition and mapping with explicit
   resource limits and coverage reporting.
4. Generate and validate corresponding cover-type polygons.
5. Extend export to include completed polygon layers and supporting artifacts.
6. Run regression, missing-data, partial-coverage, and service-failure tests.
7. Verify package transfer and actual ArcGIS Pro use.
8. Record evaluation evidence, methods, limitations, and reproducibility.
9. Complete the demo, presentation, security notes, and lessons learned.

Resolve documented agent-reliability issues without representing prompt changes as
validated improvements. Keep repository configuration and hosted versions aligned
through reviewed exports and explicit verification.

Next core milestones are objective-dependent candidate stands and physical-
accessibility screening; accessibility is not a legal-access determination.
Optional enhancements include FIA-informed workflows, AlphaEarth features, change
detection, inventory strata, and post-fire analysis. Preserve government-only
operation and do not drop cover types to add optional features.

## Documentation and license

Read `AGENTS.md`, `docs/project-specification.md`, pilot definitions, and relevant
installation and delivery notes. Keep working-role instructions and implementation
status consistent across these documents.

Treat old plans as plans, not evidence of implementation. Flag scope conflicts for
review rather than silently changing forestry requirements. Preserve historical
checkpoints with their dates instead of presenting them as current verification.

License selection and third-party code/data licensing must be confirmed before
public release. Do not assume all dependencies and government-hosted datasets have
identical redistribution terms.
