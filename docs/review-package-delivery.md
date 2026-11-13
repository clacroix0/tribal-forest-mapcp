# MapCP raster review package and private chat delivery — draft

Status: prepared for review; not deployed or enabled. This does not complete
polygon/generalization deliverables or independent accuracy evaluation.

## Scope and unchanged behavior

Adds one MCP tool, export_arcgis_review_package, without changing HTTP bearer
protection, host validation, classification, crosswalks, polygon processing,
or Docker startup. The tested dependency adoption is documented below.
It initially exports only
completed north-up 30 m EPSG:5070 raster runs with NoData -9999, at most four
million cells and 100 MiB total source artifacts. All six mapping outputs are
required. No arbitrary path, object key, bucket, URL, shell or code is accepted.
The original six artifacts remain unmodified. UUID-named local output directories
and private object prefixes prevent normal create requests from sharing keys.
Existing keys are checked and refused, never deliberately overwritten.
The existence check followed by upload is not atomic create-only protection:
a concurrent writer could create the key between those operations. UUIDs reduce
normal key collisions but do not establish an overwrite guarantee. Verify
vendor-supported conditional writes or approve an alternative before enabling
live delivery.
Local builds are single-flight, enforce a free-disk-space check, and stop at 32
cached package directories. No local cache pruning is automatic; an administrator
must review cleanup separately. Separate processes/replicas are not coordinated;
retain the prototype single-instance deployment until a concurrency review.

## Input contract

Create:

    {"request": {"action": "create", "methods_filename": "cmap_23d30f23_v2_methods.json"}}

Renew (use the real returned UUID, never this explanatory placeholder):

    {"request": {"action": "renew", "package_id": "<real package UUID>"}}

Inputs are Pydantic-validated in the MCP wrapper; mutually exclusive operation
fields and strict identifiers are also validated by the delivery service.

## Package contents

Six original artifacts: two GeoTIFFs, three CSVs and the original methods JSON.
Three generated documents: OPEN_IN_ARCGIS_PRO.md, QC_AND_LIMITATIONS.json and
PACKAGE_MANIFEST.json. The manifest hashes all other members, not itself.
The tool response includes a separate SHA-256 for the complete ZIP. Server paths
inside the original methods document are preserved provenance, not promised
included source datasets. No private configs, credentials or directory-wide
contents are included. Review flags/uncertainty remain in the existing codebook,
class rasters, source methods and QC summary; no invented spatial review layer.

Checks: success/write sentinels, all required files present and nonempty, no
symlinks, total size, strict run/version identity, single-band integer raster
CRS/grid/NoData and provenance tags, actual class histograms, forest-land pixel
agreement with the codebook, methods and CSV class counts/acreage, actual closure,
ZIP CRC and per-member SHA-256. This is consistency QC, not independent accuracy,
professional review, approval-history authentication or source-dictionary lineage
validation. The package explicitly states these limits. It does not resolve the
previously observed reference-table hash discrepancy or scheme approval metadata.

## Storage and secrets — configure only after separate approval

No real bucket is selected by this draft. Do not reuse platform/catalog/sandbox
buckets without owner approval and verification of policies and location.
Do not unlock the COS service, make a bucket public, or modify existing policies.
Use a dedicated approved private bucket or a scoped approved prefix.

Required runtime variables (values are deliberately not provided here):

- MAPCP_REVIEW_EXPORT_ENABLED: disabled unless exactly true. Keep unset for now.
- MAPCP_REVIEW_COS_BUCKET: approved bucket name.
- MAPCP_REVIEW_COS_ENDPOINT: public HTTPS IBM S3 endpoint for that bucket.
- MAPCP_REVIEW_COS_REGION: exact bucket signing region; do not infer it from the app.
- MAPCP_REVIEW_COS_PREFIX: approved prefix, default mapcp-review/.
- MAPCP_REVIEW_COS_ACCESS_KEY_ID: from an approved runtime secret.
- MAPCP_REVIEW_COS_SECRET_ACCESS_KEY: from an approved runtime secret.

HMAC signing and the IBM COS Python SDK are used. Secret field repr is suppressed.
Do not print SDK configuration, return raw exceptions, log signed URLs or keep
signed URLs in manifests/records. Never paste credentials into chat or source.
SDK upload retries are disabled to avoid ambiguous duplicate submissions.
Bucket-level List permission may be needed to distinguish absent objects from
forbidden ones. Obtain the minimum vendor-supported permissions, scoped to this
location where possible; do not weaken policies after a denial.

Storage objects per package:

    <configured-prefix>/<package-uuid>/mapcp_raster_review.zip
    <configured-prefix>/<package-uuid>/package_record.json

The ZIP is uploaded and fully read back to verify its SHA-256. A bounded package
record is then uploaded and read back. Only then is a one-hour presigned GET link
returned. The client uses path-style addresses and the returned URL is checked
against the configured HTTPS endpoint and generated object path. Links are bearer
credentials: anyone who has the URL can use it during validity. Expiration does
not delete the stored ZIP. An approved retention/lifecycle policy is still needed;
this code does not create one. Failed uploads may leave orphan objects. No cleanup
or retries run automatically. A storage failure never returns a fabricated link.
A new create request creates a distinct package; explicit renew reads the stored
package record and fully reads back the ZIP to verify its size and SHA-256 before
issuing a link. Renewal requires no local artifacts, remapping or re-upload, but
does perform remote reads and may incur transfer/request costs.

## Human approval and authorization — deployment blocker

This implementation does NOT prove human approval inside Python. No model-supplied
approval phrase or Boolean is treated as proof. MAPCP_REVIEW_EXPORT_ENABLED is an
administrator enable switch, NOT per-call approval evidence. Before enabling it:

1. Configure the actual Orchestrate approval control for both create and renew.
2. Demonstrate denial/cancel produces NO tool invocation.
3. Demonstrate approval binds the exact requested operation and identifier.
4. Demonstrate changed inputs require a new approval.
5. Preserve the actual trace as evidence. If this cannot be enforced, do not enable.

The current bearer token identifies access to one prototype deployment, not
individual users or tenants. This draft assumes one approved project/team and
public prototype materials. Package UUIDs are identifiers, not a multi-tenant
access-control model. Do not claim tenant isolation or allow unrelated projects
without a separately approved authorization design. Native chat attachments are
not assumed; test an ordinary returned link in the real chat interface.

## Local tests (no SDK or cloud credentials required)

    python3 -m unittest discover -s tests -p 'test_review_package*.py' -v

If rasterio/numpy are absent, three actual-GIS fixture tests are explicitly
skipped. Metadata tests use a SIMULATED raster-validator callback; storage tests
use in-memory SIMULATED COS. Those simulations do not establish live IBM SDK,
endpoint, account policy, signed-URL or Orchestrate compatibility. Actual GIS
fixtures establish only the raster behavior exercised by those fixtures.
Do not install packages into or alter the live application container to run tests.
Registered MCP discovery and host approval still require explicit verification.

### Observed pre-hardening checkpoint - October 26, 2026

The operator built the local Python 3.12 image mapcp-export-test:local. Dependency
consistency and GIS imports passed. In a network-isolated container with a
read-only repository mount:
- Export suite: 45 tests passed, no skips, in 0.521 seconds. All three actual
  synthetic GeoTIFF tests executed.
- Regression suite: 535 passed, 7 skipped, 4 subtests passed, in 11.04 seconds.
- Skips: one server test requiring a local Mescalero manifest; two EVT-label
  tests requiring local reference/inventory artifacts; four cover-type mapping
  tests requiring local manifest/crosswalk prerequisites.
These are observed baseline results, not results for the subsequent hardening
patch.

### Observed post-hardening checkpoint - October 26, 2026

The guarded five-file patch completed, and Python syntax checks passed.
The full regression suite then reported:
- 540 passed, 7 skipped, 38 subtests passed, in 10.69 seconds.
- No failures or errors were reported.
- The seven skips still concern local Mescalero reference artifacts.
- Added tests cover strict JSON integer statistics, malformed statistics rows,
  renewal read-back and corruption rejection, and malformed descriptor entries.

The run used the existing local image's dependencies with patched repository
source mounted read-only at /workspace, external networking disabled, temporary
writes confined to /tmp, and export disabled in the container environment.
Storage tests used simulated COS, not a live service. The image's baked-in source
has not been rebuilt with this patch.
No live COS, host-approval, real-data acceptance, or workstation-delivery result
is implied.

### Recovery verification - October 27, 2026

The October 26 counts above are historical operator-reported results preserved
from the conversation. They are NOT fresh test results for the recovered copy.
The recovery script checks the exact input and output SHA-256 of the four Python
files against the recorded draft and hardening receipts, and checks syntax
without importing the application. Fresh test execution remains pending.
No live storage, deployment, Git commit or push is performed by this recovery.

## Before deployment

- Review the diff; no unrelated rewrite is authorized.
- Preserve today's six artifacts and any required manifests/source inputs before
  replacing the ephemeral application instance. Do not assume this Git checkout
  or the new revision has today's outputs. Never remap merely to restore export.
- Verify the revised application Dockerfile with the adopted dependency snapshot;
  see review-export-dependency-plan.md. Offline installation, imports and regression
  passed; a build and verification of the revised application image remain pending.
- Approve the actual bucket/prefix, service credential scope, link lifetime
  (proposal: 3600 seconds) and retention separately.
- Plan storage test objects and costs, then obtain approval for those writes.
- Test the export with synthetic data before curated public pilot artifacts.
- Test approved deployment separately; do not deploy this draft by default.

## Live acceptance still required

1. Actual GIS consistency checks pass on the reviewed sample and negative cases.
2. Existing mapping/HTTP auth behavior and registered MCP inventory still pass.
3. Real COS put/head/get, complete read-back checksum and signing work.
4. A user can download via the actual Orchestrate link in a browser without a
   cloud console, shared API token, kubectl, Cloud Shell, or QGIS.
5. ZIP checksum and contents match locally; layers open in ArcGIS Pro.
6. Expired link fails; a newly approved renewal works without mapping/upload.
7. Stored package/record can be renewed by a replacement app instance without
   its predecessor's filesystem. Test only after preservation and approval.
8. Service failures, missing/changed artifacts, unknown IDs, bad keys/endpoints,
   unsafe paths, denied permissions and corruption return honest failure.
9. Human approval and project access conditions above are demonstrated.
10. Record results, limitations, review, and an approved committed version.

### Observed recovery test run - October 27, 2026

Fresh recovery regression run: 540 passed, 7 skipped, 38 subtests passed in 10.86 seconds.
No failures or errors were reported. The seven skips concern local Mescalero reference artifacts.
The rebuilt local image was d4a23f5d30ab, tagged mapcp-export-test:local.
Tests ran with networking disabled and the repository mounted read-only.
This result supersedes the pending recovery-test statement above.
Live COS, host approval, real-data acceptance and ArcGIS delivery remain unverified.

## Tested SDK dependency adoption - October 27, 2026

### Observed offline experiment, before repository adoption

- Python 3.12.16; 55 exact candidate package versions verified.
- Clean temporary venv, offline container, read-only repository and wheelhouse.
- pip check: no broken requirements. IBM SDK and GIS imports passed.
- Regression: 540 passed, 7 skipped, 38 subtests passed in 19.86 seconds.
- Skips remain local Mescalero reference-artifact cases.
- Container exit code 0; OOMKilled false. Repository unchanged by the experiment.
- Existing storage tests remain simulated; no real SDK storage request or client
  was created by the added import check. No live storage/signing result is implied.

The experiment changed only the temporary dateutil candidate to 2.9.0.post0 and
added the seven packages enumerated in review-export-dependency-plan.md. Every
other original dependency version was preserved. Source archive hashes were
verified before building; 55 runtime wheels and their hashes were retained.

### Local adoption and remaining build verification

The subsequent approved four-file patch adopts those tested versions in
requirements-deploy.txt, keeps requirements.txt unchanged, and permits source
packaging only for the three IBM SDK packages in the Docker install command.
It does not alter HTTP authentication, host validation, classification, forestry
rules, application startup, runtime user, or export enablement.

Replacement test image:
sha256:cd1c3102ad9098d03483fd967f6838ca7a182ba027b9915a10eb39a94a4eb77d
Python base pull digest recorded by the operator:
sha256:6dd8b6dab6b3adc7812bab69eca5dbdc1a5cc690ad28306d234ffb4ef8ac9753
The replacement contained libexpat1 2.5.0-1+deb12u5. It was a minimal test image,
not the application image. The revised application Dockerfile has not been built
or verified. Dependency/build hash enforcement and build-tool locking are not
established by this patch.

### Preserved evidence and Cloud Shell quota

Passing evidence archive: mapcp-sdk-passed-evidence-20261027T230213Z.tar.gz
SHA-256: d7c840e3bbd28be30b3c4fe61c9a6b71b99379a08a92be88d9f5579cb958ba70
The operator confirmed download to their computer.

A full temporary GIS venv under home exceeded Cloud Shell quota: that venv used
505M; home usage fell to 262M after its explicitly confirmed deletion. The home
quota is 500 MB despite df showing much larger backing storage. Preserve compact
evidence off-workspace; do not default to repeating full home-directory installs.
The earlier interrupted install and missing Docker images have no proven cause.

The non-atomic overwrite limitation, real SDK request/signing verification,
actual host approval, approved live COS operations, browser download, ArcGIS Pro
opening and workstation transfer remain required. Keep export disabled. No
bucket selection, credentials, live writes, policies, deployment, commit or push
are authorized by this file-only patch.
