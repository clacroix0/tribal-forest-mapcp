# Boundary acquisition slice, stage 1 — read-only API verification

This package is NOT the submission/status/collection adapter. It is the first
verification stage of that approved slice, because current remote API schema
and product availability could not be retrieved by the assistant's web tools.
No remote job was submitted and no contact email is needed.

Use the ZIP copies as a matched pair:
- boundary_service_contract.py beside server.py.
- tests/test_boundary_service_contract.py inside tests/.
Do not modify server.py yet; this is a developer diagnostic, not a new public
agent tool. Do not replace existing preflight/generalization modules.

## Tests

From the project folder:

    .\.venv\Scripts\python.exe -m pytest tests/test_boundary_service_contract.py -q
    .\.venv\Scripts\python.exe -m pytest tests -q -rs

Twenty-one mocked tests passed in the sandbox. They do NOT prove live service
availability, real schema compatibility, size-limit support, or adapter completion.

## Run the read-only check

    .\.venv\Scripts\python.exe .\boundary_service_contract.py boundaryprep_20261013T160855_56655eeb

The command contacts only these fixed official READ endpoints:
- https://lfps.usgs.gov/api/healthCheck
- https://lfps.usgs.gov/swagger/v1/swagger.json
- https://lfps.usgs.gov/products

It never calls /api/job/submit or follows redirects. Calls have timeouts,
response-size limits and bounded transport retries. In the worst case reads
may take several minutes. Do not alter workstation/network security controls
if requests fail. Vendor support may be needed for changed endpoints or blocks.

It verifies that the original prepared boundary is unchanged. It checks the
published GET/query parameter signatures against the previously observed
sample contract. It detects changed methods, missing parameters, unexpected
required parameters, authentication requirements, and external parameter refs.
Product-name matches are catalog evidence only, not proof of AOI coverage.

## Results

A new servicecheck_* subfolder is written inside the selected boundaryprep_*
folder. It contains service_contract_check.json and, if obtained, a redacted
published_schema_redacted.json.

- verification_incomplete means a source/schema/catalog check was not established.
  The command exits with code 1 but still saves its diagnostic report if safe.
- request_signature_and_catalog_inspected_limits_unverified means all these
  checks succeeded, but remote size limits and runtime behavior remain unverified.

execution_ready is always false in this diagnostic. job_submitted and
rasters_downloaded are always false. It does not install software, store a
user email, edit the request, poll a job, or download a data bundle.

Paste the returned diagnostic JSON first. Do not paste credentials, tokens, or
contact email. Do not change expected parameter names simply to make a check pass.
The results determine how the actual acquisition adapter will be implemented.

## Remaining approved work

After verification/review: boundary-aware exact-request submission (no automatic
retry), status checking, allowlisted bundle collection/validation, explicit
limits and approval controls. This package does not mark that work complete.
The source profile remains the existing LF2025 CONUS sample profile. Broader
product/geographic support requires separately validated profiles.
