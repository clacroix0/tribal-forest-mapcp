```markdown
# MapCP raster review package and private chat delivery

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
```
