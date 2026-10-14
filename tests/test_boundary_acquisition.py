"""Mocked-HTTP and fixture tests. No live LFPS requests, no job submission, no real LANDFIRE data.

Tests that need rasterio build tiny synthetic GeoTIFFs and are skipped if rasterio is unavailable.
"""
import hashlib
import io
import json
import sys
import uuid
import zipfile
from pathlib import Path

import geopandas as gpd
import httpx
import pytest
from pydantic import ValidationError
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "boundary_acquisition.py").is_file():
    ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import boundary_acquisition as ba

EMAIL = "reviewer.person@example.org"
JOB = "123e4567-e89b-42d3-a456-426614174000"
OUTPUT_URL = ("https://lfps.usgs.gov/arcgis/rest/directories/arcgisjobs/"
              "landfireproductservice_gpserver/j123/scratch/LFPS_download.zip")


class Net:
    def __init__(self, monkeypatch, handler):
        self.requests = []
        def wrapped(request):
            self.requests.append(request)
            return handler(request)
        monkeypatch.setattr(ba, "_client", lambda timeout: httpx.Client(
            transport=httpx.MockTransport(wrapped), timeout=timeout, follow_redirects=False))


@pytest.fixture(autouse=True)
def plenty_of_disk(monkeypatch):
    monkeypatch.setattr(ba.shutil, "disk_usage", lambda path: type("U", (), {"free": 10 ** 13})())
    monkeypatch.setattr(ba.time, "sleep", lambda seconds: None)


def make_prep(root, name="boundaryprep_example"):
    boundary = root / "project_boundary.geojson"
    gpd.GeoDataFrame({"geometry": [box(-105.9, 33.0, -105.8, 33.1)]}, crs="EPSG:4326").to_file(boundary, driver="GeoJSON", engine="pyogrio")
    frame = gpd.read_file(boundary, engine="pyogrio")
    parameters, summary = ba._expected_parameters(frame)
    directory = root / name
    directory.mkdir()
    proposal = {"document_type": "mapcp_full_boundary_request_v1", "status": "prepared_review_required",
                "products": ba.PRODUCTS, "source_boundary_filename": boundary.name,
                "source_boundary_sha256": ba._digest(boundary), "proposed_parameters_without_email": parameters}
    (directory / "boundary_request.json").write_text(json.dumps(proposal), encoding="utf-8")
    token = ba.preview_boundary_submission(root, name).summary["approval_token"]
    return name, directory, boundary, token


def submit_request(name, token, email=EMAIL):
    return ba.SubmitRequest(preparation_directory=name, request_contact_email=email, submission_approval=token)


def ok_submit(request):
    return httpx.Response(200, json={"success": True, "jobId": JOB, "status": "Pending"})


def all_text(root):
    return b"\n".join(p.read_bytes() for p in Path(root).rglob("*") if p.is_file())


# ---- preview and approval --------------------------------------------------------------------
def test_preview_has_no_network_and_binds_token(tmp_path, monkeypatch):
    name, _, _, token = make_prep(tmp_path)
    monkeypatch.setattr(ba, "_client", lambda timeout: (_ for _ in ()).throw(AssertionError("network forbidden")))
    result = ba.preview_boundary_submission(tmp_path, name)
    assert result.status == "preview_requires_user_approval" and not result.job_submitted
    assert "Email" not in result.summary["parameters_without_email"]
    assert result.summary["approval_token"] == token
    assert result.summary["proposed_limits"]["max_bundle_bytes"] == ba.LIMITS["max_bundle_bytes"]


def test_token_changes_when_limits_change(tmp_path, monkeypatch):
    name, _, _, token = make_prep(tmp_path)
    monkeypatch.setitem(ba.LIMITS, "max_bundle_bytes", 1)
    assert ba.preview_boundary_submission(tmp_path, name).summary["approval_token"] != token


def test_wrong_token_blocks_before_network_or_lock(tmp_path, monkeypatch):
    name, directory, _, _ = make_prep(tmp_path)
    net = Net(monkeypatch, ok_submit)
    result = ba.submit_boundary_job(tmp_path, submit_request(name, "submit_000000000000"))
    assert result.status == "failed" and not net.requests
    assert not (directory / "submission_lock.json").exists()


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "x" * 300 + "@example.org"])
def test_invalid_email_blocks(tmp_path, monkeypatch, email):
    name, _, _, token = make_prep(tmp_path)
    net = Net(monkeypatch, ok_submit)
    try:
        request = submit_request(name, token, email)
    except ValidationError:
        return
    assert ba.submit_boundary_job(tmp_path, request).status == "failed" and not net.requests


def test_any_valid_email_domain_accepted(tmp_path, monkeypatch):
    name, _, _, token = make_prep(tmp_path)
    Net(monkeypatch, ok_submit)
    assert ba.submit_boundary_job(tmp_path, submit_request(name, token, "person@tribe.example.org")).job_submitted is True


def test_changed_boundary_blocks(tmp_path, monkeypatch):
    name, _, boundary, token = make_prep(tmp_path)
    net = Net(monkeypatch, ok_submit)
    boundary.write_text(boundary.read_text() + " ")
    assert ba.submit_boundary_job(tmp_path, submit_request(name, token)).status == "failed" and not net.requests


def test_tampered_parameters_block(tmp_path, monkeypatch):
    name, directory, _, token = make_prep(tmp_path)
    path = directory / "boundary_request.json"
    doc = json.loads(path.read_text())
    doc["proposed_parameters_without_email"]["Area_of_Interest"] = "-125 24 -66 50"
    path.write_text(json.dumps(doc))
    net = Net(monkeypatch, ok_submit)
    result = ba.submit_boundary_job(tmp_path, submit_request(name, token))
    assert result.status == "failed" and not net.requests and "recomputed" in result.errors[0]


def test_failed_preparation_blocks(tmp_path):
    name, directory, _, _ = make_prep(tmp_path)
    (directory / "FAILED_DO_NOT_USE.json").write_text("{}")
    assert ba.preview_boundary_submission(tmp_path, name).status == "failed"


# ---- submission -------------------------------------------------------------------------------
def test_successful_submission_request_and_privacy(tmp_path, monkeypatch):
    name, directory, _, token = make_prep(tmp_path)
    net = Net(monkeypatch, ok_submit)
    result = ba.submit_boundary_job(tmp_path, submit_request(name, token))
    assert result.status == "submitted_waiting_for_completion" and result.job_submitted is True and result.job_id == JOB
    request = net.requests[0]
    assert request.method == "GET" and str(request.url).startswith(ba.SUBMIT_URL)
    params = dict(request.url.params)
    assert params["Email"] == EMAIL and params["Layer_List"] == "LF2025_EVT;LF2025_EVC;LF2025_EVH"
    assert params["Output_Projection"] == "5070" and params["Include_Layer_List_XML_File"] == "true"
    assert len(net.requests) == 1
    assert EMAIL.encode() not in all_text(tmp_path) and EMAIL not in result.model_dump_json()
    job = json.loads((tmp_path / result.artifacts["acquisition_directory"] / "job.json").read_text())
    assert job["contact_email_stored"] is False and job["job_id"] == JOB
    assert (directory / "submission_lock.json").exists() and (directory / "submission_result.json").exists()


def test_second_attempt_refused_without_network(tmp_path, monkeypatch):
    name, _, _, token = make_prep(tmp_path)
    net = Net(monkeypatch, ok_submit)
    ba.submit_boundary_job(tmp_path, submit_request(name, token))
    second = ba.submit_boundary_job(tmp_path, submit_request(name, token))
    assert second.status == "failed" and len(net.requests) == 1


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(200, text="<html>app shell</html>", headers={"content-type": "text/html"}),
    lambda r: httpx.Response(500, text="server error"),
    lambda r: httpx.Response(302, headers={"location": "https://example.invalid/"}),
    lambda r: httpx.Response(200, json={"success": True, "jobId": "not-a-uuid"}),
    lambda r: httpx.Response(200, json=["not", "an", "object"]),
    lambda r: (_ for _ in ()).throw(httpx.ConnectTimeout("SIMULATED timeout", request=r)),
])
def test_unknown_outcomes_keep_lock_and_block_retry(tmp_path, monkeypatch, handler):
    name, directory, _, token = make_prep(tmp_path)
    net = Net(monkeypatch, handler)
    result = ba.submit_boundary_job(tmp_path, submit_request(name, token))
    assert result.status == "failed" and result.job_submitted == "unknown"
    assert (directory / "submission_lock.json").exists()
    again = ba.submit_boundary_job(tmp_path, submit_request(name, token))
    assert again.status == "failed" and len(net.requests) == 1
    assert EMAIL not in result.model_dump_json()


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(400, text="bad request"),
    lambda r: httpx.Response(200, json={"success": False, "message": f"rejected for {EMAIL}"}),
])
def test_definite_rejection_releases_lock_and_redacts(tmp_path, monkeypatch, handler):
    name, directory, _, token = make_prep(tmp_path)
    Net(monkeypatch, handler)
    result = ba.submit_boundary_job(tmp_path, submit_request(name, token))
    assert result.status == "failed" and result.job_submitted is False
    assert not (directory / "submission_lock.json").exists()
    assert list(directory.glob("submission_rejected_*.json"))
    assert EMAIL.encode() not in all_text(tmp_path) and EMAIL not in result.model_dump_json()
    Net(monkeypatch, ok_submit)
    assert ba.submit_boundary_job(tmp_path, submit_request(name, token)).job_submitted is True


def test_quick_repeated_rejections_do_not_collide(tmp_path, monkeypatch):
    name, directory, _, token = make_prep(tmp_path)
    Net(monkeypatch, lambda r: httpx.Response(400))
    for _ in range(3):
        assert ba.submit_boundary_job(tmp_path, submit_request(name, token)).job_submitted is False
    assert len(list(directory.glob("submission_rejected_*.json"))) == 3


def test_manifest_write_failure_still_returns_job_id(tmp_path, monkeypatch):
    name, _, _, token = make_prep(tmp_path)
    Net(monkeypatch, ok_submit)
    original = ba._write_json
    def failing(path, value):
        if path.name == "job.json":
            raise OSError("SIMULATED path-length failure")
        return original(path, value)
    monkeypatch.setattr(ba, "_write_json", failing)
    result = ba.submit_boundary_job(tmp_path, submit_request(name, token))
    assert result.status == "submitted_manifest_write_failed" and result.job_id == JOB and result.job_submitted is True
    assert EMAIL not in result.model_dump_json()


def test_recover_job_without_network(tmp_path, monkeypatch):
    name, _, _, _ = make_prep(tmp_path)
    monkeypatch.setattr(ba, "_client", lambda timeout: (_ for _ in ()).throw(AssertionError("network forbidden")))
    result = ba.record_recovered_job(tmp_path, name, JOB)
    assert result.status == "recovered_manifest_written"
    assert ba.record_recovered_job(tmp_path, name, "nope").status == "failed"


# ---- status ----------------------------------------------------------------------------------
def submitted(tmp_path, monkeypatch):
    name, directory, boundary, token = make_prep(tmp_path)
    Net(monkeypatch, ok_submit)
    result = ba.submit_boundary_job(tmp_path, submit_request(name, token))
    return result.artifacts["acquisition_directory"], directory, boundary


@pytest.mark.parametrize("source,expected", [
    ("Pending", "submitted_waiting_in_queue"), ("Executing", "submitted_processing"),
    ("Succeeded", "completed_requires_output_collection"), ("Failed", "source_job_failed"),
    ("Cancelled", "source_job_canceled"), ("Odd", "source_job_status_unrecognized"),
])
def test_status_mapping_and_request(tmp_path, monkeypatch, source, expected):
    acq, _, _ = submitted(tmp_path, monkeypatch)
    net = Net(monkeypatch, lambda r: httpx.Response(200, json={"success": True, "jobId": JOB, "status": source, "outputFile": OUTPUT_URL}))
    result = ba.check_boundary_job(tmp_path, ba.StatusRequest(acquisition_directory=acq))
    assert result.status == expected
    assert net.requests[0].method == "GET" and str(net.requests[0].url).startswith(ba.STATUS_URL)
    assert dict(net.requests[0].url.params) == {"JobId": JOB}
    assert all("/job/submit" not in str(r.url) for r in net.requests)
    assert (tmp_path / acq / result.artifacts["status_report"]).is_file()


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(200, json={"success": True, "jobId": "other", "status": "Succeeded"}),
    lambda r: httpx.Response(200, json={"success": False, "jobId": JOB}),
    lambda r: httpx.Response(200, json={"success": True, "jobId": JOB}),
    lambda r: httpx.Response(200, text="<html/>", headers={"content-type": "text/html"}),
    lambda r: httpx.Response(302, headers={"location": "https://example.invalid/"}),
    lambda r: httpx.Response(500),
])
def test_bad_status_responses_fail_without_report(tmp_path, monkeypatch, handler):
    acq, _, _ = submitted(tmp_path, monkeypatch)
    Net(monkeypatch, handler)
    result = ba.check_boundary_job(tmp_path, ba.StatusRequest(acquisition_directory=acq))
    assert result.status == "failed" and not list((tmp_path / acq).glob("status_*.json"))


def test_status_retries_transport_error_once(tmp_path, monkeypatch):
    acq, _, _ = submitted(tmp_path, monkeypatch)
    calls = []
    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("SIMULATED", request=request)
        return httpx.Response(200, json={"success": True, "jobId": JOB, "status": "Pending"})
    Net(monkeypatch, handler)
    assert ba.check_boundary_job(tmp_path, ba.StatusRequest(acquisition_directory=acq)).status == "submitted_waiting_in_queue"
    assert len(calls) == 2


def test_status_rejects_bad_directory_names():
    with pytest.raises(ValidationError):
        ba.StatusRequest(acquisition_directory="../bacq_x")


# ---- collection ----------------------------------------------------------------------------------
def completed(tmp_path, monkeypatch, output_url=OUTPUT_URL, status="Succeeded"):
    acq, directory, boundary = submitted(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, json={"success": True, "jobId": JOB, "status": status, "outputFile": output_url}))
    result = ba.check_boundary_job(tmp_path, ba.StatusRequest(acquisition_directory=acq))
    return acq, result.artifacts.get("status_report"), boundary


def make_zip(files=None):
    files = files if files is not None else {"data/layers.tif": b"SYNTHETIC TIFF BYTES",
                                              **{f"data/{n}": b"<xml/>" for n in ba.EXPECTED_XML}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return buffer.getvalue()


GOOD_INSPECTION = {"band_count": 3, "validation_errors": [], "pixels_inspected": True, "cell_area_m2": 900.0,
                   "cells_inside_boundary": 3, "evt_code_counts": [[7000, 2], [7001, 1]]}


def collect(tmp_path, acq, status_file, ok=True):
    return ba.collect_boundary_bundle(tmp_path, ba.CollectRequest(
        acquisition_directory=acq, status_filename=status_file, collection_approval=ba.COLLECTION_PHRASE))


def test_successful_collection(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    net = Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    monkeypatch.setattr(ba, "_inspect_raster", lambda tif, boundary: dict(GOOD_INSPECTION))
    result = collect(tmp_path, acq, status_file)
    assert result.status == "bundle_collected_requires_gis_review" and result.usable_for_mapping and result.rasters_downloaded
    assert not result.classification_performed
    directory = tmp_path / acq
    manifest = json.loads((directory / "collection.json").read_text())
    assert manifest["classification_performed"] is False and manifest["boundary_clipping_performed"] is False
    assert manifest["bundle"]["sha256"] == hashlib.sha256((directory / "bundle.zip").read_bytes()).hexdigest()
    assert (directory / "extract" / "data" / "layers.tif").is_file()
    assert "7000" in (directory / "evt_codes_in_boundary.csv").read_text(encoding="utf-8-sig")
    assert not (directory / "bundle.part").exists() and not (directory / "extract_staging").exists()
    assert str(net.requests[0].url) == OUTPUT_URL


def test_second_collection_refused_without_network(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    net = Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    monkeypatch.setattr(ba, "_inspect_raster", lambda tif, boundary: dict(GOOD_INSPECTION))
    collect(tmp_path, acq, status_file)
    assert collect(tmp_path, acq, status_file).status == "failed" and len(net.requests) == 1


def test_raster_validation_errors_are_not_usable(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    bad = {"validation_errors": ["Expected EPSG:5070; found 4326."], "pixels_inspected": False}
    monkeypatch.setattr(ba, "_inspect_raster", lambda tif, boundary: bad)
    result = collect(tmp_path, acq, status_file)
    assert result.status == "bundle_collected_validation_review_required" and not result.usable_for_mapping
    assert not (tmp_path / acq / "evt_codes_in_boundary.csv").exists()


@pytest.mark.parametrize("url", [
    "http://lfps.usgs.gov/arcgis/rest/directories/arcgisjobs/landfireproductservice_gpserver/j/a.zip",
    "https://example.invalid/arcgis/rest/directories/arcgisjobs/landfireproductservice_gpserver/j/a.zip",
    "https://lfps.usgs.gov/other/path/a.zip",
    "https://lfps.usgs.gov/arcgis/rest/directories/arcgisjobs/landfireproductservice_gpserver/j/a.exe",
    "https://user:pw@lfps.usgs.gov/arcgis/rest/directories/arcgisjobs/landfireproductservice_gpserver/j/a.zip",
    "https://lfps.usgs.gov:8443/arcgis/rest/directories/arcgisjobs/landfireproductservice_gpserver/j/a.zip",
])
def test_output_url_allowlist(tmp_path, monkeypatch, url):
    acq, status_file, _ = completed(tmp_path, monkeypatch, output_url=url)
    net = Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    result = collect(tmp_path, acq, status_file)
    assert result.status == "failed" and not net.requests and not result.rasters_downloaded


def test_unfinished_job_not_collected(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch, status="Executing")
    net = Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    assert collect(tmp_path, acq, status_file).status == "failed" and not net.requests


def test_changed_boundary_blocks_collection(tmp_path, monkeypatch):
    acq, status_file, boundary = completed(tmp_path, monkeypatch)
    boundary.write_text(boundary.read_text() + " ")
    net = Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    assert collect(tmp_path, acq, status_file).status == "failed" and not net.requests


def test_status_from_another_job_blocked(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    path = tmp_path / acq / status_file
    doc = json.loads(path.read_text())
    doc["job_id"] = str(uuid.uuid4())
    path.write_text(json.dumps(doc))
    net = Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    assert collect(tmp_path, acq, status_file).status == "failed" and not net.requests


def zip_with(**changes):
    files = {"data/layers.tif": b"SYNTHETIC TIFF BYTES", **{f"data/{n}": b"<xml/>" for n in ba.EXPECTED_XML}}
    files.update(changes)
    return {k: v for k, v in files.items() if v is not None}


@pytest.mark.parametrize("files,message", [
    (zip_with(**{"data/LF2025_EVT_CONUS.xml": None}), "missing metadata"),
    (zip_with(**{"data/second.tif": b"x"}), "exactly one GeoTIFF"),
    (zip_with(**{"../escape.txt": b"x"}), "unsafe"),
    (zip_with(**{"/absolute.txt": b"x"}), "unsafe"),
    (zip_with(**{"C:/drive.txt": b"x"}), "unsafe"),
    ({}, "empty"),
])
def test_bad_archives_fail_and_preserve_evidence(tmp_path, monkeypatch, files, message):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip(files)))
    monkeypatch.setattr(ba, "_inspect_raster", lambda tif, boundary: dict(GOOD_INSPECTION))
    result = collect(tmp_path, acq, status_file)
    directory = tmp_path / acq
    assert result.status == "failed" and message.lower() in result.errors[0].lower()
    assert not (directory / "collection.json").exists() and not (directory / "extract").exists()
    assert not (directory / "extract_staging").exists() and not (directory / "bundle.part").exists()
    assert list(directory.glob("bundle_failed_*.zip")) and not (directory / "bundle.zip").exists()
    assert not (tmp_path / "escape.txt").exists()


def test_retry_possible_after_failed_collection(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip(zip_with(**{"data/second.tif": b"x"}))))
    assert collect(tmp_path, acq, status_file).status == "failed"
    Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    monkeypatch.setattr(ba, "_inspect_raster", lambda tif, boundary: dict(GOOD_INSPECTION))
    assert collect(tmp_path, acq, status_file).status == "bundle_collected_requires_gis_review"


def test_compression_ratio_limit(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip(zip_with(**{"data/layers.tif": b"\0" * 5_000_000}))))
    result = collect(tmp_path, acq, status_file)
    assert result.status == "failed" and "compression-ratio" in result.errors[0]


def test_extracted_size_limit(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    monkeypatch.setitem(ba.LIMITS, "max_extracted_bytes", 5)
    assert "expanded size" in collect(tmp_path, acq, status_file).errors[0]


def test_member_limit(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    monkeypatch.setitem(ba.LIMITS, "max_zip_members", 2)
    assert "member limit" in collect(tmp_path, acq, status_file).errors[0]


def test_path_length_guard(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    monkeypatch.setitem(ba.LIMITS, "max_path_chars", 20)
    assert "path limit" in collect(tmp_path, acq, status_file).errors[0]


def test_low_disk_guard(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    monkeypatch.setattr(ba.shutil, "disk_usage", lambda path: type("U", (), {"free": 1})())
    assert "free disk" in collect(tmp_path, acq, status_file).errors[0]


def test_advertised_bundle_limit(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    monkeypatch.setitem(ba.LIMITS, "max_bundle_bytes", 10)
    result = collect(tmp_path, acq, status_file)
    assert result.status == "failed" and not list((tmp_path / acq).glob("bundle*"))


def test_streaming_bundle_limit_without_content_length(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, content=iter([b"x" * 30, b"x" * 30])))
    monkeypatch.setitem(ba.LIMITS, "max_bundle_bytes", 40)
    result = collect(tmp_path, acq, status_file)
    assert result.status == "failed" and "size limit" in result.errors[0]
    assert not list((tmp_path / acq).glob("bundle*"))


def test_empty_and_redirected_downloads_fail(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, content=b""))
    assert "empty" in collect(tmp_path, acq, status_file).errors[0]
    Net(monkeypatch, lambda r: httpx.Response(302, headers={"location": "https://example.invalid/a.zip"}))
    assert "redirect" in collect(tmp_path, acq, status_file).errors[0].lower()


def test_inspection_failure_preserves_artifacts_and_blocks_use(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    def explode(tif, boundary):
        raise RuntimeError("SIMULATED raster library failure")
    monkeypatch.setattr(ba, "_inspect_raster", explode)
    result = collect(tmp_path, acq, status_file)
    directory = tmp_path / acq
    assert result.status == "failed" and not (directory / "collection.json").exists()
    assert list(directory.glob("extract_failed_*")) and list(directory.glob("bundle_failed_*.zip"))


def test_no_collection_calls_submit(tmp_path, monkeypatch):
    acq, status_file, _ = completed(tmp_path, monkeypatch)
    net = Net(monkeypatch, lambda r: httpx.Response(200, content=make_zip()))
    monkeypatch.setattr(ba, "_inspect_raster", lambda tif, boundary: dict(GOOD_INSPECTION))
    collect(tmp_path, acq, status_file)
    assert all("/job/submit" not in str(r.url) for r in net.requests)


def test_collection_phrase_is_required():
    with pytest.raises(ValidationError):
        ba.CollectRequest(acquisition_directory="bacq_x", status_filename="status_x.json", collection_approval="yes")


def test_redaction_helper():
    cleaned = ba._redact({"Email": "a@b.org", "msg": "contact a@b.org now", "nested": ["x@y.com"]})
    assert "a@b.org" not in json.dumps(cleaned) and "x@y.com" not in json.dumps(cleaned)


# ---- real raster inspection (needs rasterio; skipped in environments without it) -----------------------
def tiny_raster(path, descriptions=None, evt_values=None, origin=(-917_000.0, 1_160_000.0)):
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    from rasterio.transform import from_origin
    evt = evt_values if evt_values is not None else np.full((20, 20), 7000, dtype="int32")
    with rasterio.open(path, "w", driver="GTiff", height=20, width=20, count=3, dtype="int32", crs="EPSG:5070",
                       transform=from_origin(origin[0], origin[1], 30.0, 30.0), nodata=-9999) as dst:
        dst.write(evt, 1)
        dst.write(np.full((20, 20), 110, dtype="int32"), 2)
        dst.write(np.full((20, 20), 101, dtype="int32"), 3)
        for index, name in enumerate(descriptions or ba.EXPECTED_BANDS, start=1):
            dst.set_band_description(index, name)


def boundary_file(path, x0=-916_850.0, y0=1_159_850.0, size=300.0):
    gpd.GeoDataFrame({"geometry": [box(x0, y0 - size, x0 + size, y0)]}, crs="EPSG:5070").to_crs(4326).to_file(path, driver="GeoJSON", engine="pyogrio")


def test_real_raster_inspection_counts_codes(tmp_path):
    pytest.importorskip("rasterio")
    import numpy as np
    evt = np.full((20, 20), 7000, dtype="int32")
    evt[:, 10:] = 7001
    evt[0:2, 0:2] = -9999
    tiny_raster(tmp_path / "t.tif", evt_values=evt)
    boundary_file(tmp_path / "b.geojson")
    result = ba._inspect_raster(tmp_path / "t.tif", tmp_path / "b.geojson")
    assert result["validation_errors"] == [] and result["pixels_inspected"] is True
    assert result["cells_inside_boundary"] > 0
    codes = {code for code, count in result["evt_code_counts"]}
    assert codes <= {7000, 7001} and len(codes) >= 1
    assert result["valid_evt_cells_inside_boundary"] + result["nodata_evt_cells_inside_boundary"] == result["cells_inside_boundary"]


def test_real_raster_boundary_outside_extent_flagged(tmp_path):
    pytest.importorskip("rasterio")
    tiny_raster(tmp_path / "t.tif")
    boundary_file(tmp_path / "b.geojson", x0=-900_000.0, y0=1_100_000.0)
    result = ba._inspect_raster(tmp_path / "t.tif", tmp_path / "b.geojson")
    assert result["raster_covers_boundary_extent"] is False and result["pixels_inspected"] is False
    assert any("cover" in e for e in result["validation_errors"])


def test_real_raster_wrong_band_order_flagged(tmp_path):
    pytest.importorskip("rasterio")
    tiny_raster(tmp_path / "t.tif", descriptions=["LF2025_EVC_CONUS", "LF2025_EVT_CONUS", "LF2025_EVH_CONUS"])
    boundary_file(tmp_path / "b.geojson")
    result = ba._inspect_raster(tmp_path / "t.tif", tmp_path / "b.geojson")
    assert any("Band descriptions" in e for e in result["validation_errors"]) and result["pixels_inspected"] is False
