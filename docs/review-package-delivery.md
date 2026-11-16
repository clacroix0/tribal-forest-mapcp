# MapCP raster review package and private chat delivery

## Boundary-export compatibility checkpoint - November 16, 2026

### Source and status

Local VM working branch: `fix/full-boundary-export-compat`.

Base commit: `7cfb5bbc8b37ea8d61694a280de3aec3bc30199d`.

Historical pre-commit checkpoint: the compatibility edits and tests were
uncommitted when this section was first written. They were subsequently
committed as b3e45e6fc4915592420680a5bda36bdba449e688 and pushed to
`origin/fix/full-boundary-export-compat`, as confirmed by operator-provided
Git output on November 16, 2026. At that check, GitHub `main` remained at
the base commit above. Deployment of this compatibility repair remains
unverified.

This section supersedes older descriptions below only for the reviewed local
working-tree behavior and its dated tests. Historical deployment and sample
delivery observations remain historical evidence, not acceptance of this repair.

### Compatibility behavior

The exporter recognizes the boundary mapper's existing output representation
without rewriting original mapping artifacts:

- Accept `codebook_csv` as the codebook artifact-key alias only when
  `boundary_clipping_performed` is explicitly true. Conflicting canonical and
  alias references are rejected; controlled filename checks remain in force.
- Require nonnegative JSON integer boundary component counts. Outside-boundary
  cells plus inside-boundary EVT NoData cells must equal total NoData, and valid
  plus NoData cells must equal the recorded raster total.
- Permit boundary methods with the three successful Boolean closure checks and
  no legacy numeric closure totals. Any numeric closure totals supplied must
  still agree. Legacy runs retain the numeric-total requirements.
- Validate the two exact cover-type CSV component labels
  `outside_boundary_masked` and `evt_nodata_inside_boundary`. Both rows,
  including zero-count components, are required when the split representation
  is used. Validate code -9999, null forest-land status, integer counts, and
  area. Combine the two rows only in memory for aggregate raster-count QC.
  Legacy aggregate-NoData rows remain supported.
- Permit valid-only boundary forest-land summaries with codes 0, 1, and 2,
  including zero-count classes. Check CSV and methods summaries independently
  against raster counts. Reconcile NoData separately against methods and both
  rasters. Existing summaries that explicitly include NoData remain supported.
- Preserve unknown forest-land code 2 separately from NoData -9999 and
  nonforest code 0.

Generated `QC_AND_LIMITATIONS.json` records split cover-type NoData handling
and boundary forest-land summary validation where applicable. Original methods
and CSV bytes are preserved. Export does not independently authenticate approval
history or verify the geographic location of each reported NoData component.

No public tool schema, classification rule, crosswalk, forestry threshold,
connectivity rule, polygon tolerance, storage configuration, or deployment
setting is changed by this repair.

### Separate source and ZIP ceilings

- `MAX_SOURCE_BYTES`: 192 MiB, shared by the six mapping source artifacts and,
  when requested, the three raw-polygon source artifacts.
- `MAX_BYTES`: 100 MiB, unchanged ZIP ceiling.
- The source budget does not count generated package documents or the ZIP.
  The ZIP ceiling applies to the completed archive including generated members.
- Existing four-million-cell, 200,000-patch, metadata-size, temporary-space,
  and local-cache checks remain in place.

Sources may exceed 100 MiB only if they remain within 192 MiB and the resulting
ZIP remains within 100 MiB. The source increase is not permission to remove
other processing limits or proof of near-limit resource feasibility.
The ZIP is checked after compression; this is not an incremental ZIP-write cap.

### Operator-reported VM verification

Python executable used:

    /home/itzuser/.venvs/mapcp-py312/bin/python

Actual commands and reported results on November 16, 2026:

1. Actual synthetic producer integration:

       python -B -m pytest tests/test_boundary_export_integration.py -q -rs -p no:cacheprovider

   Result: 4 passed in 1.29 seconds; no reported failures or skips.

2. Size-policy subset in `tests/test_review_package_polygons.py`:

   Result: 7 passed, 103 deselected in 0.18 seconds; no reported failures or skips.

3. Combined related regression run:

       python -B -m pytest tests/test_boundary_export_integration.py tests/test_review_package_polygons.py tests/test_cover_type_patches.py -q -rs -p no:cacheprovider

   Result: 150 passed in 3.01 seconds; no reported failures or skips.

The producer integration uses actual local preview, boundary mapping, raw-polygon
generation, and export functions with tiny synthetic rasters, a synthetic
boundary, and a synthetic crosswalk. It covers no NoData, outside-only,
interior-only, and mixed NoData cases. Synthetic approval markers are test
fixtures, not real forestry approvals.

The size tests assert the production constants and exercise small, temporarily
scaled budgets with real file copying and compression. They check exact source
budget acceptance, one-byte source overflow, combined raster/polygon accounting,
compressible sources larger than the ZIP budget, oversized-ZIP rejection, and
failed-build staging cleanup. GIS validation is simulated in those size tests.

These results do not establish literal 192 MiB/100 MiB execution, exact-byte
ZIP-boundary acceptance, near-limit resource performance, or live storage
enforcement. Storage tests in the focused suite use simulated COS.

### Remaining acceptance work at the historical pre-commit checkpoint

This list records the earlier checkpoint, not a current task list. The later
sections record broader regression evidence, the real package build and review,
and subsequent Git and Orchestrate delivery observations.

- Review broader regression coverage beyond the three files reported above.
- Review and commit the complete change only after explicit approval; include
  the new producer integration test, which was untracked at this checkpoint.
- Separately approve a local package build from exact existing real mapping and
  raw-polygon run identifiers after confirming artifacts and resource readiness.
  Do not remap merely to repair export.
- Verify the real package's run identity, required members, extent, coverage,
  acreage, checksums, and completeness across the approved analysis boundary.
- Separately authorize any transfer/storage/deployment action and verify actual
  workstation delivery and ArcGIS Pro usability.
- Preserve the unresolved deployment-provenance, host-approval, concurrency,
  storage-policy, expiry/renewal, and recovery limitations recorded below.

No real forestry-artifact package build, live COS action, configuration change,
deployment, commit, or push is established by these tests.
This documentation edit is not new implementation verification.

### Accepted hackathon artifact and real delivery - November 16, 2026

The user accepted the delivered mapping and raw-polygon review package as-is
for the hackathon entry. No further classification, remapping, or generalization
is requested for this accepted artifact.

This is user acceptance for the hackathon demonstration. It does not establish
Tribal approval, independent classification accuracy, or separately verified
coverage of the approved full analysis boundary. It does not close other
submission or specification gates automatically.

#### Broader local regression evidence

Operator-reported VM command:

    MAPCP_REVIEW_EXPORT_ENABLED=false /home/itzuser/.venvs/mapcp-py312/bin/python -B -m pytest tests/test_boundary_mapping.py tests/test_boundary_mapping_preflight.py tests/test_boundary_export_integration.py tests/test_review_package_polygons.py tests/test_cover_type_patches.py -q -rs -p no:cacheprovider

Result: 271 passed in 3.87 seconds; no reported failures or skips.
This is a five-file regression run, not a full-repository test run.
The environment override applied to that test process, not Code Engine.

#### Accepted real-artifact package

- Mapping job: `f4111579-24a1-4923-bcb8-240d5e9f50f5`.
- Methods: `cmap_f4111579_v2_methods.json`.
- Crosswalk: `mescalero_v1_evt_crosswalk_v2`, version `v2`.
- Raw run: `rawpatch_f4111579_v2_20261116T194636_f80c64`.
- Package ID: `51b15397-90a8-4c9e-937d-ed6dee7d411c`.
- Scope: `preliminary_raster_and_raw_polygon_review`, schema `2`.
- Source artifacts: 133,201,516 bytes.
- ZIP: 12,281,096 bytes; 12 package members.
- ZIP SHA-256:
  `454c661d5cb667ea5e7d419092bed768637493705310ff7600f8a49ec4302d2d`.
- Local build runtime: 141.02 seconds.
- Reported process peak RSS: 1,183,020 KiB.
- Original source-file checksum preservation check: passed.
- Classification rerun: false.
- Storage upload by the local builder: false.

The local build used actual raster and polygon validation. These measurements
describe this run on the VM, not Code Engine capacity or near-limit performance.

#### Workstation transfer and review

The operator transferred the ZIP through a personal iCloud account accessed
from the VM, then downloaded and extracted it on Windows. This is a reported
manual workaround, not an approved production transfer mechanism and not
evidence of Orchestrate/COS delivery for this package.

Windows verification of `mapcp_raster_review (3).zip` reported the exact size
and SHA-256 above, with `MatchesExpected: True`.

Screenshot evidence shows the extracted files on Windows and raw candidate
cover-type polygons loaded and rendered in ArcGIS Pro. The user accepted the
artifact as-is for the hackathon. No additional workstation feature-count,
raster-comparison, acreage, or boundary-coverage checks are inferred.

#### Retained limitations and next host test

EVT codes 7012, 7057, and 7061 remain assigned to `unmapped_evt`.
No crosswalk change was made to remove these warnings.

The ZIP does not include the boundary file or a static preview. Do not describe
it as satisfying every final-package requirement. Independent accuracy,
approval-history authentication, separately verified approved-boundary
completeness, and the previously documented security limitations remain open.

At this historical pre-host-test checkpoint, the compatibility repair was
local and uncommitted. The later Git checkpoint below records its commit and
push. Execution of the repaired boundary-export path in the backend called by
Orchestrate remains unverified. Renewal of the existing stored package does not
establish that its original VM source artifacts are present in a deployed
container.

Before host testing, identify and approve the exact reviewed commit/build,
preserve required runtime configuration and artifacts, verify backend revision
and tool binding, and obtain approval for each consequential export/storage
operation. Do not remap merely to recover or demonstrate this accepted package.

This record authorizes no commit, push, deployment, cloud upload, or submission.

### Subsequent Git and Orchestrate delivery checkpoint - November 16, 2026

#### Git synchronization

Operator-provided Git output confirmed:

- VM branch: `fix/full-boundary-export-compat`.
- VM HEAD and matching GitHub branch:
  `b3e45e6fc4915592420680a5bda36bdba449e688`.
- Commit title: `Fix boundary mapping review export compatibility`.
- Working tree: clean at the time of the reported check.
- GitHub `main`: `7cfb5bbc8b37ea8d61694a280de3aec3bc30199d`.
- The compatibility fix was pushed to its branch but was not yet merged into
  `main` at that check.

These observations establish remote preservation of the committed branch,
not deployed-code parity.

#### Supervised Orchestrate renewal and user-confirmed contents

The user explicitly approved one supervised renewal of the existing accepted
public-prototype package
`51b15397-90a8-4c9e-937d-ed6dee7d411c`.

The pasted Orchestrate response reported successful renewal, a one-hour link,
expiration at `2026-11-16T23:36:41Z`, and the same package size and SHA-256
recorded above. The user subsequently confirmed that the downloaded package
contained all expected contents, including raw polygons.

This is operator-reported Orchestrate/COS delivery evidence for the existing
package, supplementing the earlier manual workstation-transfer record.
The complete tool activity trace was not supplied for this checkpoint;
exactly one invocation and absence of additional processing were not
independently verified. No fresh checksum calculation or additional ArcGIS Pro
inspection is inferred from the user's contents confirmation.

Platform-enforced approval remains unverified. The one-call conversational
approval does not demonstrate an enforced platform approval mechanism.

The successful renewal does not establish execution of the compatibility
repair in the deployed backend, a new package build, new mapping, independent
classification accuracy, or separately verified approved-boundary coverage.
Signed download URLs are intentionally omitted from this record.

---


Status updated November 13, 2026: the deployed exporter is enabled, and the user
confirmed successful download of a sample-area raster review ZIP.

This is a partial delivery milestone, not acceptance of the complete mapping
product. Full approved-boundary mapping, polygon-inclusive export, final ArcGIS
Pro review, and independent classification-accuracy evaluation remain incomplete
or unverified.

This document combines the original implementation contract, historical test
evidence, and the current deployment checkpoint. Historical test results do not
establish that the current recovered source or deployed image passed fresh tests.
Implementation details below must be checked against current source before
extending the exporter or treating them as current acceptance evidence.

## Polygon-inclusive export update — implementation draft, November 16, 2026

Status, November 16, 2026: applied on VM branch `feature/polygon-review-export`
(base `91d862c5611326436147363ebaca2c42e50388b9`). Superseded as to
deployment: see the November 16 sample delivery section below.

Observed on the VM with a Python 3.12 test virtual environment built from the
deployment pins, excluding the IBM COS SDK group (package versions not recorded
here): focused run of tests/test_review_package_polygons.py and
tests/test_cover_type_patches.py, 65 passed, 0 skipped; full tests run,
519 passed, 7 skipped (local Mescalero manifest, EVT-label, and crosswalk
artifacts). Storage tests use simulated COS; GIS tests use synthetic fixtures.

Not verified: MCP discovery, Orchestrate tool binding, export of a real mapped
run, live COS delivery or renewal, deployed-image build, and ArcGIS Pro opening.
The historical results below are dated evidence, not results for this change.

### Request and compatibility

The existing tool remains `export_arcgis_review_package`.
Create accepts `methods_filename` and optional `raw_run_directory` (a single
existing generated rawpatch folder name directly inside outputs, never a path).
Use exact identifiers returned by mapping and polygon tools; examples are not
artifact discovery. Renew continues to accept only `package_id`.

Omitting `raw_run_directory` preserves explicitly raster-only intermediate
export. Supplying it requires matching, complete raw polygons; failures do not
silently fall back to raster-only output. No mapping, new polygon run,
generalization, or imagery acquisition occurs during export. Validation does
reconstruct expected patches in memory to check actual geometry/attributes.

Polygon-inclusive packages add three members to the original nine:
- `raw_cover_type_patches.gpkg`
- `raw_patch_acreage.csv`
- `raw_patch_qc.json`

The raw layer is `candidate_cover_type_raw_patches`. Original QC references to
server paths are provenance, not promised portable file locations.
The opening guide, QC, and checksum manifest are updated. The raster methods
JSON is preserved unchanged: its polygon sentinel refers to the raster stage;
the separate raw-patch QC records the later polygon stage.

New polygon packages use schema `2` and scope
`preliminary_raster_and_raw_polygon_review`. Existing raster-only schema `1`
packages remain supported, including renewal. To avoid breaking old links, the
stored ZIP object name and download filename remain `mapcp_raster_review.zip`
for both versions; inspect scope and contents rather than infer from that name.

### Validation and limits

Validate run identity, exact source hashes, grid, successful raw-run status,
absence of a failure marker, and required saved QC. Snapshot only fixed files
from a validated nonsymbolic run directory. Reject symlink files and enforce
combined source-size and temporary-space checks.

Read the actual expected GeoPackage layer with a bounded feature count.
Reuse existing raw-patch rules to verify geometry, patch IDs, attributes,
connectivity, class flags, raster correspondence, NoData holes/gaps, per-class
acreage, saved QC totals, and acreage CSV. No new forestry rule or tolerance
is introduced. Generalized polygons, extra layers, or changed attributes are
not accepted as raw patches by this contract.

The original polygon-export checkpoint used limits of four million raster
cells, 200,000 raw patches, 100 MiB combined source artifacts, and 100 MiB ZIP.
The November 16 boundary-export compatibility working branch separates the
source ceiling (192 MiB) from the unchanged ZIP ceiling (100 MiB); see the
current checkpoint above. This is not evidence of deployed limits.
Polygon validation uses in-memory GIS operations and may be expensive near
these limits; verify resources before larger execution. Ceilings do not prove
that inputs near them are feasible.

### Focused verification

Run in an approved development environment from repository root:

    python -m pytest tests/test_review_package_polygons.py tests/test_cover_type_patches.py -q -rs

The new focused suite labels metadata/storage simulations and separately tests
real synthetic raster-to-polygon export. Actual GIS tests require Rasterio and
must not be counted as verified when skipped. The schema test isolates the
Pydantic request class; it does not prove live MCP discovery or host binding.
No historical comprehensive export suite is reconstructed by this change.

Required remaining checks include actual GIS execution, relevant existing
regression tests, current MCP discovery, build compatibility, preserved runtime
configuration and approval controls, separately approved live delivery/renewal,
and user-recorded ArcGIS Pro opening. No live COS result is implied by simulated
storage tests. Do not alter the live container for tests.

This update does not establish full-boundary coverage or final package
completion. Retain intermediate/sample labels until coverage, required layers,
preview, and applicable specification gates are demonstrated.

## Sample delivery and ArcGIS Pro review, November 16, 2026

Operator-reported observations, not independently reproduced by this document:

- A sample-area review ZIP of 30,456 bytes was exported and downloaded through
  the Orchestrate chat link in a browser. Its SHA-256 matched the value reported
  by the tool:
  `20d61c119d094601f7b0b28f5af8d7a8a189fd63d2936ee7c8b016d31a843d00`.
  This confirms download integrity only, not mapping accuracy.
- The package manifest reports schema version 2 and package scope
  `preliminary_raster_and_raw_polygon_review`. The ZIP contained the six
  original artifacts, the three generated documents, and the three polygon
  members: `raw_cover_type_patches.gpkg`, `raw_patch_acreage.csv` and
  `raw_patch_qc.json`.
- The operator opened the GeoPackage and the rasters in ArcGIS Pro 3.7.3 on a
  local workstation. The layers loaded without errors, and the cover-type
  classes looked plausible in an informal visual check. This is not an
  independent accuracy assessment or a systematic review of the codebook.
- The operator reported that Code Engine revision `tribal-forest-mapcp-00008`,
  receiving 100% of traffic, was deployed on the morning of November 16, 2026,
  and believes this was done from Cloud Shell. Eric was not involved. The Code
  Engine console shows an image in IBM Container Registry
  (`us.icr.io/gsa-hackathon-cr-student9/tribal-forest-mapcp`, referenced by
  digest) and no Code Engine image build. The Git commit or working-tree state
  used to build that image was not recorded, so the deployed code is not
  verified to equal any commit in Git.
- Before invoking `export_arcgis_review_package`, the agent displayed a
  chat-text request asking the user to confirm the exact filenames and
  directory. This was an agent-authored conversational confirmation. A
  platform-enforced approval control bound to the exact tool inputs, with denial
  preventing invocation, has not been demonstrated.

Not verified: full approved-boundary coverage, link expiry and renewal,
replacement-instance recovery, persistence of the export setting across
redeployment, build provenance of revision 00008, and independent accuracy.
The package remains a sample and an intermediate deliverable.

## Current deployment and delivery checkpoint — November 13, 2026

### Confirmed or user-reported observations

- Eric confirmed that he enabled review export through the Code Engine
  application environment variable `MAPCP_REVIEW_EXPORT_ENABLED=true`.
- The supplied configuration screenshot shows application
  `tribal-forest-mapcp`, revision `tribal-forest-mapcp-00006`, Ready and
  receiving 100% of traffic.
- The user confirmed that a sample-area review ZIP could be downloaded.
- The downloaded package contains candidate cover-type and forest-land
  rasters, acreage tables, codebooks, methods JSON, and an ArcGIS Pro guide.
- The user reported that recovered export code and supporting deployment
  requirements were committed and merged into `main`, and the VM synchronized.
  Obtain exact revision identifiers from Git history.

### Geographic and product limitations

- The delivered package covers a sample area, not the approved full project
  boundary.
- The current exporter is raster-only. It does not include candidate cover-type
  polygons or a polygon GeoPackage.
- The agent reported a raw-patch GeoPackage, but its current existence,
  availability, and delivery have not been independently verified.
- A successful download does not establish full coverage, mapping accuracy,
  complete package contents, replacement-instance recovery, or ArcGIS Pro
  acceptance.
- The intended end-user product covers the approved full project boundary.
  Small samples are development and testing aids, not substitutes for that
  deliverable.

### Export-enablement configuration

Location:

    Code Engine project ce-550000w6t0
    > Applications
    > tribal-forest-mapcp
    > Configuration
    > Environment variables

Exact setting:

    MAPCP_REVIEW_EXPORT_ENABLED=true

This is deployed application configuration, not evidence that the source-code
default has changed. Preserve and verify it during deployment updates and
explicitly configure it when creating a replacement application or environment.

Enabling export does not implement full-boundary mapping or polygon-inclusive
packaging. It also does not establish per-call human approval or resolve the
security and acceptance questions recorded below.

This documentation update authorizes no configuration changes, storage-policy
changes, live tests, deployment, cleanup, or additional processing.

## Scope and unchanged behavior

The documented implementation adds one MCP tool, `export_arcgis_review_package`,
without changing HTTP bearer protection, host validation, classification,
crosswalks, polygon processing, or Docker startup. The tested dependency adoption
is documented below.

The initial implementation exports only completed north-up 30 m EPSG:5070 raster
runs with NoData -9999, at most four million cells and 100 MiB total source
artifacts. All six mapping outputs are required. No arbitrary path, object key,
bucket, URL, shell, or code is accepted.

The original six artifacts remain unmodified. UUID-named local output directories
and private object prefixes prevent normal create requests from sharing keys.
Existing keys are checked and refused, never deliberately overwritten.

The existence check followed by upload is not atomic create-only protection:
a concurrent writer could create the key between those operations. UUIDs reduce
normal key collisions but do not establish an overwrite guarantee. Verify
vendor-supported conditional writes or approve an alternative. Live delivery is
now enabled, but the evidence recorded here does not establish that this
concurrency limitation has been resolved. Record its disposition explicitly;
download success does not close it.

Local builds are single-flight, enforce a free-disk-space check, and stop at 32
cached package directories. No local cache pruning is automatic; an administrator
must review cleanup separately. Separate processes/replicas are not coordinated.
The documented prototype constraint is single-instance deployment until a
concurrency review; verify the actual scaling configuration before relying on it.

## Input contract

Create:

    {"request": {"action": "create", "methods_filename": "cmap_23d30f23_v2_methods.json"}}

The methods filename above is an example, not an existing artifact reference.
Use the exact filename returned by the applicable successful mapping run.

Renew:

    {"request": {"action": "renew", "package_id": "<real package UUID>"}}

Use the real returned package UUID, never the explanatory placeholder.

Inputs are Pydantic-validated in the MCP wrapper; mutually exclusive operation
fields and strict identifiers are also validated by the delivery service.

## Package contents

Six original artifacts: two GeoTIFFs, three CSVs, and the original methods JSON.

Three generated documents:

- `OPEN_IN_ARCGIS_PRO.md`
- `QC_AND_LIMITATIONS.json`
- `PACKAGE_MANIFEST.json`

The manifest hashes all other members, not itself. The tool response includes
a separate SHA-256 for the complete ZIP.

Server paths inside the original methods document are preserved provenance, not
promised included source datasets. No private configs, credentials, or
directory-wide contents are included. Review flags/uncertainty remain in the
existing codebook, class rasters, source methods, and QC summary; no invented
spatial review layer is added.

The documented checks include:

- Success/write sentinels.
- All required files present and nonempty.
- No symlinks.
- Total size.
- Strict run/version identity.
- Single-band integer raster CRS/grid/NoData and provenance tags.
- Actual class histograms.
- Forest-land pixel agreement with the codebook.
- Methods and CSV class counts/acreage.
- Actual acreage closure.
- ZIP CRC and per-member SHA-256.

This is consistency QC, not independent accuracy, professional review,
approval-history authentication, or source-dictionary lineage validation.
The package explicitly states these limits. It does not resolve the previously
observed reference-table hash discrepancy or scheme approval metadata.

## Storage and secrets — configuration and outstanding verification

The original draft did not select a bucket. The deployed application now has
export enabled, and the configuration screenshot shows a review-storage secret
reference. This document does not record secret values or independently establish
the actual bucket, prefix, region, credential scope, retention policy, or storage
configuration.

Do not reuse platform/catalog/sandbox buckets without owner approval and
verification of policies and location. Do not unlock the COS service, make a
bucket public, or modify existing policies. Use a dedicated approved private
bucket or a scoped approved prefix.

Required runtime variables:

- `MAPCP_REVIEW_EXPORT_ENABLED`: disabled unless exactly `true`. The November 13
  deployed configuration sets this to `true`; other environments must be
  configured and approved separately.
- `MAPCP_REVIEW_COS_BUCKET`: approved bucket name.
- `MAPCP_REVIEW_COS_ENDPOINT`: public HTTPS IBM S3 endpoint for that bucket.
- `MAPCP_REVIEW_COS_REGION`: exact bucket signing region; do not infer it from
  the app.
- `MAPCP_REVIEW_COS_PREFIX`: approved prefix, default `mapcp-review/`.
- `MAPCP_REVIEW_COS_ACCESS_KEY_ID`: from an approved runtime secret.
- `MAPCP_REVIEW_COS_SECRET_ACCESS_KEY`: from an approved runtime secret.

HMAC signing and the IBM COS Python SDK are used. Secret field repr is suppressed.
Do not print SDK configuration, return raw exceptions, log signed URLs, or keep
signed URLs in manifests/records. Never paste credentials into chat or source.

SDK upload retries are disabled to avoid ambiguous duplicate submissions.
Bucket-level List permission may be needed to distinguish absent objects from
forbidden ones. Obtain the minimum vendor-supported permissions, scoped to this
location where possible; do not weaken policies after a denial.

Storage objects per package:

    <configured-prefix>/<package-uuid>/mapcp_raster_review.zip
    <configured-prefix>/<package-uuid>/package_record.json

The documented implementation uploads the ZIP and fully reads it back to verify
its SHA-256. A bounded package record is then uploaded and read back. Only then
is a one-hour presigned GET link returned. The client uses path-style addresses,
and the returned URL is checked against the configured HTTPS endpoint and
generated object path.

Links are bearer credentials: anyone who has the URL can use it during validity.
Expiration does not delete the stored ZIP. An approved retention/lifecycle policy
is still needed; this code does not create one. Failed uploads may leave orphan
objects. No cleanup or retries run automatically. A storage failure never returns
a fabricated link.

A new create request creates a distinct package. Explicit renew reads the stored
package record and fully reads back the ZIP to verify its size and SHA-256 before
issuing a link. Renewal requires no local artifacts, remapping, or re-upload, but
does perform remote reads and may incur transfer/request costs.

## Human approval and authorization — verification outstanding

This implementation does NOT prove human approval inside Python. No model-supplied
approval phrase or Boolean is treated as proof. `MAPCP_REVIEW_EXPORT_ENABLED` is an
administrator enable switch, NOT per-call approval evidence.

The original deployment requirement was to establish the controls below before
enablement. Export is now enabled, but the evidence recorded in this document
does not establish that these checks were completed. Record the actual control,
results, and any authorized interim operating restriction. Do not mark these
requirements satisfied merely because a download succeeded.

1. Configure the actual Orchestrate approval control for both create and renew.
2. Demonstrate denial/cancel produces NO tool invocation.
3. Demonstrate approval binds the exact requested operation and identifier.
4. Demonstrate changed inputs require a new approval.
5. Preserve reviewed, redacted evidence of the actual control behavior in approved
   storage. Exclude credentials and signed download URLs. If approval cannot be
   enforced, treat that as an unresolved blocker to further use and obtain an
   administrator decision rather than bypassing the requirement.

The current bearer token identifies access to one prototype deployment, not
individual users or tenants. This implementation assumes one approved project/team
and public prototype materials. Package UUIDs are identifiers, not a multi-tenant
access-control model. Do not claim tenant isolation or allow unrelated projects
without a separately approved authorization design.

Native chat attachments are not assumed. The user confirmed a working sample
download; record the actual chat-to-browser delivery path separately rather than
inferring attachment support.

## Local tests (no SDK or cloud credentials required)

    python3 -m unittest discover -s tests -p 'test_review_package*.py' -v

This is the documented test command, not evidence of a fresh November 13 run.
Verify that the test files are present in the recovered checkout before relying
on this command.

If rasterio/numpy are absent, three actual-GIS fixture tests are explicitly
skipped. Metadata tests use a SIMULATED raster-validator callback; storage tests
use in-memory SIMULATED COS. Those simulations do not establish live IBM SDK,
endpoint, account policy, signed-URL, or Orchestrate compatibility. Actual GIS
fixtures establish only the raster behavior exercised by those fixtures.

Do not install packages into or alter the live application container to run tests.
Registered MCP discovery and host approval still require explicit verification.

### Observed pre-hardening checkpoint — October 26, 2026

The operator built the local Python 3.12 image `mapcp-export-test:local`.
Dependency consistency and GIS imports passed. In a network-isolated container
with a read-only repository mount:

- Export suite: 45 tests passed, no skips, in 0.521 seconds. All three actual
  synthetic GeoTIFF tests executed.
- Regression suite: 535 passed, 7 skipped, 4 subtests passed, in 11.04 seconds.
- Skips: one server test requiring a local Mescalero manifest; two EVT-label
  tests requiring local reference/inventory artifacts; four cover-type mapping
  tests requiring local manifest/crosswalk prerequisites.

These are observed baseline results, not results for the subsequent hardening
patch or the current recovered/deployed version.

### Observed post-hardening checkpoint — October 26, 2026

The guarded five-file patch completed, and Python syntax checks passed.
The full regression suite then reported:

- 540 passed, 7 skipped, 38 subtests passed, in 10.69 seconds.
- No failures or errors were reported.
- The seven skips still concern local Mescalero reference artifacts.
- Added tests cover strict JSON integer statistics, malformed statistics rows,
  renewal read-back and corruption rejection, and malformed descriptor entries.

The run used the existing local image's dependencies with patched repository
source mounted read-only at `/workspace`, external networking disabled, temporary
writes confined to `/tmp`, and export disabled in the container environment.
Storage tests used simulated COS, not a live service. At this checkpoint, the
image's baked-in source had not been rebuilt with this patch.

No live COS, host-approval, real-data acceptance, or workstation-delivery result
is implied by this historical test run.

### Recovery verification — October 27, 2026

The October 26 counts above are historical operator-reported results preserved
from the conversation. They are NOT fresh test results for the recovered copy.

The recovery script checks the exact input and output SHA-256 of the four Python
files against the recorded draft and hardening receipts, and checks syntax
without importing the application. At this stage, fresh test execution remained
pending; the later October 27 recovery test run below superseded that pending
statement for that recovered version.

No live storage, deployment, Git commit, or push was performed by this recovery
step.

## Before the next deployment or configuration change

- Review the diff; no unrelated rewrite is authorized.
- Preserve existing mapping artifacts and any required manifests/source inputs
  before replacing an ephemeral application instance. Do not assume this Git
  checkout or the new revision has the previous instance's outputs. Never remap
  merely to restore export.
- Verify the actual application Dockerfile and dependency snapshot against the
  current repository and build process; see `review-export-dependency-plan.md`.
  Historical offline installation, imports, and regression results do not
  establish that the current recovered application image was rebuilt and tested.
- Verify the actual bucket/prefix, service credential scope, link lifetime, and
  approved retention arrangement. The documented link lifetime is 3600 seconds.
  Do not infer approval or policy configuration from download success.
- Plan storage test objects and costs, then obtain approval for those writes.
- For changed export behavior, test synthetic data before curated public pilot
  artifacts.
- Verify that deployment configuration preserves the required export,
  authentication, and host-validation settings.
- Obtain separate approval for the next deployment. The existing enabled
  deployment is not authorization to deploy recovered source or make additional
  configuration changes.

## Live acceptance checklist — current evidence and remaining checks

The November 13 user-confirmed sample download provides evidence for part of
item 4. The full access path and all other acceptance conditions must be recorded
separately. The checklist below is not a claim that no deployment or download has
occurred, nor that successful download satisfies every item.

1. Actual GIS consistency checks pass on the reviewed sample and negative cases.
2. Existing mapping/HTTP auth behavior and registered MCP inventory still pass.
3. Real COS put/head/get, complete read-back checksum, and signing work.
4. A user can download via the actual Orchestrate link in a browser without a
   cloud console, shared API token, kubectl, Cloud Shell, or QGIS.
5. ZIP checksum and contents match locally; layers open in ArcGIS Pro.
6. Expired link fails; a newly approved renewal works without mapping/upload.
7. Stored package/record can be renewed by a replacement app instance without
   its predecessor's filesystem. Test only after preservation and approval.
8. Service failures, missing/changed artifacts, unknown IDs, bad keys/endpoints,
   unsafe paths, denied permissions, and corruption return honest failure.
9. Human approval and project access conditions above are demonstrated.
10. Record results, limitations, review, and an approved committed version.

### Observed recovery test run — October 27, 2026

Fresh recovery regression run: 540 passed, 7 skipped, 38 subtests passed in
10.86 seconds. No failures or errors were reported. The seven skips concern
local Mescalero reference artifacts.

The rebuilt local image was `d4a23f5d30ab`, tagged `mapcp-export-test:local`.
Tests ran with networking disabled and the repository mounted read-only.

This result superseded the earlier pending recovery-test statement for the
October 27 recovered version. It is not a fresh regression result for the
November 13 recovered source or deployed image.

Live COS, host approval, real-data acceptance, and ArcGIS delivery were unverified
at this historical checkpoint. See the November 13 status section for the later
sample-download observation.

## Tested SDK dependency adoption — October 27, 2026

### Observed offline experiment, before repository adoption

- Python 3.12.16; 55 exact candidate package versions verified.
- Clean temporary venv, offline container, read-only repository and wheelhouse.
- pip check: no broken requirements. IBM SDK and GIS imports passed.
- Regression: 540 passed, 7 skipped, 38 subtests passed in 19.86 seconds.
- Skips remain local Mescalero reference-artifact cases.
- Container exit code 0; OOMKilled false. Repository unchanged by the experiment.
- Existing storage tests remain simulated; no real SDK storage request or client
  was created by the added import check. No live storage/signing result is implied.

The experiment changed only the temporary dateutil candidate to `2.9.0.post0` and
added the seven packages enumerated in `review-export-dependency-plan.md`. Every
other original dependency version was preserved. Source archive hashes were
verified before building; 55 runtime wheels and their hashes were retained.

### Local adoption and remaining build verification

The subsequent approved four-file patch adopted those tested versions in
`requirements-deploy.txt`, kept `requirements.txt` unchanged, and permitted source
packaging only for the three IBM SDK packages in the Docker install command.
It did not alter HTTP authentication, host validation, classification, forestry
rules, application startup, runtime user, or export enablement.

Replacement test image:

    sha256:cd1c3102ad9098d03483fd967f6838ca7a182ba027b9915a10eb39a94a4eb77d

Python base pull digest recorded by the operator:

    sha256:6dd8b6dab6b3adc7812bab69eca5dbdc1a5cc690ad28306d234ffb4ef8ac9753

The replacement contained libexpat1 `2.5.0-1+deb12u5`. It was a minimal test image,
not the application image. At this historical checkpoint, the revised application
Dockerfile had not been built or verified. Dependency/build hash enforcement and
build-tool locking were not established by this patch.

The November 13 deployment observation does not identify the build inputs or
demonstrate that the current Git Dockerfile reproduces the running image.

### Preserved evidence and Cloud Shell quota

Passing evidence archive:

    mapcp-sdk-passed-evidence-20261027T230213Z.tar.gz

SHA-256:

    d7c840e3bbd28be30b3c4fe61c9a6b71b99379a08a92be88d9f5579cb958ba70

The operator confirmed download to their computer.

A full temporary GIS venv under home exceeded Cloud Shell quota: that venv used
505M; home usage fell to 262M after its explicitly confirmed deletion. The
recorded home quota was 500 MB despite `df` showing much larger backing storage.
Preserve compact evidence off-workspace; do not default to repeating full
home-directory installs. The earlier interrupted install and missing Docker
images have no proven cause.

## Remaining verification and full-product work

The October evidence above remains historical. The November 13 checkpoint
supersedes the earlier statements that export is not deployed or enabled and
that no browser download has occurred.

The following still require explicit evidence or disposition:

- The non-atomic overwrite limitation and concurrency constraints.
- Current-image build provenance and fresh regression verification.
- Real SDK request/signing behavior and complete storage read-back verification.
- Actual host approval and project-access controls.
- Storage configuration, credential scope, and retention.
- Expired-link and renewal behavior.
- Replacement-instance recovery.
- Local ZIP integrity and ArcGIS Pro acceptance.
- Full approved-boundary processing and coverage/QC reporting.
- Polygon-inclusive packaging with matching acreage summaries and provenance.

A successful sample download does not independently verify these controls or
complete the intended product.

Prefer extending existing acquisition, mapping, polygon-processing, and export
components after reviewing current source and contracts. Do not assume that new
public tools are required, that full-boundary NAIP mosaics are mandatory, or that
removing processing limits is an acceptable scaling strategy.

Preserve the native candidate rasters and raw polygons. Generalization remains
optional and separately approved. Do not change forestry definitions, crosswalks,
thresholds, disturbance treatment, or minimum mapping units without approval.

All outputs remain preliminary and require professional forestry and GIS review.
They do not constitute Tribal approval, Realty verification, field inventory,
management authority, authoritative ownership or trust-status determination,
legal-access determination, or final management classes.

No additional bucket selection, credentials, live writes, policy changes,
deployment, commit, or push are authorized by this documentation update.
