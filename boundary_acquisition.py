from __future__ import annotations

import csv
import hashlib
import hmac
import json
import math
import os
import re
import shutil
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import geopandas as gpd
import httpx
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from boundary_mapping_preflight import PRODUCTS, inspect_boundary_frame

# --- Fixed, reviewed service constants (same conventions as the working sample workflow) ---
SUBMIT_URL = "https://lfps.usgs.gov/api/job/submit"
STATUS_URL = "https://lfps.usgs.gov/api/job/status"
OUTPUT_HOST = "lfps.usgs.gov"
OUTPUT_PATH_PREFIX = "/arcgis/rest/directories/arcgisjobs/landfireproductservice_gpserver/"
EXPECTED_BANDS = ["LF2025_EVT_CONUS", "LF2025_EVC_CONUS", "LF2025_EVH_CONUS"]
EXPECTED_XML = [f"{name}.xml" for name in EXPECTED_BANDS]
OUTPUT_EPSG = 5070
NODATA_FILL = -9999
MAX_JSON_BYTES = 5_000_000
JOB_ID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
EMAIL_PATTERN = r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}"
COLLECTION_PHRASE = "download_and_validate_this_exact_lfps_v2_bundle"

# PROPOSED full-boundary limits. They are shown in the preview and bound into the approval
# token. They are NOT vendor limits; the preflight estimated ~41 MB for three uncompressed
# int32 bands, so these leave a wide margin without removing protection.
LIMITS = {
    "max_bundle_bytes": 500_000_000,
    "max_extracted_bytes": 2_000_000_000,
    "max_zip_members": 50,
    "max_compression_ratio": 100,
    "max_inspect_pixels": 25_000_000,
    "max_path_chars": 240,
    "submit_timeout_seconds": 60,
    "status_timeout_seconds": 60,
    "download_timeout_seconds": 300,
}


class AcquisitionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: str
    stage: str
    job_submitted: bool | Literal["unknown"] = False
    job_id: str | None = None
    rasters_downloaded: bool = False
    classification_performed: bool = False
    usable_for_mapping: bool = False
    summary: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    preparation_directory: str = Field(pattern=r"^boundaryprep_[A-Za-z0-9_-]+$", max_length=240)
    request_contact_email: str = Field(min_length=3, max_length=254)
    submission_approval: str = Field(pattern=r"^submit_[0-9a-f]{12}$")


class StatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    acquisition_directory: str = Field(pattern=r"^bacq_[A-Za-z0-9_-]+$", max_length=120)


class CollectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    acquisition_directory: str = Field(pattern=r"^bacq_[A-Za-z0-9_-]+$", max_length=120)
    status_filename: str = Field(pattern=r"^status_[A-Za-z0-9_-]+\.json$", max_length=120)
    collection_approval: Literal["download_and_validate_this_exact_lfps_v2_bundle"]


class AcquisitionError(ValueError):
    pass


# --- helpers -------------------------------------------------------------------------------
def _client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=False)


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _redact(value, email: str | None = None):
    if isinstance(value, str):
        if email:
            value = value.replace(email, "<redacted-email>")
        return re.sub(EMAIL_PATTERN, "<redacted-email>", value)
    if isinstance(value, list):
        return [_redact(item, email) for item in value]
    if isinstance(value, dict):
        return {(_redact(k, email) if isinstance(k, str) else k):
                ("<redacted-email>" if isinstance(k, str) and "email" in k.lower() else _redact(v, email))
                for k, v in value.items()}
    return value


def _direct_dir(root: Path, name: str) -> Path:
    directory = (Path(root).resolve() / name).resolve()
    if directory.parent != Path(root).resolve() or not directory.is_dir():
        raise AcquisitionError("Directory must be an existing direct subfolder of outputs.")
    return directory


def _direct_file(directory: Path, name: str, limit: int = MAX_JSON_BYTES) -> Path:
    path = (directory / name).resolve()
    if path.parent != directory.resolve() or not path.is_file():
        raise AcquisitionError(f"Missing or escaping file: {name}")
    if path.stat().st_size > limit:
        raise AcquisitionError(f"File exceeds size limit: {name}")
    return path


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise AcquisitionError("Expected a JSON object.")
    return value


def _write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def _failure(stage: str, errors: list[str], **kwargs) -> AcquisitionResult:
    return AcquisitionResult(status="failed", stage=stage, errors=errors, **kwargs)


def _expected_parameters(frame: gpd.GeoDataFrame):
    summary = inspect_boundary_frame(frame)
    west, south, east, north = summary["download_aoi_wgs84"]
    return {
        "Layer_List": ";".join(PRODUCTS),
        "Include_Layer_List_XML_File": "true",
        "Area_of_Interest": f"{west:.12f} {south:.12f} {east:.12f} {north:.12f}",
        "Output_Projection": str(OUTPUT_EPSG),
    }, summary


def _load_prepared(root: Path, preparation_directory: str) -> dict:
    directory = _direct_dir(root, preparation_directory)
    if (directory / "FAILED_DO_NOT_USE.json").exists():
        raise AcquisitionError("Preparation is marked failed.")
    request_path = _direct_file(directory, "boundary_request.json")
    proposal = _read_json(request_path)
    if proposal.get("document_type") != "mapcp_full_boundary_request_v1" or proposal.get("status") != "prepared_review_required":
        raise AcquisitionError("Not a successful full-boundary preparation document.")
    if proposal.get("products") != PRODUCTS:
        raise AcquisitionError("Unsupported product profile.")
    name = proposal.get("source_boundary_filename")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.geojson", name):
        raise AcquisitionError("Invalid boundary filename in preparation.")
    boundary_path = _direct_file(Path(root).resolve(), name)
    boundary_hash = _digest(boundary_path)
    if boundary_hash != proposal.get("source_boundary_sha256"):
        raise AcquisitionError("Boundary changed since preparation; review and prepare again.")
    frame = gpd.read_file(boundary_path, engine="pyogrio")
    expected, summary = _expected_parameters(frame)
    if proposal.get("proposed_parameters_without_email") != expected:
        raise AcquisitionError("Prepared parameters differ from those recomputed from the boundary; do not submit.")
    request_hash = _digest(request_path)
    token_source = json.dumps({"request": request_hash, "boundary": boundary_hash,
                               "parameters": expected, "limits": LIMITS}, sort_keys=True)
    token = "submit_" + hashlib.sha256(token_source.encode()).hexdigest()[:12]
    return {"directory": directory, "proposal": proposal, "request_path": request_path,
            "boundary_path": boundary_path, "boundary_hash": boundary_hash, "request_hash": request_hash,
            "parameters": expected, "summary": summary, "token": token}


# --- 1. preview (no network, no writes) ---------------------------------------------------------
def preview_boundary_submission(outputs_root: Path, preparation_directory: str) -> AcquisitionResult:
    try:
        prepared = _load_prepared(outputs_root, preparation_directory)
        summary = prepared["summary"]
        return AcquisitionResult(
            status="preview_requires_user_approval", stage="complete",
            summary={"endpoint": SUBMIT_URL, "method": "GET",
                     "parameters_without_email": prepared["parameters"],
                     "contact_email_required_at_submission": True,
                     "boundary_filename": prepared["proposal"]["source_boundary_filename"],
                     "boundary_acres": summary["boundary_acres"],
                     "estimated_download_pixels": summary["estimated_download_pixels"],
                     "proposed_limits": LIMITS, "approval_token": prepared["token"]},
            warnings=["No network request was made and no job was submitted.",
                      "Limits are MapCP proposals, not verified vendor limits; the service may reject or time out.",
                      "The token binds this exact prepared request, boundary hash, parameters and limits.",
                      "A model-generated token is not proof of human review; the user must review this preview."])
    except Exception as exc:
        return _failure("preview", [f"{type(exc).__name__}: {_redact(str(exc))}"])


# --- 2. submit (at most one attempt per preparation) --------------------------------------------
def submit_boundary_job(outputs_root: Path, request: SubmitRequest) -> AcquisitionResult:
    email = request.request_contact_email.strip()
    if not re.fullmatch(EMAIL_PATTERN, email):
        return _failure("validate_contact_email", ["A valid contact email is required (any valid domain)."])
    try:
        prepared = _load_prepared(outputs_root, request.preparation_directory)
    except Exception as exc:
        return _failure("validate_prepared_request", [f"{type(exc).__name__}: {_redact(str(exc), email)}"])
    if not hmac.compare_digest(request.submission_approval, prepared["token"]):
        return _failure("validate_approval", ["Approval token does not match this exact reviewed request. No job was submitted."])
    directory = prepared["directory"]
    lock_path = directory / "submission_lock.json"
    try:
        _write_json(lock_path, {"state": "attempt_started", "started_at_utc": datetime.now(timezone.utc).isoformat(),
                                "request_sha256": prepared["request_hash"], "contact_email_stored": False})
    except FileExistsError:
        return _failure("validate_no_prior_attempt",
                        ["A submission attempt already exists for this preparation. Review submission_result.json or the lock; "
                         "do not resubmit until the earlier outcome is understood."], job_submitted="unknown")
    parameters = dict(prepared["parameters"])
    parameters["Email"] = email
    submitted_at = datetime.now(timezone.utc)

    def release(reason: str, detail: dict) -> None:
        """Definite rejection only: preserve evidence, then free the lock. On any file error keep the lock."""
        suffix = f"{submitted_at.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
        try:
            with (directory / f"submission_rejected_{suffix}.json").open("x", encoding="utf-8") as stream:
                json.dump({"reason": reason, "detail": _redact(detail, email), "job_submitted": False}, stream, indent=2)
            os.replace(lock_path, directory / f"submission_lock_released_{suffix}.json")
        except OSError:
            pass

    try:
        with _client(LIMITS["submit_timeout_seconds"]) as client:
            response = client.get(SUBMIT_URL, params=parameters, headers={"Accept": "application/json"})
        if response.is_redirect:
            return _failure("submit", ["Submission redirected; MapCP refused to follow it and cannot confirm whether a job exists."], job_submitted="unknown")
        if 400 <= response.status_code < 500:
            release("http_client_error", {"status_code": response.status_code})
            return _failure("submit", [f"LFPS rejected the request with HTTP {response.status_code}. No job was created."], job_submitted=False)
        response.raise_for_status()
        if len(response.content) > MAX_JSON_BYTES:
            return _failure("submit", ["Submission response exceeded the size limit; job outcome is unknown."], job_submitted="unknown")
        if "application/json" not in response.headers.get("content-type", "").lower():
            return _failure("submit", ["Submission returned non-JSON content; job outcome is unknown. Do not resubmit automatically."], job_submitted="unknown")
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return _failure("submit", [f"Submission outcome unknown after {type(exc).__name__}: {_redact(str(exc), email)}. Do not resubmit automatically."], job_submitted="unknown")
    if not isinstance(body, dict):
        return _failure("submit", ["Submission response was not a JSON object; job outcome is unknown."], job_submitted="unknown")
    safe_body = _redact(body, email)
    if body.get("success") is False:
        release("success_false", {"response": safe_body})
        return _failure("submit", ["LFPS reported the submission was not successful."], job_submitted=False, summary={"response": safe_body})
    job_id = body.get("jobId")
    if not isinstance(job_id, str) or not re.fullmatch(JOB_ID_PATTERN, job_id):
        return _failure("submit", ["Response had no usable UUID jobId; outcome unknown."], job_submitted="unknown", summary={"response": safe_body})
    stamp = submitted_at.strftime("%Y%m%dT%H%M%S")
    acquisition = Path(outputs_root).resolve() / f"bacq_{stamp}_{job_id[:8]}"
    job_doc = {"document_type": "mapcp_boundary_job_v1", "status": "submitted_waiting_for_completion",
               "submitted_at_utc": submitted_at.isoformat(), "api_version": "LFPS v2",
               "preparation_directory": request.preparation_directory,
               "prepared_request_sha256": prepared["request_hash"],
               "boundary_filename": prepared["proposal"]["source_boundary_filename"],
               "boundary_sha256": prepared["boundary_hash"],
               "submit_endpoint": SUBMIT_URL, "status_endpoint": STATUS_URL, "job_id": job_id,
               "parameters_without_email": prepared["parameters"], "limits": LIMITS,
               "initial_response": safe_body, "contact_email_supplied": True, "contact_email_stored": False,
               "classification_performed": False, "rasters_downloaded": False}
    try:
        acquisition.mkdir(exist_ok=False)
        _write_json(acquisition / "job.json", job_doc)
        _write_json(directory / "submission_result.json", {"job_id": job_id, "acquisition_directory": acquisition.name,
                                                           "submitted_at_utc": submitted_at.isoformat()})
    except OSError as exc:
        return AcquisitionResult(status="submitted_manifest_write_failed", stage="write_job_manifest", job_submitted=True, job_id=job_id,
                                 errors=[f"Job exists but local manifest failed: {_redact(str(exc), email)}. Keep this job ID."])
    return AcquisitionResult(status="submitted_waiting_for_completion", stage="complete", job_submitted=True, job_id=job_id,
                             artifacts={"acquisition_directory": acquisition.name, "job_manifest": "job.json"},
                             warnings=["Completion is not confirmed. Check status; do not resubmit."])


def record_recovered_job(outputs_root: Path, preparation_directory: str, job_id: str) -> AcquisitionResult:
    """Create a local manifest for a job ID already issued by LFPS. No network access."""
    try:
        if not re.fullmatch(JOB_ID_PATTERN, job_id):
            raise AcquisitionError("job_id must be the UUID issued by LFPS.")
        prepared = _load_prepared(outputs_root, preparation_directory)
        now = datetime.now(timezone.utc)
        acquisition = Path(outputs_root).resolve() / f"bacq_{now.strftime('%Y%m%dT%H%M%S')}_{job_id[:8]}"
        acquisition.mkdir(exist_ok=False)
        _write_json(acquisition / "job.json", {
            "document_type": "mapcp_boundary_job_v1", "status": "recovered_waiting_for_status_check",
            "recovered_at_utc": now.isoformat(), "api_version": "LFPS v2", "preparation_directory": preparation_directory,
            "prepared_request_sha256": prepared["request_hash"], "boundary_filename": prepared["proposal"]["source_boundary_filename"],
            "boundary_sha256": prepared["boundary_hash"], "status_endpoint": STATUS_URL, "submit_endpoint": SUBMIT_URL,
            "job_id": job_id, "parameters_without_email": prepared["parameters"], "limits": LIMITS,
            "initial_response": None, "contact_email_supplied": True, "contact_email_stored": False,
            "classification_performed": False, "rasters_downloaded": False})
        return AcquisitionResult(status="recovered_manifest_written", stage="complete", job_submitted=True, job_id=job_id,
                                 artifacts={"acquisition_directory": acquisition.name},
                                 warnings=["Recovered record: initial service response was not retained. Check status next."])
    except Exception as exc:
        return _failure("recover_job", [f"{type(exc).__name__}: {_redact(str(exc))}"])


# --- 3. status ------------------------------------------------------------------------------------
def _load_job(root: Path, acquisition_directory: str):
    directory = _direct_dir(root, acquisition_directory)
    job = _read_json(_direct_file(directory, "job.json"))
    if job.get("document_type") != "mapcp_boundary_job_v1" or job.get("status_endpoint") != STATUS_URL:
        raise AcquisitionError("Not a recognized boundary acquisition job manifest.")
    job_id = job.get("job_id")
    if not isinstance(job_id, str) or not re.fullmatch(JOB_ID_PATTERN, job_id):
        raise AcquisitionError("Job manifest has no valid job ID.")
    return directory, job, job_id


def check_boundary_job(outputs_root: Path, request: StatusRequest) -> AcquisitionResult:
    try:
        directory, job, job_id = _load_job(outputs_root, request.acquisition_directory)
        last = None
        for attempt in range(2):
            try:
                with _client(LIMITS["status_timeout_seconds"]) as client:
                    response = client.get(STATUS_URL, params={"JobId": job_id}, headers={"Accept": "application/json"})
                break
            except httpx.TransportError as exc:
                last = exc
                if attempt == 0:
                    time.sleep(1)
        else:
            raise AcquisitionError(f"Status request failed after bounded retry: {last}")
        if response.is_redirect:
            raise AcquisitionError("Status endpoint redirected; refusing to follow.")
        response.raise_for_status()
        if len(response.content) > MAX_JSON_BYTES or "application/json" not in response.headers.get("content-type", "").lower():
            raise AcquisitionError("Status response was oversized or not JSON.")
        body = response.json()
        if not isinstance(body, dict):
            raise AcquisitionError("Status response was not a JSON object.")
        if body.get("success") is False:
            raise AcquisitionError("LFPS status reported success=false.")
        if body.get("jobId") != job_id:
            raise AcquisitionError("Returned job ID does not match the requested job.")
        source_status = body.get("status")
        if not isinstance(source_status, str) or not source_status.strip():
            raise AcquisitionError("Status response had no usable status.")
        normalized = source_status.strip().lower()
        if normalized in {"pending", "queued"}:
            status = "submitted_waiting_in_queue"
        elif normalized in {"executing", "running", "processing"}:
            status = "submitted_processing"
        elif normalized in {"succeeded", "success", "completed"}:
            status = "completed_requires_output_collection"
        elif normalized in {"failed", "error"}:
            status = "source_job_failed"
        elif normalized in {"canceled", "cancelled"}:
            status = "source_job_canceled"
        else:
            status = "source_job_status_unrecognized"
        now = datetime.now(timezone.utc)
        name = f"status_{now.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:4]}.json"
        _write_json(directory / name, {"document_type": "mapcp_boundary_status_v1", "status": status,
                                       "checked_at_utc": now.isoformat(), "job_id": job_id, "source_status": source_status,
                                       "queue_position": body.get("queuePosition"), "messages": _redact(body.get("messages")),
                                       "output_file": _redact(body.get("outputFile")), "rasters_downloaded": False})
        return AcquisitionResult(status=status, stage="complete", job_submitted=True, job_id=job_id,
                                 summary={"source_status": source_status, "queue_position": body.get("queuePosition")},
                                 artifacts={"status_report": name})
    except Exception as exc:
        return _failure("check_status", [f"{type(exc).__name__}: {_redact(str(exc))}"], job_submitted=True)


# --- 4. collection ------------------------------------------------------------------------------------
def _validate_output_url(value) -> str:
    if not isinstance(value, str):
        raise AcquisitionError("Status report has no usable output URL.")
    parsed = urlparse(value)
    if not (parsed.scheme == "https" and parsed.netloc.lower() == OUTPUT_HOST
            and parsed.path.startswith(OUTPUT_PATH_PREFIX) and parsed.path.lower().endswith(".zip")
            and not parsed.username and not parsed.password):
        raise AcquisitionError("Output URL does not match the fixed HTTPS LANDFIRE bundle allowlist.")
    return value


def _download(url: str, part: Path) -> int:
    total = 0
    with _client(LIMITS["download_timeout_seconds"]) as client:
        with client.stream("GET", url, headers={"Accept": "application/zip"}) as response:
            if response.is_redirect:
                raise AcquisitionError("Bundle URL redirected; refusing to follow.")
            response.raise_for_status()
            advertised = response.headers.get("content-length")
            if advertised is not None and advertised.isdigit() and int(advertised) > LIMITS["max_bundle_bytes"]:
                raise AcquisitionError("Bundle exceeds the approved size limit.")
            with part.open("xb") as stream:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > LIMITS["max_bundle_bytes"]:
                        raise AcquisitionError("Bundle exceeded the approved size limit while downloading.")
                    stream.write(chunk)
    if total == 0:
        raise AcquisitionError("Downloaded bundle was empty.")
    return total


def _extract_zip(zip_path: Path, staging: Path, final_name: str) -> dict:
    with zipfile.ZipFile(zip_path) as bundle:
        members = bundle.infolist()
        if not members or len(members) > LIMITS["max_zip_members"]:
            raise AcquisitionError("ZIP is empty or exceeds the member limit.")
        if sum(item.file_size for item in members) > LIMITS["max_extracted_bytes"]:
            raise AcquisitionError("ZIP expanded size exceeds the approved limit.")
        free = shutil.disk_usage(zip_path.parent).free
        if free < LIMITS["max_extracted_bytes"] + LIMITS["max_bundle_bytes"]:
            raise AcquisitionError("Insufficient free disk for the approved worst-case extraction.")
        staging.mkdir(parents=True, exist_ok=False)
        root = staging.resolve()
        planned = []
        for item in members:
            name = item.filename
            if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name) or ".." in Path(name).parts:
                raise AcquisitionError("ZIP contains an unsafe path.")
            if item.flag_bits & 0x1:
                raise AcquisitionError("ZIP contains encrypted members.")
            if item.compress_size > 0 and item.file_size > item.compress_size * LIMITS["max_compression_ratio"]:
                raise AcquisitionError("ZIP member exceeds the approved compression-ratio limit.")
            destination = (staging / name).resolve()
            try:
                destination.relative_to(root)
            except ValueError as exc:
                raise AcquisitionError("ZIP member escaped the controlled folder.") from exc
            for prefix in (staging.parent / final_name, staging):
                if len(str(prefix / name)) > LIMITS["max_path_chars"]:
                    raise AcquisitionError("Extracted path would exceed the Windows-safe path limit; use a shorter project location.")
            planned.append((item, destination))
        bad = bundle.testzip()
        if bad is not None:
            raise AcquisitionError(f"ZIP CRC validation failed: {bad}")
        tifs = [item.filename for item in members if item.filename.lower().endswith((".tif", ".tiff"))]
        if len(tifs) != 1:
            raise AcquisitionError(f"Expected exactly one GeoTIFF; found {len(tifs)}.")
        basenames = {Path(item.filename).name for item in members}
        missing = [name for name in EXPECTED_XML if name not in basenames]
        if missing:
            raise AcquisitionError(f"ZIP is missing metadata XML: {missing}")
        written = 0
        for item, destination in planned:
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(item) as source, destination.open("xb") as target:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > LIMITS["max_extracted_bytes"]:
                        raise AcquisitionError("Extraction exceeded the approved size limit.")
                    target.write(chunk)
    return {"tif_member": tifs[0], "member_count": len(members), "uncompressed_bytes": written}


def _inspect_raster(tif_path: Path, boundary_path: Path) -> dict:
    """Read-only inspection against the selected boundary. Requires rasterio (user's environment)."""
    import rasterio
    from rasterio.features import geometry_mask
    errors = []
    boundary = gpd.read_file(boundary_path, engine="pyogrio").to_crs(epsg=OUTPUT_EPSG)
    geometry = boundary.union_all() if hasattr(boundary, "union_all") else boundary.unary_union
    with rasterio.open(tif_path) as src:
        count, width, height = src.count, src.width, src.height
        epsg = src.crs.to_epsg() if src.crs is not None else None
        resolution = [abs(float(v)) for v in src.res]
        descriptions = [d.strip() if isinstance(d, str) else None for d in src.descriptions]
        bounds = [float(src.bounds.left), float(src.bounds.bottom), float(src.bounds.right), float(src.bounds.top)]
        nodata_values = list(src.nodatavals)
        if count != 3:
            errors.append(f"Expected 3 bands; found {count}.")
        if epsg != OUTPUT_EPSG:
            errors.append(f"Expected EPSG:{OUTPUT_EPSG}; found {epsg}.")
        if not all(math.isclose(v, 30.0, abs_tol=0.01) for v in resolution):
            errors.append(f"Expected 30 m cells; found {resolution}.")
        if descriptions != EXPECTED_BANDS:
            errors.append(f"Band descriptions do not match expected order: {descriptions}")
        if width * height > LIMITS["max_inspect_pixels"]:
            errors.append("Raster exceeds the approved inspection pixel limit; no pixels were read.")
        result = {"band_count": count, "width": width, "height": height, "epsg": epsg, "resolution_m": resolution,
                  "bounds_epsg5070": bounds, "nodata_values": nodata_values, "band_descriptions": descriptions}
        minx, miny, maxx, maxy = [float(v) for v in geometry.bounds]
        tolerance = 30.0
        covers = (bounds[0] <= minx + tolerance and bounds[1] <= miny + tolerance
                  and bounds[2] >= maxx - tolerance and bounds[3] >= maxy - tolerance)
        result["raster_covers_boundary_extent"] = covers
        if not covers:
            errors.append("Raster extent does not cover the selected boundary extent.")
        result["validation_errors"] = errors
        if errors or "LF2025_EVT_CONUS" not in descriptions:
            result["pixels_inspected"] = False
            return result
        evt_index = descriptions.index("LF2025_EVT_CONUS") + 1
        evt = src.read(evt_index)
        inside = geometry_mask([geometry], out_shape=(height, width), transform=src.transform, invert=True, all_touched=False)
        fill = [NODATA_FILL]
        if nodata_values and nodata_values[evt_index - 1] is not None:
            fill.append(nodata_values[evt_index - 1])
        valid = inside & ~np.isin(evt, fill)
        codes, counts = np.unique(evt[valid], return_counts=True)
        cell_area = resolution[0] * resolution[1]
        result.update({
            "pixels_inspected": True, "cells_inside_boundary": int(inside.sum()),
            "valid_evt_cells_inside_boundary": int(valid.sum()),
            "nodata_evt_cells_inside_boundary": int(inside.sum() - valid.sum()),
            "cell_area_m2": cell_area, "inside_area_acres": float(inside.sum() * cell_area / 4046.8564224),
            "unique_evt_codes_inside_boundary": int(len(codes)),
            "evt_code_counts": [[int(c), int(n)] for c, n in zip(codes, counts)]})
    return result


def collect_boundary_bundle(outputs_root: Path, request: CollectRequest) -> AcquisitionResult:
    started = time.perf_counter()
    directory = None
    part = None
    staging = None
    zip_path = None
    extract_path = None
    collection_path = None
    try:
        directory, job, job_id = _load_job(outputs_root, request.acquisition_directory)
        status_doc = _read_json(_direct_file(directory, request.status_filename))
        if status_doc.get("document_type") != "mapcp_boundary_status_v1" or status_doc.get("job_id") != job_id:
            raise AcquisitionError("Status report does not belong to this job.")
        if status_doc.get("status") != "completed_requires_output_collection":
            raise AcquisitionError("Job is not in a successful completed state; nothing was downloaded.")
        url = _validate_output_url(status_doc.get("output_file"))
        zip_path, extract_path, collection_path = directory / "bundle.zip", directory / "extract", directory / "collection.json"
        if zip_path.exists() or extract_path.exists() or collection_path.exists():
            raise AcquisitionError("A collection already exists for this job; it will not be overwritten.")
        root = Path(outputs_root).resolve()
        boundary_path = _direct_file(root, job["boundary_filename"])
        if _digest(boundary_path) != job.get("boundary_sha256"):
            raise AcquisitionError("Boundary changed since submission.")
        part = directory / "bundle.part"
        size = _download(url, part)
        part.replace(zip_path)
        part = None
        staging = directory / "extract_staging"
        info = _extract_zip(zip_path, staging, "extract")
        staging.replace(extract_path)
        staging = None
        tif_path = (extract_path / info["tif_member"]).resolve()
        inspection = _inspect_raster(tif_path, boundary_path)
        errors = inspection.get("validation_errors", [])
        csv_name = None
        if inspection.get("pixels_inspected"):
            csv_name = "evt_codes_in_boundary.csv"
            with (directory / csv_name).open("x", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["evt_code", "cell_count", "square_meters", "acres"])
                for code, n in inspection["evt_code_counts"]:
                    area = n * inspection["cell_area_m2"]
                    writer.writerow([code, n, area, area / 4046.8564224])
        document = {
            "document_type": "mapcp_boundary_collection_v1",
            "status": "bundle_collected_requires_gis_review" if not errors else "bundle_collected_validation_review_required",
            "collected_at_utc": datetime.now(timezone.utc).isoformat(), "runtime_seconds": time.perf_counter() - started,
            "job_id": job_id, "preparation_directory": job.get("preparation_directory"),
            "boundary_filename": job["boundary_filename"], "boundary_sha256": job["boundary_sha256"],
            "bundle": {"file": "bundle.zip", "bytes": size, "sha256": _digest(zip_path)},
            "extract": {"folder": "extract", "geotiff_member": info["tif_member"], "member_count": info["member_count"],
                        "uncompressed_bytes": info["uncompressed_bytes"], "geotiff_sha256": _digest(tif_path)},
            "inspection": inspection, "evt_code_csv": csv_name, "limits": LIMITS,
            "usable_for_mapping": not errors, "validation_errors": errors,
            "classification_performed": False, "crosswalk_applied": False, "boundary_clipping_performed": False,
            "note": "Inspection counts cells inside the boundary. No clipped product was written; classification, crosswalk coverage review and polygonization are later stages.",
            "limitations": ["Source codes not yet checked against the approved crosswalk.",
                            "NoData/outside-boundary accounting is inspection-only.",
                            "Public modeled vegetation data are not field inventory or legal-boundary evidence."]}
        _write_json(collection_path, document)
        return AcquisitionResult(status=document["status"], stage="complete", job_submitted=True, job_id=job_id,
                                 rasters_downloaded=True, usable_for_mapping=not errors,
                                 summary={"bundle_bytes": size, "inspection": {k: v for k, v in inspection.items() if k != "evt_code_counts"}},
                                 errors=errors, artifacts={"collection": "collection.json", "bundle": "bundle.zip", "extract": "extract"})
    except Exception as exc:
        errors = [f"{type(exc).__name__}: {_redact(str(exc))}"]
        if part is not None and part.exists():
            part.unlink()
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        stamp = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:4]}"
        downloaded = False
        if directory is not None and collection_path is not None and not collection_path.exists():
            # Preserve failed evidence under new names so a corrected retry is possible and nothing is overwritten.
            for original, preserved in ((zip_path, f"bundle_failed_{stamp}.zip"), (extract_path, f"extract_failed_{stamp}")):
                if original is not None and original.exists() and original.parent == directory:
                    downloaded = downloaded or original == zip_path
                    try:
                        original.rename(directory / preserved)
                    except OSError as rename_error:
                        errors.append(f"Could not preserve failed artifact: {rename_error}")
        return _failure("collect_bundle", errors, job_submitted=True, rasters_downloaded=downloaded,
                        warnings=["Failed artifacts, if any, were renamed *_failed_* and must not be used for mapping."])


if __name__ == "__main__":
    import argparse
    import getpass
    import sys

    root = Path(__file__).resolve().parent / "outputs"
    parser = argparse.ArgumentParser(description="Boundary-aware LFPS acquisition. 'preview' makes no network request.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preview"); p.add_argument("preparation_directory")
    p = sub.add_parser("submit"); p.add_argument("preparation_directory"); p.add_argument("--approval", required=True)
    p = sub.add_parser("recover"); p.add_argument("preparation_directory"); p.add_argument("job_id")
    p = sub.add_parser("status"); p.add_argument("acquisition_directory")
    p = sub.add_parser("collect"); p.add_argument("acquisition_directory"); p.add_argument("status_filename")
    p.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if args.command == "preview":
        result = preview_boundary_submission(root, args.preparation_directory)
    elif args.command == "submit":
        # Session-only variable first (for consoles without hidden input), else the hidden prompt.
        email = os.environ.get("MAPCP_LFPS_CONTACT_EMAIL", "").strip()
        if not email:
            email = getpass.getpass("LFPS contact email (input hidden; not stored): ").strip()
        try:
            submit_request = SubmitRequest(preparation_directory=args.preparation_directory,
                                           request_contact_email=email, submission_approval=args.approval)
        except Exception:
            print("Invalid submission input (details withheld to avoid printing the email). "
                  "Check the contact email and approval token. Nothing was submitted.")
            sys.exit(2)
        result = submit_boundary_job(root, submit_request)
    elif args.command == "recover":
        result = record_recovered_job(root, args.preparation_directory, args.job_id)
    elif args.command == "status":
        result = check_boundary_job(root, StatusRequest(acquisition_directory=args.acquisition_directory))
    else:
        if not args.confirm:
            print("Add --confirm to download and validate the bundle."); sys.exit(2)
        result = collect_boundary_bundle(root, CollectRequest(acquisition_directory=args.acquisition_directory,
                                                              status_filename=args.status_filename,
                                                              collection_approval=COLLECTION_PHRASE))
    print(result.model_dump_json(indent=2))
    raise SystemExit(0 if result.status != "failed" else 1)
