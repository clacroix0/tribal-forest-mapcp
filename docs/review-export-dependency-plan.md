# Dependency plan - tested candidate adopted locally; application build pending

## Observed compatibility checkpoint - October 27, 2026

The dependency candidate was installed into a clean Python 3.12.16 virtual
environment in a container with networking disabled. All 55 candidate versions
were verified. pip check reported no broken requirements. IBM SDK and GIS imports
passed. The full regression suite reported 540 passed, 7 skipped, and 38 subtests
passed in 19.86 seconds. The seven skips require local Mescalero reference
artifacts. Container exit code was 0 and OOMKilled was false.

The application repository was read-only during that experiment. Adopting its
candidate here is a subsequent local file change, not a deployment or an observed
build of the revised application Dockerfile.

## Exact dependency changes

Keep requirements.txt unchanged. In requirements-deploy.txt, preserve every
other original pin, change python-dateutil from 3.0.0 to 2.9.0.post0, and add:

- ibm-cos-sdk==2.16.2
- ibm-cos-sdk-core==2.16.2
- ibm-cos-sdk-s3transfer==2.16.2
- jmespath==1.0.1
- requests==2.34.2
- urllib3==2.8.0
- charset-normalizer==3.5.2

The current IBM core requires python-dateutil>=2.9.0,<3.0.0. The original 3.0.0
pin conflicts. The tested candidate preserves pandas and all other original pins.

## Packaging and build limits

IBM publishes these three 2.16.2 packages as source archives. The initial
wheel-only resolver excluded them and tried obsolete 1.x releases; do not adopt
those older releases. The Docker install command now permits source packaging
only for ibm-cos-sdk, ibm-cos-sdk-core and ibm-cos-sdk-s3transfer, retaining the
wheel-only requirement for the remaining runtime packages.

Source preparation/build hooks execute package code and may download temporary
build dependencies. The approved experiment verified the three source hashes
before building, built 55 exact-version runtime wheels, recorded their hashes,
and installed only those wheels offline. The Dockerfile does not yet consume
that wheelhouse or enforce those recorded hashes. Its revised build has not run.
Build-tool versions were not fully locked. This remains a tested Linux/Python
snapshot, not a cross-platform or fully reproducible build lockfile.

The package builder uses the Python standard library and lazily uses the existing
rasterio/numpy dependencies for raster validation. Storage uses ibm_boto3 and
ibm_botocore from the IBM SDK family. The three IBM distributions declare Apache
License 2.0. Their built wheels were observed to contain license/notice files;
this is not a completed legal or third-party notice audit.

## Evidence and environment limitations

Evidence archive: mapcp-sdk-passed-evidence-20261027T230213Z.tar.gz
Archive SHA-256: d7c840e3bbd28be30b3c4fe61c9a6b71b99379a08a92be88d9f5579cb958ba70
The operator confirmed this archive was downloaded to their computer.

The approved source archives, candidate requirements and wheel hashes were
preserved separately in mapcp-sdk-test.4OTmDc. Offline logs and state were saved
in mapcp-sdk-offline-disk.Fo6Ren. These are operator evidence locations, not
runtime paths or prerequisites for end users.

Cloud Shell has a 500 MB home-directory quota; df reported backing-filesystem
capacity rather than that quota. The disk-backed temporary venv occupied 505M
and was removed after explicit operator confirmation. Reported home usage then
fell to 262M. Do not recreate a full GIS venv under Cloud Shell home by default.
The prior Docker EOF and image-store loss have no confirmed root cause.

## Still required before enabling delivery

- Separately approve and verify the revised application image build.
- Exercise actual SDK request/signing behavior; imports and simulated storage
  tests do not establish actual SDK API or live service compatibility.
- Resolve the non-atomic existence-check/upload overwrite limitation.
- Approve storage location, permissions, credentials, lifetime and retention.
- Demonstrate actual host approval for both create and renew.
- Complete approved live storage, browser download and ArcGIS Pro acceptance.

Keep export disabled. Do not create credentials, select a bucket, write live
objects, change policies, deploy, commit or push as part of this adoption patch.
