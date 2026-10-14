# Tribal Forest MapCP — Project Specification

Scope revision: 2026-10-09
Status: Hackathon completion specification; not a claim of implementation.

## 1. Mission

Help understaffed Tribal and BIA forestry programs replace a blank starting map
with transparent, preliminary candidate cover-type mapping for forest inventory
planning and Forest Management Plan development.

Tagline: Replacing the blank map—not the forester.

The central product is actual cover-type mapping with acreage, uncertainty,
provenance, and professional-review information.

## 2. Submission endpoint

The hackathon workflow ends with:
- Candidate cover-type mapping.
- Companion candidate forest-land mapping.
- Raw same-class patch polygons.
- Generalized candidate cover-type review polygons.
- Membership and original-class composition tables.
- Acreage, QC, review flags, methods, and provenance.
- An ArcGIS Pro-compatible package.
- A judge-friendly visual preview.
- A bounded AI-agent demonstration.

Generalized review polygons are required.
They are not candidate stands or approved management units.

The first reproducible workflow may use a bounded Mescalero pilot sample.
Do not claim full-reservation coverage or arbitrary-geography support unless
implemented and tested.

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

These remain future work and must not delay the required endpoint.

## 4. Authority and user decisions

The user approves forestry definitions, crosswalks, thresholds, source roles,
disturbance treatment, and polygon rules.

User approval of a pilot configuration does not establish Tribal approval or
management authority.

Local definitions are documented separately.
This specification does not redefine local cover-type codes.

Mescalero-specific decisions are not defaults for another Tribe or geography.

## 5. Input requirements

Validate and record:
- Public boundary source and selected record.
- Geometry validity and feature identifiers.
- Analysis extent versus broader reference boundary.
- CRS, units, and projected area.
- Source product, version, acquisition date, and lineage.
- Raster resolution, alignment, bands, coverage, and NoData.
- Actual EVT codes and metadata.
- Crosswalk, scheme, and rule versions.
- Missing inputs, partial coverage, and limitations.

Use public government sources for the core workflow.
NAIP is visual-review context unless a separate analysis method is approved.
LANDFIRE EVT is the initial classification basis.
EVC/EVH roles must match the approved rules.

Do not claim independent validation from modeled products with shared lineage.

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

For the approved Mescalero pilot:
- Woodland classes are candidate forest land.
- Approved NT and NW classes are candidate forest land.
- Low canopy alone does not override that policy.
- Unsupported assignment to NT/NW must not be invented.
- Unknown forest-land status is not false/nonforest.

Use the approved pilot treatment for consolidated riparian classes.
Do not claim unresolved local riparian subtypes are mapped.

## 7. Polygon products

### 7.1 Native classified raster

Preserve the classified raster unchanged.
Record its relationship to source products and the approved crosswalk.

### 7.2 Raw patch polygons

Create connected same-class patches using the documented approved connectivity.
Preserve stable patch identifiers within the run.

Retain:
- Original candidate class.
- Candidate forest-land status.
- Area and acreage.
- Review flags.
- Run and source references.

Validate geometry, gaps, overlaps, raster correspondence, and class acreage.

### 7.3 Generalized review polygons

Create a separate layer intended to reduce impractical fragmentation while
retaining source evidence.

Generalization groups raw patches; it does not change the native raster.

Required outputs:
- Generalized polygon geometry.
- Stable review-unit identifiers within the run.
- Raw-patch-to-unit membership table.
- Per-unit original-class composition table.
- Generalization parameters and rule version.
- Before/after QC and summaries.

## 8. Approved bounded generalization trial

The current Mescalero trial allows eligible small P and PJ patches to be
absorbed as inclusions into edge-sharing P/PJ review units.

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

### Unresolved implementation choices

Before implementation, obtain explicit approval for:
- Recipient ranking among multiple eligible neighbors.
- Tie-breaking.
- Processing order.
- Whether eligibility uses frozen original patch area throughout the pass.
- Whether merged units may receive subsequent inclusions.
- Treatment of an eligible patch with no eligible recipient.
- Display label for a unit containing both P and PJ.

Implement only the approved choices.
Save them as parameters, not undocumented code behavior.

Do not introduce smoothing, simplification, buffering, hole filling, or
reclassification without separate approval.

### Composition and labeling

Each raw patch must belong to exactly one generalized unit.

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

## 9. Generalization acceptance criteria

Required:
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
13. Visual review in ArcGIS is recorded.

A lower polygon count alone does not demonstrate success.
Do not invent a target reduction percentage.

## 10. Final review package

Required contents:
- Validated analysis boundary and reference information.
- Candidate cover-type GeoTIFF.
- Candidate forest-land GeoTIFF.
- GeoPackage with raw and generalized cover-type polygons.
- Raw-patch membership table.
- Generalized-unit composition table.
- Cover-type and forest-land acreage CSVs.
- Generalization summary and unmerged-patch reasons.
- Codebook.
- Source manifest.
- Parameters and approved configuration references.
- Methods, QC, and limitations.
- ArcGIS Pro opening instructions.
- A static map preview readable without GIS software.

Where appropriate, multiple attributes belong on one polygon layer.
Do not create duplicate geometry layers solely for each attribute.

Use controlled filenames and run identifiers.
Do not overwrite existing outputs automatically.

Export must verify required artifacts exist and are valid.
It must not package missing outputs as if the workflow succeeded.

Verify transfer from the execution environment to the ArcGIS workstation.
A remote filesystem path is not a completed download mechanism.

## 11. MCP interface

Expose a coherent set of tools needed to finish the bounded workflow.
Do not enforce an arbitrary tool count.

Workflow capabilities include:
- Boundary discovery and selection.
- Input validation and source inspection.
- Necessary source preparation/acquisition.
- Asynchronous job submission, status, and collection.
- Candidate mapping.
- Polygon generation/generalization.
- Review-package export.

Exact registered names are determined from the current repository.
A capability listed here is not proof that its tool exists.

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

Expose no unrestricted shell, code, SQL, URLs, or filesystem operations.

## 12. Conversational interaction

Watsonx Orchestrate is the planned host; integration must be verified.

The agent should:
- Resolve the project/sample and required artifacts.
- Explain available data and limitations.
- Use approved pilot configurations.
- Request explicit approval for consequential actions.
- Invoke real tools.
- Explain actual acreage and QC results.
- Provide a usable package handoff.
- Never describe generalized units as stands.

Do not build interactive merge negotiation for this submission.
The approved deterministic generalization run and professional GIS review are
sufficient for the bounded workflow.

Human approval must be bound to the reviewed action and inputs.
A model-generated approval phrase alone is insufficient.

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

Keep core Python portable.
Verify dependencies, permissions, persistence, and transport in each environment.
Do not copy virtual environments between machines.

LFPS contact email is used only for approved submission.
Do not persist raw email in artifacts, logs, documentation, tests, or Git.
Accept valid email domains without an agency-domain restriction.

Use only public prototype data.
Review local configurations before publishing curated examples.
Keep secrets and generated outputs out of Git.

Do not publish unauthenticated endpoints or expose government workstations.

## 14. Evaluation

Evaluate separately:
- Tool/request validity.
- Workflow completion and failures.
- GIS correctness.
- Generalization behavior.
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
- Threshold equality.
- Shared-edge and corner-only contact.
- Protected patches.
- Multiple candidate recipients and ties.
- Unmergeable patches.
- Membership and composition closure.
- Repeated-run determinism.
- Export completeness.

Use synthetic fixtures for controlled cases and label them clearly.
Record actual tests, runtime, skips, failures, and review evidence.

Measure classification accuracy only with defensible independent references.
Do not confuse computational QC or visual plausibility with measured accuracy.

## 15. Completion gates

### Local toolset ready for host integration

- Candidate mapping is reproducible.
- Raw and generalized polygons meet acceptance criteria.
- Approved merge choices are recorded.
- Membership and composition outputs are complete.
- Export package is complete.
- Relevant tests pass.
- Advertised tools match the submitted workflow.
- ArcGIS review and limitations are recorded.
- Documentation matches current implementation.

### Submission ready

Additionally:
- Host connection and agent calls are demonstrated.
- Artifact retrieval is verified.
- Actual evaluation is documented.
- Repository includes reproducible instructions and curated examples.
- Presentation and recorded demonstration are prepared.
- Judges can understand outputs without ArcGIS.
- Security notes and lessons learned are included.
- The reviewed version is committed.

## 16. Implementation status

At this scope revision:
- Source acquisition and inspection have been demonstrated locally.
- Candidate raster mapping has been demonstrated in the pilot workflow.
- Raw patch generation has been demonstrated in the pilot workflow.
- Generalized review polygons are required but not verified complete.
- Final packaged export is not verified complete.
- Watsonx interaction and remote artifact delivery are not verified complete.
- Stand delineation and other deferred features are outside submission scope.

These statements summarize reported progress, not a fresh repository audit.
Update them only with current source, test, artifact, and review evidence.