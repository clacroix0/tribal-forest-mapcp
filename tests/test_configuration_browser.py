"""Synthetic review tests. No real operator, source raster, or cloud service."""
import base64
import copy
import hashlib
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import configuration_browser as cb
import boundary_mapping as bm
from source_configuration import build_source_configuration
from crosswalk_proposal import build_crosswalk_proposal
from crosswalk_review import build_crosswalk_review


@pytest.fixture
def setup(tmp_path, monkeypatch):
    data = b"VALUE,NAME\n10,Synthetic tree\n"
    profile = {"product": "EVT", "version": "synthetic", "region": "CONUS"}
    source = build_source_configuration(
        data, [10, 40], raster_profile=profile,
        catalog_record={**profile, "source_url": "https://www.landfire.gov/synthetic.csv",
                        "sha256": hashlib.sha256(data).hexdigest()},
        code_column="VALUE", name_column="NAME")
    proposal = build_crosswalk_proposal(source, {
        "source_configuration_sha256": source["configuration_sha256"],
        "classes": [
            {"output_code": 10, "label": "synthetic_tree", "rationale": "Synthetic only"},
            {"output_code": 40, "label": "unknown_40", "rationale": "Preserve unknown"}],
        "decisions": [
            {"source_evt_code": 10, "output_code": 10, "proposed_forest_land": True,
             "rationale": "Synthetic only", "unresolved": []},
            {"source_evt_code": 40, "output_code": 40, "proposed_forest_land": None,
             "rationale": "Unknown remains unknown", "unresolved": ["Missing official label"]}]})
    evidence = {
        "source_run_id": "bacq_synthetic", "boundary_sha256": "a" * 64,
        "source_raster_sha256": "b" * 64,
        "source_configuration_sha256": source["configuration_sha256"],
        "proposal_sha256": proposal["proposal_sha256"], "total_grid_cells": 3,
        "outside_boundary_cells": 0, "evt_nodata_inside_boundary_cells": 1,
        "evt_counts": [{"source_evt_code": 10, "cell_count": 1},
                       {"source_evt_code": 40, "cell_count": 1}]}
    result = {"status": "draft_review_complete_requires_human_review",
              "acquisition_directory": "bacq_synthetic", "source_configuration": source,
              "proposal": proposal, "review": build_crosswalk_review(source, proposal, evidence),
              "limitations": ["Synthetic only; not actual forestry approval"]}
    settings = cb.Settings("https://review.example.test", "operator", "p" * 48,
                           "s" * 48, tmp_path / "state")
    service = cb.ReviewService(tmp_path / "outputs", tmp_path / "data", settings)
    monkeypatch.setattr(cb, "review_source_configuration", lambda *args: copy.deepcopy(result))
    monkeypatch.setattr(cb, "runtime_service", lambda *args, **kwargs: service)
    monkeypatch.setenv("MAPCP_CONFIG_REVIEW_ENABLED", "true")
    cb._failures.clear()
    return service, result


def pending(service):
    return service.request_review({"acquisition_directory": "bacq_synthetic", "proposal": None})


def approve(service, review_id):
    return service.decide(review_id, "approve", service.csrf(service.row(review_id)))


def test_request_and_get_do_not_save_configuration(setup):
    service, _ = setup
    result = pending(service)
    assert result["configuration_saved"] is False
    assert not (service.data / "run_crosswalks").exists()
    app = Starlette(routes=cb.browser_routes())
    with TestClient(app, base_url=service.settings.origin) as client:
        response = client.get("/configuration-review/" + result["review_id"],
                              auth=(service.settings.username, service.settings.password))
    assert response.status_code == 200
    assert "unknown_40" in response.text
    assert "Complete reviewed evidence" in response.text
    assert not (service.data / "run_crosswalks").exists()


def test_approve_real_documents_and_mapping_validation(setup):
    service, _ = setup
    review_id = pending(service)["review_id"]
    saved = approve(service, review_id)
    assert saved["configuration_saved"] is True
    assert saved["classification_performed"] is False
    cw, _ = bm.load_crosswalk(service.data, saved["configuration_id"])
    assert next(e for e in cw["entries"] if e["evt_code"] == 40)["candidate_forest_land"] is None
    cb.local.validate_run_binding(service.data, "bacq_synthetic", {
        "boundary_sha256": "a" * 64, "extract": {"geotiff_sha256": "b" * 64}}, cw)
    assert service.status(review_id)["configuration_id"] == saved["configuration_id"]


def test_rejection_no_configuration(setup):
    service, _ = setup
    review_id = pending(service)["review_id"]
    result = service.decide(review_id, "reject", service.csrf(service.row(review_id)))
    assert result["status"] == "rejected"
    assert not (service.data / "run_crosswalks").exists()


def test_changed_review_no_configuration(setup, monkeypatch):
    service, original = setup
    review_id = pending(service)["review_id"]
    changed = copy.deepcopy(original)
    changed["limitations"].append("Changed")
    monkeypatch.setattr(cb, "review_source_configuration", lambda *args: changed)
    with pytest.raises(cb.ReviewError, match="changed"):
        approve(service, review_id)
    assert not (service.data / "run_crosswalks").exists()


def test_expired_request_no_configuration(setup, monkeypatch):
    service, _ = setup
    review_id = pending(service)["review_id"]
    expires = service.row(review_id)["expires"]
    monkeypatch.setattr(cb.time, "time", lambda: expires + 1)
    with pytest.raises(cb.ReviewError, match="expired"):
        approve(service, review_id)
    assert not (service.data / "run_crosswalks").exists()


def test_replay_refused(setup):
    service, _ = setup
    review_id = pending(service)["review_id"]
    approve(service, review_id)
    with pytest.raises(cb.ReviewError, match="replay"):
        approve(service, review_id)


def test_wrong_run_and_tampered_record_refused(setup):
    service, _ = setup
    saved = approve(service, pending(service)["review_id"])
    cw, _ = bm.load_crosswalk(service.data, saved["configuration_id"])
    with pytest.raises(ValueError, match="does not match"):
        cb.local.validate_run_binding(service.data, "bacq_different", {
            "boundary_sha256": "a" * 64, "extract": {"geotiff_sha256": "b" * 64}}, cw)
    record = cb.local._read(service.data / "approvals" / cw["approval_record_filename"])
    record["browser_operator"] = "forged"
    with pytest.raises(cb.ReviewError, match="signature"):
        service.validate(cw, record)


def test_bad_form_token_no_configuration(setup):
    service, _ = setup
    review_id = pending(service)["review_id"]
    with pytest.raises(cb.ReviewError, match="form token"):
        service.decide(review_id, "approve", "forged")
    assert not (service.data / "run_crosswalks").exists()


def test_bearer_and_unauthenticated_browser_cannot_approve(setup):
    service, _ = setup
    review_id = pending(service)["review_id"]
    path = "/configuration-review/" + review_id
    with TestClient(Starlette(routes=cb.browser_routes()), base_url=service.settings.origin) as client:
        assert client.get(path).status_code == 401
        response = client.post(path, headers={"Authorization": "Bearer " + "a" * 48,
                                              "Origin": service.settings.origin},
                               data={"decision": "approve", "csrf": service.csrf(service.row(review_id))})
    assert response.status_code == 401
    assert not (service.data / "run_crosswalks").exists()


def test_browser_origin_csrf_and_http_denied(setup):
    service, _ = setup
    review_id = pending(service)["review_id"]
    path = "/configuration-review/" + review_id
    auth = (service.settings.username, service.settings.password)
    with TestClient(Starlette(routes=cb.browser_routes()), base_url=service.settings.origin) as client:
        assert client.post(path, auth=auth, headers={"Origin": "https://other.example"},
                           data={"decision": "approve", "csrf": service.csrf(service.row(review_id))}).status_code == 409
        assert client.post(path, auth=auth, headers={"Origin": service.settings.origin},
                           data={"decision": "approve", "csrf": "wrong"}).status_code == 409
        assert client.get("http://review.example.test" + path, auth=auth).status_code == 403
    assert not (service.data / "run_crosswalks").exists()


def test_real_browser_approval_post(setup):
    service, _ = setup
    review_id = pending(service)["review_id"]
    with TestClient(Starlette(routes=cb.browser_routes()), base_url=service.settings.origin) as client:
        response = client.post("/configuration-review/" + review_id,
                               auth=(service.settings.username, service.settings.password),
                               headers={"Origin": service.settings.origin},
                               data={"decision": "approve", "csrf": service.csrf(service.row(review_id))})
    assert response.status_code == 200
    assert service.status(review_id)["configuration_saved"] is True


def test_partial_write_is_not_approved(setup, monkeypatch):
    service, _ = setup
    review_id = pending(service)["review_id"]
    def broken_writer(root, name, cw, record_name, record):
        directory = Path(root) / "approvals"
        directory.mkdir(parents=True)
        (directory / record_name).write_text(cb.canonical(record))
        raise OSError("SIMULATED storage failure")
    monkeypatch.setattr(cb.local, "_write_documents", broken_writer)
    with pytest.raises(cb.ReviewError, match="incomplete files"):
        approve(service, review_id)
    assert service.status(review_id)["status"] == "failed_storage"
    assert not (service.data / "run_crosswalks").exists()


def test_disabled_http_and_runtime_settings(setup, monkeypatch):
    service, _ = setup
    monkeypatch.delenv("MAPCP_CONFIG_REVIEW_ENABLED", raising=False)
    with pytest.raises(cb.ReviewError, match="disabled"):
        cb.Settings.from_env()
    with TestClient(Starlette(routes=cb.browser_routes()), base_url=service.settings.origin) as client:
        assert client.get("/configuration-review/cr_" + "0" * 32).status_code == 404


def test_state_survives_service_recreation(setup):
    service, _ = setup
    review_id = pending(service)["review_id"]
    saved = approve(service, review_id)
    recreated = cb.ReviewService(service.outputs, service.data, service.settings)
    assert recreated.status(review_id)["configuration_id"] == saved["configuration_id"]


def test_outer_bearer_guard_preserved_and_browser_independently_protected(setup):
    # Isolates the actual middleware class to avoid importing the GIS MCP server.
    import ast
    import secrets
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    service, _ = setup
    path = Path(__file__).resolve().parents[1] / "server_http.py"
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                and n.name == "RequireBearerToken")
    namespace = {"secrets": secrets, "JSONResponse": JSONResponse}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    async def ok(request):
        return JSONResponse({"ok": True})
    app = Starlette(routes=cb.browser_routes() + [
        Route("/health", ok), Route("/mcp", ok)])
    protected = namespace["RequireBearerToken"](app, "a" * 48)
    review_id = pending(service)["review_id"]
    with TestClient(protected, base_url=service.settings.origin) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/mcp").status_code == 401
        assert client.get("/mcp", headers={"Authorization": "Bearer " + "a" * 48}).status_code == 200
        assert client.get("/configuration-review/" + review_id).status_code == 401
        assert client.get("/configuration-review/" + review_id,
                          auth=(service.settings.username, service.settings.password)).status_code == 200


def test_expiry_during_fresh_review_no_configuration(setup, monkeypatch):
    service, original = setup
    review_id = pending(service)["review_id"]
    expires = service.row(review_id)["expires"]
    def slow_review(*args):
        monkeypatch.setattr(cb.time, "time", lambda: expires + 1)
        return copy.deepcopy(original)
    monkeypatch.setattr(cb, "review_source_configuration", slow_review)
    with pytest.raises(cb.ReviewError, match="expired during"):
        approve(service, review_id)
    assert not (service.data / "run_crosswalks").exists()


def test_pending_capacity_no_automatic_pruning(setup, monkeypatch):
    service, _ = setup
    monkeypatch.setattr(cb, "MAX_REVIEWS", 1)
    review_id = pending(service)["review_id"]
    with pytest.raises(cb.ReviewError, match="capacity"):
        pending(service)
    assert service.status(review_id)["status"] == "pending"


def test_signing_key_change_refuses_saved_approval(setup):
    service, _ = setup
    review_id = pending(service)["review_id"]
    saved = approve(service, review_id)
    settings = cb.Settings(service.settings.origin, service.settings.username,
                           service.settings.password, "different" * 8,
                           service.settings.state_dir)
    changed = cb.ReviewService(service.outputs, service.data, settings)
    cw, _ = bm.load_crosswalk(service.data, saved["configuration_id"])
    record = cb.local._read(service.data / "approvals" / cw["approval_record_filename"])
    with pytest.raises(cb.ReviewError, match="signature"):
        changed.validate(cw, record)


def test_review_id_path_rejected(setup):
    service, _ = setup
    with pytest.raises(cb.ReviewError, match="Invalid review ID"):
        service.status("../../other")


@pytest.fixture
def browser_settings_env(tmp_path, monkeypatch):
    """Isolated synthetic settings; no runtime service or storage creation."""
    values = {
        "MAPCP_CONFIG_REVIEW_ENABLED": "true",
        "MAPCP_CONFIG_STORAGE_APPROVED": "true",
        "MAPCP_CONFIG_REVIEW_ORIGIN": "https://review.example.test",
        "MAPCP_CONFIG_REVIEW_USER": "test_operator",
        "MAPCP_CONFIG_REVIEW_PASSWORD": "p" * 48,
        "MAPCP_CONFIG_SIGNING_KEY": "s" * 48,
        "MAPCP_API_TOKEN": "a" * 48,
        "MAPCP_CONFIG_STATE_DIR": str(tmp_path / "review-state"),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def test_browser_settings_accept_valid_environment_without_creating_storage(
    browser_settings_env,
):
    settings = cb.Settings.from_env()

    assert settings.origin == browser_settings_env["MAPCP_CONFIG_REVIEW_ORIGIN"]
    assert settings.username == browser_settings_env["MAPCP_CONFIG_REVIEW_USER"]
    assert settings.password == browser_settings_env["MAPCP_CONFIG_REVIEW_PASSWORD"]
    assert settings.signing_key == browser_settings_env["MAPCP_CONFIG_SIGNING_KEY"]
    assert settings.state_dir == Path(browser_settings_env["MAPCP_CONFIG_STATE_DIR"])
    assert not settings.state_dir.exists()

    assert settings.password not in repr(settings)
    assert settings.signing_key not in repr(settings)


@pytest.mark.parametrize(
    "name,value",
    [
        ("MAPCP_CONFIG_REVIEW_ENABLED", None),
        ("MAPCP_CONFIG_REVIEW_ENABLED", "false"),
        ("MAPCP_CONFIG_STORAGE_APPROVED", None),
        ("MAPCP_CONFIG_STORAGE_APPROVED", "false"),
        ("MAPCP_CONFIG_REVIEW_ORIGIN", None),
        ("MAPCP_CONFIG_REVIEW_ORIGIN", "http://review.example.test"),
        ("MAPCP_CONFIG_REVIEW_ORIGIN", "https://review.example.test/"),
        ("MAPCP_CONFIG_REVIEW_ORIGIN", "https://review.example.test/path"),
        ("MAPCP_CONFIG_REVIEW_ORIGIN", "https://review.example.test?query=1"),
        ("MAPCP_CONFIG_REVIEW_ORIGIN", "https://review.example.test#fragment"),
        ("MAPCP_CONFIG_REVIEW_ORIGIN", "https://user:password@review.example.test"),
        ("MAPCP_CONFIG_REVIEW_USER", None),
        ("MAPCP_CONFIG_REVIEW_USER", "operator with spaces"),
        ("MAPCP_CONFIG_REVIEW_PASSWORD", None),
        ("MAPCP_CONFIG_REVIEW_PASSWORD", "short"),
        ("MAPCP_CONFIG_REVIEW_PASSWORD", "p" * 47 + " "),
        ("MAPCP_CONFIG_REVIEW_PASSWORD", "p" * 47 + "\u00e9"),
        ("MAPCP_CONFIG_SIGNING_KEY", None),
        ("MAPCP_CONFIG_SIGNING_KEY", "short"),
        ("MAPCP_CONFIG_SIGNING_KEY", "s" * 47 + "\t"),
        ("MAPCP_CONFIG_SIGNING_KEY", "s" * 47 + "\u00e9"),
        ("MAPCP_CONFIG_STATE_DIR", None),
        ("MAPCP_CONFIG_STATE_DIR", "relative/review-state"),
    ],
)
def test_browser_settings_reject_invalid_environment(
    browser_settings_env, monkeypatch, name, value,
):
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)

    with pytest.raises(cb.ReviewError):
        cb.Settings.from_env()

    assert not Path(browser_settings_env["MAPCP_CONFIG_STATE_DIR"]).exists()


@pytest.mark.parametrize(
    "target,source",
    [
        ("MAPCP_CONFIG_REVIEW_PASSWORD", "MAPCP_CONFIG_SIGNING_KEY"),
        ("MAPCP_CONFIG_REVIEW_PASSWORD", "MAPCP_API_TOKEN"),
        ("MAPCP_CONFIG_SIGNING_KEY", "MAPCP_API_TOKEN"),
    ],
)
def test_browser_settings_reject_reused_credentials(
    browser_settings_env, monkeypatch, target, source,
):
    monkeypatch.setenv(target, browser_settings_env[source])

    with pytest.raises(cb.ReviewError, match="must be different"):
        cb.Settings.from_env()

    assert not Path(browser_settings_env["MAPCP_CONFIG_STATE_DIR"]).exists()
