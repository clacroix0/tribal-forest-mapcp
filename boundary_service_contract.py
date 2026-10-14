from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field

URLS = {
    "health": "https://lfps.usgs.gov/api/healthCheck",
    "schema": "https://lfps.usgs.gov/swagger/v1/swagger.json",
    "products": "https://lfps.usgs.gov/products",
}
MAX_BYTES = 5_000_000
EMAIL_PATTERN = r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
EXPECTED_SUBMIT_PARAMETERS = {"Layer_List", "Include_Layer_List_XML_File", "Area_of_Interest", "Output_Projection", "Email"}
EXPECTED_STATUS_PARAMETERS = {"JobId"}


class ContractInspectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    preparation_directory: str = Field(pattern=r"^boundaryprep_[A-Za-z0-9_-]+$", max_length=240)


class ContractInspectionError(ValueError):
    pass


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _redact(text):
    return re.sub(EMAIL_PATTERN, "<redacted-email>", str(text))


def _read_endpoint(kind):
    """Only fixed READ endpoints; no submission URL is accepted or called."""
    if kind not in URLS:
        raise ContractInspectionError("Endpoint is not a permitted inspection source.")
    last_error = None
    for attempt in range(2):
        try:
            with httpx.Client(timeout=30.0, follow_redirects=False, trust_env=True) as client:
                with client.stream("GET", URLS[kind]) as response:
                    if response.is_redirect:
                        raise ContractInspectionError("Redirect refused; no alternate URL was followed.")
                    response.raise_for_status()
                    length = response.headers.get("content-length")
                    if length is not None and int(length) > MAX_BYTES:
                        raise ContractInspectionError("Response exceeds inspection byte limit.")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise ContractInspectionError("Response exceeds inspection byte limit.")
                    return bytes(body), response.headers.get("content-type", "")
        except httpx.TransportError as exc:
            last_error = _redact(exc)
            if attempt == 0:
                time.sleep(1)
    raise ContractInspectionError(f"Read failed after bounded transport retry: {last_error}")


def _resolve_parameter(doc, value):
    if not isinstance(value, dict):
        raise ContractInspectionError("Parameter is not an object.")
    if "$ref" not in value:
        return value
    ref = value["$ref"]
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise ContractInspectionError("Only local schema references are supported.")
    current = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise ContractInspectionError("Unresolved local schema parameter reference.")
        current = current[part]
    if not isinstance(current, dict) or "$ref" in current:
        raise ContractInspectionError("Nested/cyclic parameter references require review.")
    return current


def inspect_schema(doc):
    """Inspect published query signatures; does not prove runtime response behavior or size limits."""
    if not isinstance(doc, dict) or not isinstance(doc.get("paths"), dict):
        raise ContractInspectionError("Expected an OpenAPI/Swagger object with paths.")
    result = {}
    for endpoint, expected in [("/api/job/submit", EXPECTED_SUBMIT_PARAMETERS), ("/api/job/status", EXPECTED_STATUS_PARAMETERS)]:
        path = doc["paths"].get(endpoint)
        if not isinstance(path, dict) or not isinstance(path.get("get"), dict):
            raise ContractInspectionError(f"Published GET operation missing: {endpoint}")
        operation = path["get"]
        resolved = [_resolve_parameter(doc, v) for v in path.get("parameters", []) + operation.get("parameters", [])]
        queries = {p["name"]: p for p in resolved if p.get("in") == "query" and isinstance(p.get("name"), str)}
        missing = expected - set(queries)
        if missing:
            raise ContractInspectionError(f"Expected query parameters missing for {endpoint}: {sorted(missing)}")
        if operation.get("requestBody"):
            raise ContractInspectionError(f"Unexpected GET request body for {endpoint}; review contract.")
        required_extras = sorted(name for name,p in queries.items() if p.get("required") is True and name not in expected)
        if required_extras:
            raise ContractInspectionError(f"New required query parameters for {endpoint}: {required_extras}")
        if operation.get("security") or doc.get("security"):
            raise ContractInspectionError("Published authentication requirements need a separately reviewed integration.")
        result[endpoint] = {
            "method": "GET",
            "query_parameters": [{"name": name, "required": queries[name].get("required", False),
                                  "description": _redact(queries[name].get("description", ""))[:2500],
                                  "schema": queries[name].get("schema", {k: queries[name][k] for k in ["type","format","enum","default","maximum","minimum"] if k in queries[name]})}
                                 for name in sorted(queries)],
            "responses": operation.get("responses", {}),
        }
    return {"schema_version": doc.get("openapi") or doc.get("swagger"),
            "api_title": doc.get("info", {}).get("title"), "operations": result,
            "request_signature_matches_previous_sample_contract": True,
            "runtime_responses_verified": False, "remote_size_limits_verified": False}


def inspect_boundary_service_contract(outputs_root: Path, request: ContractInspectionRequest):
    """Read-only service calls plus isolated local evidence writes; never submits/downloads a job."""
    root = Path(outputs_root).resolve()
    directory = (root/request.preparation_directory).resolve()
    if directory.parent != root or not directory.is_dir():
        raise ContractInspectionError("Preparation must be a direct controlled outputs subfolder.")
    if (directory/"FAILED_DO_NOT_USE.json").exists():
        raise ContractInspectionError("Preparation is marked failed.")
    request_path = (directory/"boundary_request.json").resolve()
    if request_path.parent != directory or not request_path.is_file() or request_path.stat().st_size > MAX_BYTES:
        raise ContractInspectionError("Missing, oversized or escaping request document.")
    proposal = json.loads(request_path.read_text(encoding="utf-8-sig"))
    if not isinstance(proposal,dict) or proposal.get("document_type") != "mapcp_full_boundary_request_v1" or proposal.get("status") != "prepared_review_required":
        raise ContractInspectionError("Not a successful full-boundary preparation document.")
    filename = proposal.get("source_boundary_filename")
    if not isinstance(filename,str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.geojson",filename):
        raise ContractInspectionError("Invalid controlled boundary filename.")
    boundary = (root/filename).resolve()
    if boundary.parent != root or not boundary.is_file() or boundary.stat().st_size > MAX_BYTES:
        raise ContractInspectionError("Missing, oversized or escaping boundary.")
    boundary_hash = _digest(boundary)
    if boundary_hash != proposal.get("source_boundary_sha256"):
        raise ContractInspectionError("Boundary changed since preparation.")
    request_hash = _digest(request_path)
    products = proposal.get("products")
    if products != ["LF2025_EVT","LF2025_EVC","LF2025_EVH"]:
        raise ContractInspectionError("Inspection supports the current selected LF2025 CONUS profile only.")
    evidence = {"document_type":"mapcp_boundary_service_contract_inspection_v1",
                "created_at_utc":datetime.now(timezone.utc).isoformat(),
                "source_preparation_directory":request.preparation_directory,
                "prepared_request_sha256":request_hash,"boundary_sha256":boundary_hash,
                "job_submitted":False,"rasters_downloaded":False,"execution_ready":False,
                "remote_size_limits_verified":False,"endpoints":{},"errors":[],
                "limitations":["Schema signatures are not proof of runtime response or request-size support.",
                               "Product name presence in the official catalog is not proof of AOI coverage.",
                               "No submission, polling of a specific job, bundle download, or acquisition adapter execution occurred."]}
    schema = None
    for kind in URLS:
        try:
            body, content_type = _read_endpoint(kind)
            text = body.decode("utf-8-sig")
            item = {"url":URLS[kind],"bytes":len(body),"content_type":content_type,
                    "sha256":hashlib.sha256(body).hexdigest(),"read_success":True}
            if kind == "schema":
                schema = json.loads(text)
                item["contract"] = inspect_schema(schema)
                item["signature_verified"] = True
            elif kind == "health":
                health = json.loads(text)
                if not isinstance(health,dict) or health.get("success") is False:
                    raise ContractInspectionError("Health endpoint did not return a successful JSON object.")
                item["health_json"] = json.loads(_redact(json.dumps(health)))
            else:
                if not ("html" in content_type.lower() or "json" in content_type.lower()):
                    raise ContractInspectionError("Product catalog is not recognized HTML/JSON.")
                found = [p for p in products if re.search(r"(?<![A-Za-z0-9_])"+re.escape(p)+r"(?![A-Za-z0-9_])",text)]
                item["requested_identifiers_found"] = found
                item["all_requested_identifiers_found"] = len(found) == len(products)
                if len(found) != len(products):
                    evidence["errors"].append("Products page did not expose all requested identifiers; JavaScript/catalog layout or availability may require review.")
            evidence["endpoints"][kind] = item
        except Exception as exc:
            evidence["endpoints"][kind] = {"url":URLS[kind],"read_success":False,"error":_redact(f"{type(exc).__name__}: {exc}")}
            evidence["errors"].append(f"{kind} inspection failed; do not assume service support.")
    schema_ok = evidence["endpoints"].get("schema",{}).get("signature_verified") is True
    health_ok = evidence["endpoints"].get("health",{}).get("read_success") is True
    catalog_ok = evidence["endpoints"].get("products",{}).get("all_requested_identifiers_found") is True
    evidence["status"] = "request_signature_and_catalog_inspected_limits_unverified" if schema_ok and health_ok and catalog_ok else "verification_incomplete"
    if _digest(boundary) != boundary_hash or _digest(request_path) != request_hash:
        raise ContractInspectionError("Input changed during inspection; no evidence accepted.")
    target = directory/f"servicecheck_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    target.mkdir(exist_ok=False)
    try:
        if schema is not None:
            with (target/"published_schema_redacted.json").open("x",encoding="utf-8") as stream:
                stream.write(_redact(json.dumps(schema,indent=2)))
        evidence["report_path"] = str(target/"service_contract_check.json")
        with (target/"service_contract_check.json").open("x",encoding="utf-8") as stream:
            json.dump(evidence,stream,indent=2,allow_nan=False)
    except Exception as exc:
        with (target/"FAILED_DO_NOT_USE.json").open("x",encoding="utf-8") as stream:
            json.dump({"status":"failed","accept_outputs":False,"error":_redact(exc)},stream)
        raise
    return evidence


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description="Read-only LFPS contract checks; never submit a job.")
    parser.add_argument("preparation_directory")
    args=parser.parse_args()
    try:
        result=inspect_boundary_service_contract(Path(__file__).resolve().parent/"outputs",
                    ContractInspectionRequest(preparation_directory=args.preparation_directory))
        print(json.dumps(result,indent=2,allow_nan=False))
        raise SystemExit(0 if result["status"] == "request_signature_and_catalog_inspected_limits_unverified" else 1)
    except Exception as exc:
        print(json.dumps({"status":"failed","job_submitted":False,"error":_redact(f"{type(exc).__name__}: {exc}")},indent=2))
        raise SystemExit(1)
