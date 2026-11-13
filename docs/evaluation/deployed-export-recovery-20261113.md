# Deployed export source recovery — November 13, 2026

## Purpose

Preserve recovered export source and deployment requirements on a recovery
branch. This checkpoint is not approval to deploy, enable exports, or merge
an unverified build into main.

## Recovery source

Registry image:
us.icr.io/gsa-hackathon-cr-student9/tribal-forest-mapcp@sha256:4e5fe9fff4d24487399703e475cd490923ef2556d24b2278b745f954743eed46

Local Docker image ID:
sha256:ab6dd167a936fe9ddf608cf44f7385a1f465c8168875037f27eda1f5dc9d0bf3

Inspection container: mapcp-source-inspect
Application directory: /app
Git baseline: 289e76e
Recovery branch: recovery/deployed-export-2026-11-13

## Recovered files

- server.py: 53 added lines relative to the baseline.
- review_package.py
- review_package_storage.py
- requirements-deploy.txt
- docs/review-package-delivery.md
- docs/review-export-dependency-plan.md

Recovered server_http.py matched the baseline and was not changed.

## Missing recovery material

The inspection container did not contain /app/tests, /app/Dockerfile,
or /app/requirements.txt.

A bounded search of Cloud Shell home found no matching test_review_package*.py
files or matching historical evidence archives. This does not prove those
materials are absent from other computers or storage.

The original revised Dockerfile and export tests have not been recovered.
The baseline Dockerfile remains unchanged. Its wheel-only installation command
has not been reconciled with the recovered dependency plan's SDK packaging
requirements. This checkpoint is not established as a reproducible build.

## Verification and limitations

The recovered copies were compared byte-for-byte with the extraction copies,
and the three recovered Python source files passed a non-executing compilation
check before this note was written.

Historical test counts and status statements in recovered documents describe
earlier checkpoints, not fresh results for this recovery.

No fresh export, mapping regression, application image build, live storage,
host-approval, browser download, or ArcGIS Pro acceptance test was performed
as part of this checkpoint.

No export enablement or deployment change is authorized by this recovery.
Do not add credentials, signed URLs, runtime approval records, or generated
mapping outputs to this commit.

## Follow-up before merge or deployment

- Recover the original tests or explicitly implement reviewed replacement tests.
- Reconcile and verify the Dockerfile against the recovered dependencies.
- Review recovered files for secrets and sensitive information.
- Run applicable regression and export tests and record actual results.
- Reconcile historical documentation with the verified current state.
- Review the pull request before merging.
