"""Mocked service responses only; no live LFPS requests or job submissions."""
from pathlib import Path
import json
import sys
import pytest
from pydantic import ValidationError
ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/"boundary_service_contract.py").is_file():
    ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import boundary_service_contract as c


def schema():
    return {"openapi":"3.0.1","info":{"title":"SYNTHETIC SCHEMA"},"paths":{
        "/api/job/submit":{"get":{"parameters":[{"name":name,"in":"query","schema":{"type":"string"}} for name in sorted(c.EXPECTED_SUBMIT_PARAMETERS)],"responses":{"200":{"description":"Synthetic accepted response"}}}},
        "/api/job/status":{"get":{"parameters":[{"name":"JobId","in":"query","required":True,"schema":{"type":"string"}}],"responses":{"200":{"description":"Synthetic status"}}}},
    }}


def prep(root):
    boundary=root/"b.geojson"
    boundary.write_text('{"type":"FeatureCollection","features":[]}')
    directory=root/"boundaryprep_example"
    directory.mkdir()
    document={"document_type":"mapcp_full_boundary_request_v1","status":"prepared_review_required",
              "source_boundary_filename":"b.geojson","source_boundary_sha256":c._digest(boundary),
              "products":["LF2025_EVT","LF2025_EVC","LF2025_EVH"]}
    (directory/"boundary_request.json").write_text(json.dumps(document))
    return c.ContractInspectionRequest(preparation_directory=directory.name),directory,boundary


def fake_read(kind):
    if kind=="schema":
        return json.dumps(schema()).encode(),"application/json"
    if kind=="health":
        return b'{"success":true,"status":"healthy"}',"application/json"
    return b'<table>LF2025_EVT LF2025_EVC LF2025_EVH</table>',"text/html"


def test_schema_signatures_match():
    report=c.inspect_schema(schema())
    assert report["request_signature_matches_previous_sample_contract"]
    assert report["remote_size_limits_verified"] is False
    assert report["runtime_responses_verified"] is False


def test_missing_parameter_rejected():
    doc=schema()
    doc["paths"]["/api/job/submit"]["get"]["parameters"]=[p for p in doc["paths"]["/api/job/submit"]["get"]["parameters"] if p["name"]!="Email"]
    with pytest.raises(c.ContractInspectionError,match="missing"):
        c.inspect_schema(doc)


def test_changed_method_rejected():
    doc=schema(); doc["paths"]["/api/job/submit"]["post"]=doc["paths"]["/api/job/submit"].pop("get")
    with pytest.raises(c.ContractInspectionError,match="GET"):
        c.inspect_schema(doc)


def test_new_required_parameter_rejected():
    doc=schema(); doc["paths"]["/api/job/submit"]["get"]["parameters"].append({"name":"Token","in":"query","required":True})
    with pytest.raises(c.ContractInspectionError,match="required"):
        c.inspect_schema(doc)


def test_get_body_rejected():
    doc=schema(); doc["paths"]["/api/job/submit"]["get"]["requestBody"]={"required":True}
    with pytest.raises(c.ContractInspectionError,match="body"):
        c.inspect_schema(doc)


def test_new_authentication_rejected():
    doc=schema(); doc["security"]=[{"token":[]}]
    with pytest.raises(c.ContractInspectionError,match="authentication"):
        c.inspect_schema(doc)


def test_local_parameter_ref_supported():
    doc=schema(); parameter=doc["paths"]["/api/job/status"]["get"]["parameters"][0]
    doc["components"]={"parameters":{"job":parameter}}
    doc["paths"]["/api/job/status"]["get"]["parameters"]=[{"$ref":"#/components/parameters/job"}]
    assert c.inspect_schema(doc)["request_signature_matches_previous_sample_contract"]


def test_remote_parameter_ref_rejected():
    doc=schema();doc["paths"]["/api/job/status"]["get"]["parameters"]=[{"$ref":"https://example.invalid/parameter"}]
    with pytest.raises(c.ContractInspectionError,match="local"):
        c.inspect_schema(doc)


def test_submission_endpoint_cannot_be_read_by_helper():
    with pytest.raises(c.ContractInspectionError,match="permitted"):
        c._read_endpoint("submit")
    assert set(c.URLS)=={"health","schema","products"}
    assert all("/job/submit" not in url for url in c.URLS.values())


def test_mocked_success_never_execution_ready(tmp_path,monkeypatch):
    request,directory,boundary=prep(tmp_path)
    before=c._digest(boundary)
    calls=[]
    def reader(kind):
        calls.append(kind);return fake_read(kind)
    monkeypatch.setattr(c,"_read_endpoint",reader)
    result=c.inspect_boundary_service_contract(tmp_path,request)
    assert result["status"]=="request_signature_and_catalog_inspected_limits_unverified"
    assert result["execution_ready"] is False and result["job_submitted"] is False
    assert result["rasters_downloaded"] is False
    assert calls==["health","schema","products"]
    assert c._digest(boundary)==before
    assert Path(result["report_path"]).is_file()
    assert not (directory/"service_contract_check.json").exists()


def test_failed_source_is_explicit(tmp_path,monkeypatch):
    request,_,_=prep(tmp_path)
    def reader(kind):
        if kind=="schema": raise OSError("SIMULATED source failure")
        return fake_read(kind)
    monkeypatch.setattr(c,"_read_endpoint",reader)
    result=c.inspect_boundary_service_contract(tmp_path,request)
    assert result["status"]=="verification_incomplete"
    assert result["endpoints"]["schema"]["read_success"] is False
    assert "SIMULATED" in result["endpoints"]["schema"]["error"]


def test_products_missing_not_claimed_available(tmp_path,monkeypatch):
    request,_,_=prep(tmp_path)
    monkeypatch.setattr(c,"_read_endpoint",lambda kind:(b'<html>JavaScript app</html>',"text/html") if kind=="products" else fake_read(kind))
    result=c.inspect_boundary_service_contract(tmp_path,request)
    assert result["status"]=="verification_incomplete"
    assert result["endpoints"]["products"]["all_requested_identifiers_found"] is False


def test_false_health_blocks_success(tmp_path,monkeypatch):
    request,_,_=prep(tmp_path)
    monkeypatch.setattr(c,"_read_endpoint",lambda kind:(b'{"success":false}',"application/json") if kind=="health" else fake_read(kind))
    result=c.inspect_boundary_service_contract(tmp_path,request)
    assert result["status"]=="verification_incomplete"


def test_boundary_changed_before_inspection_rejected(tmp_path):
    request,_,boundary=prep(tmp_path);boundary.write_text("changed")
    with pytest.raises(c.ContractInspectionError,match="changed"):
        c.inspect_boundary_service_contract(tmp_path,request)


def test_boundary_changed_during_inspection_rejected(tmp_path,monkeypatch):
    request,_,boundary=prep(tmp_path)
    def reader(kind):
        boundary.write_text("changed");return fake_read(kind)
    monkeypatch.setattr(c,"_read_endpoint",reader)
    with pytest.raises(c.ContractInspectionError,match="changed"):
        c.inspect_boundary_service_contract(tmp_path,request)


def test_repeated_inspections_do_not_overwrite(tmp_path,monkeypatch):
    request,_,_=prep(tmp_path);monkeypatch.setattr(c,"_read_endpoint",fake_read)
    one=c.inspect_boundary_service_contract(tmp_path,request)
    two=c.inspect_boundary_service_contract(tmp_path,request)
    assert one["report_path"]!=two["report_path"]


@pytest.mark.parametrize("name",["../boundaryprep_x","boundaryprep_x/y","C:\\boundaryprep_x"])
def test_path_injection_rejected(name):
    with pytest.raises(ValidationError):
        c.ContractInspectionRequest(preparation_directory=name)


def test_failed_preparation_rejected(tmp_path):
    request,directory,_=prep(tmp_path);(directory/"FAILED_DO_NOT_USE.json").write_text("{}")
    with pytest.raises(c.ContractInspectionError,match="failed"):
        c.inspect_boundary_service_contract(tmp_path,request)


def test_error_emails_redacted(tmp_path,monkeypatch):
    request,_,_=prep(tmp_path)
    def reader(kind):raise OSError("SIMULATED contact person@example.invalid")
    monkeypatch.setattr(c,"_read_endpoint",reader)
    result=c.inspect_boundary_service_contract(tmp_path,request)
    assert "person@example.invalid" not in json.dumps(result)
    assert "redacted-email" in json.dumps(result)
