# Tribal Forest MapCP

Replacing the blank map—not the forester.

Tribal Forest MapCP is a 2026 GSA MCP Hackathon prototype helping understaffed
Tribal and BIA forestry programs prepare preliminary candidate forest-land and
cover-type mapping from public government data for inventory planning and Forest
Management Plan development.

Candidate cover-type mapping is the central purpose. Forest/nonforest screening
is a required companion, not a substitute. Outputs require professional review;
they are not field inventory, final stands, or approved management classes.

## Status — November 10, 2026

This is an active prototype, not a production service. Status below separates
source-code presence, previously reported progress, and observed integration tests.

| Component | Evidence and current limitation |
|---|---|
| Repository checkpoint | The VM working copy was clean at commit `0a8983e`. After `git fetch origin`, local `main` and `origin/main` had zero unique commits on either side. This describes the pre-documentation-update checkpoint, not a permanent latest revision. |
| Pilot acquisition and mapping | Previously reported local progress includes public-boundary discovery/validation, NAIP review sampling, LFPS v2 collection, raster inspection, candidate cover-type/forest-land rasters, and raw patches. These results were not rerun during the November 10 documentation session. |
| Generalization and composition | Source and associated tests are tracked. Current test execution, output QC, and ArcGIS review must be checked before reporting completion. |
| Boundary expansion | Acquisition, service-contract, mapping, and preflight modules and tests are tracked. File presence does not establish a demonstrated full-reservation workflow. |
| HTTP/container integration | `server_http.py`, `Dockerfile`, and deployment requirements are tracked. Commit history records an authenticated launcher and container GIS-import checks. Live deployment behavior was not revalidated in this checkpoint. |
| Orchestrate agent | An existing hosted MapCP agent with tools and knowledge attached was accessed through ADK 2.19.1. Agent configuration was exported. |
| Runtime skill | `candidate-cover-mapping-review` was registered, attached, updated, selected automatically in a tested draft request, and its revised instructions appeared in the subsequent model input. |
| Agent reliability | The tested model response still invented a manifest filename, expanded the initial checklist unnecessarily, and requested mapping approval prematurely. Prompt tuning was paused; these limitations remain open. |
| Export and file delivery | Final package completeness, durable storage, download access, and workstation transfer require separate evidence. A server-side path is not delivery. |
| Regression/accuracy | No fresh regression-suite result or defensible independent classification-accuracy estimate is claimed by this checkpoint. |

The observed skill behavior is a bounded draft-preview test, not proof of end-to-end
mapping reliability or of the deployed agent using the same revision.

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
          +-- candidate rasters, raw patches, generalized review units
          +-- QC, acreage/composition, provenance, review artifacts
          |
          v
Verified file delivery -> professional ArcGIS Pro review
```

Orchestrate is the conversational host, not the GIS processing engine. The runtime
skill supplies procedures; it does not implement missing tools, persistent storage,
server authorization, or file transfer. Coding assistants are not required for
end-user operation.

## Bounded mapping workflow

1. Establish geography, extent, objective, and approved forestry definitions.
2. Discover, select, and validate the public reference boundary.
3. Inspect source coverage, dates/version, CRS, resolution, alignment, and NoData.
4. Confirm the approved cover scheme, crosswalk version, and processing settings.
5. Produce candidate cover-type and companion candidate forest-land rasters.
6. Create raw connected same-class patches from the candidate raster.
7. Create separate generalized review polygons under approved pilot rules.
8. Preserve raw-patch membership and original-class composition and acreage.
9. Review actual QC, provenance, uncertainty, parameters, and limitations.
10. Create the supported review package and separately verify delivery and ArcGIS use.

Use existing artifacts when available and suitable. Carry exact returned identifiers
between tools; collection manifests, methods JSON files, and raw-run directories
are not interchangeable. Do not repeat collection or remote submission simply
because an earlier artifact reference is missing.

Only tools attached to the current host are callable. Obtain the actual registered
inventory and schemas rather than treating this workflow or module names as proof
that every stage is exposed. Respect sample limits; sample success does not prove
full-boundary processing support.

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

## Generalized review polygons are not stands

Preserve the native candidate raster and raw patches separately. The documented
bounded Mescalero P/PJ trial uses a 10,000-square-meter threshold and shared-edge
eligibility, with protected/excluded features and deterministic rules requiring
review against the current implementation and approved configuration.

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
- `boundary_acquisition.py`, `boundary_mapping.py`,
  `boundary_mapping_preflight.py`, `boundary_service_contract.py`: boundary-related
  implementation; verify each current contract before use.
- `cover_scheme_models.py`, `cover_type_patches.py`,
  `cover_type_generalization.py`: configuration and polygon-processing components.
- `check_mcp_discovery.py`, `check_mcp_stdio.py`, `check_mcp_tool_calls.py`:
  development diagnostics; inspect side effects before invocation.
- `tests/`: automated tests; presence is not a passing test result.
- `docs/`: specifications, pilot definitions, installation notes, plans, and backlog.
- `project_data/`: configuration/reference materials; see the tracking caveat below.

Agent YAML and runtime skills should be version-controlled as reviewed configuration,
separately from authentication files. Preserve deployment-specific bindings needed
for restoration in approved storage; do not publish secrets to improve portability.

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

## Development and testing

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

## Review package and evaluation

The required outcome is a preliminary ArcGIS Pro-compatible package with completed
layers, acreage/composition CSVs, source/configuration versions, methods, QC,
limitations, review flags, and opening instructions. A static preview is a submission
target; its existence and fidelity must be demonstrated before claiming delivery.

Verify these separately:

- Processing and artifact integrity.
- Package contents and completeness.
- Durable storage and authorized download access.
- Transfer to the workstation.
- ArcGIS Pro opening, geometry/attributes, acreage, fragmentation, and professional review.

End users must not need QGIS. Record ArcGIS/software versions and actual findings.
Evaluate computational correctness, error handling, tool selection, reproducibility,
GIS quality, and delivery separately from independent classification accuracy.

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

Outputs establish no authoritative ownership, trust status, jurisdiction, legal
access, commercial status, productivity, Tribal approval, or management authority.

## Remaining work and scope

First complete the bounded, evaluated cover-type workflow, export/delivery,
professional review, reproducible configuration, repository, demo, and presentation.
Resolve documented agent-reliability issues without representing prompt changes as
validated improvements.

Next core milestones are objective-dependent candidate stands and physical-
accessibility screening; accessibility is not a legal-access determination.
Optional enhancements include FIA-informed workflows, AlphaEarth features, change
detection, inventory strata, and post-fire analysis. Preserve government-only
operation and do not drop cover types to add optional features.

## Documentation and license

Read `AGENTS.md`, `docs/project-specification.md`, pilot definitions, and relevant
installation notes. Treat old plans as plans, not evidence of implementation; flag
scope conflicts for review rather than silently changing forestry requirements.

License selection and third-party code/data licensing must be confirmed before
public release. Do not assume all dependencies and government-hosted datasets have
identical redistribution terms.
