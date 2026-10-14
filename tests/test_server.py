# tests/test_server.py
#
# Regression baseline for Tribal Forest MapCP server.py
#
# All network calls are mocked; no live service is contacted.
# These tests verify request validation, safe error paths, artifact-identifier
# guards, ZIP safety logic, and email-redaction behaviour.
#
# Run with:  pytest tests/test_server.py -v
#
# Fixtures labelled FIXTURE or SIMULATED_FAILURE are synthetic test data and
# do not represent real LANDFIRE or imagery outputs.

import io
import json
import re
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import geopandas as gpd
import pytest
from pydantic import ValidationError
from shapely.geometry import mapping, shape

import server
from server import (
    BIA_BOUNDARY_LAYER,
    CENSUS_BOUNDARY_LAYER,
    LANDFIRE_LFPS_V2_SUBMIT_URL,
    LANDFIRE_LFPS_V2_STATUS_URL,
    LANDFIRE_LFPS_V2_OUTPUT_HOST,
    LANDFIRE_LFPS_V2_OUTPUT_PATH_PREFIX,
    LANDFIRE_LFPS_V2_SAMPLE_LAYERS,
    LANDFIRE_LFPS_V2_LAYER_LIST,
    LANDFIRE_LFPS_V2_OUTPUT_WKID,
    MappingRequest,
    OUTPUT_FOLDER,
)
from mcp.server.mcpserver.exceptions import ToolError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_polygon_geojson() -> dict:
    """FIXTURE: minimal valid single-feature CONUS GeoJSON FeatureCollection."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-105.9, 33.1],
                            [-105.8, 33.1],
                            [-105.8, 33.2],
                            [-105.9, 33.2],
                            [-105.9, 33.1],
                        ]
                    ],
                },
                "properties": {
                    "OBJECTID": 1,
                    "LARID": "NM-001",
                    "LARName": "Test Reservation",
                    "GISAcres": 50000.0,
                },
            }
        ],
    }


def _write_boundary_geojson(tmp_path: Path, name: str = "test_lar") -> Path:
    """Write a FIXTURE valid GeoJSON boundary file into a controlled folder."""
    folder = tmp_path / "outputs"
    folder.mkdir(exist_ok=True)
    run_id = "20260101T000000000000Z"
    filename = f"{name}_{run_id}.geojson"
    path = folder / filename
    path.write_text(json.dumps(_simple_polygon_geojson()), encoding="utf-8")
    return path


def _write_naip_manifest(tmp_path: Path, boundary_path: Path) -> Path:
    """Write a FIXTURE valid NAIP sample source manifest."""
    folder = tmp_path / "outputs"
    run_id = "20260101T010000000000Z"
    stem = boundary_path.stem
    manifest_name = f"{stem}_naip_sample_{run_id}_source.json"
    manifest_path = folder / manifest_name
    manifest = {
        "status": "downloaded_requires_review",
        "grid_validation_passed": True,
        "returned_footprint_within_boundary": True,
        "requested_bbox_crs": "EPSG:5070",
        "requested_bbox_epsg_5070": [-1_200_000.0, 1_500_000.0, -1_199_000.0, 1_501_000.0],
        "reference_envelope_lonlat": [-105.9, 33.1, -105.8, 33.2],
        "downloaded_file": str(folder / f"{stem}_naip_sample_{run_id}.tif"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def _write_lfps_v2_request(tmp_path: Path, naip_manifest_path: Path) -> Path:
    """Write a FIXTURE valid LFPS v2 prepared-request record."""
    folder = tmp_path / "outputs"
    run_id = "20260101T020000000000Z"
    stem = naip_manifest_path.stem
    request_name = f"{stem}_landfire_v2_request_{run_id}.json"
    request_path = folder / request_name
    west, south, east, north = -105.9, 33.1, -105.8, 33.2
    aoi_text = f"{west:.12f} {south:.12f} {east:.12f} {north:.12f}"
    record = {
        "status": "request_prepared_requires_submission_approval",
        "api_version": "LFPS v2",
        "prepared_request": str(request_path),
        "submission_method": "GET",
        "submission_endpoint": LANDFIRE_LFPS_V2_SUBMIT_URL,
        "status_endpoint": LANDFIRE_LFPS_V2_STATUS_URL,
        "layers_in_requested_band_order": LANDFIRE_LFPS_V2_SAMPLE_LAYERS,
        "layer_list": LANDFIRE_LFPS_V2_LAYER_LIST,
        "aoi_wgs84_west_south_east_north": [west, south, east, north],
        "aoi_width_degrees": east - west,
        "aoi_height_degrees": north - south,
        "output_projection_wkid": LANDFIRE_LFPS_V2_OUTPUT_WKID,
        "resample_resolution_parameter_sent": False,
        "include_layer_list_xml_file": True,
        "contact_email_required_at_submission": True,
        "contact_email_stored": False,
        "submit_parameters_without_email": {
            "Layer_List": LANDFIRE_LFPS_V2_LAYER_LIST,
            "Include_Layer_List_XML_File": "true",
            "Area_of_Interest": aoi_text,
            "Output_Projection": str(LANDFIRE_LFPS_V2_OUTPUT_WKID),
        },
        "job_submitted": False,
        "rasters_downloaded": False,
        "classification_performed": False,
    }
    request_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return request_path


def _write_lfps_v2_job_manifest(
    tmp_path: Path,
    job_id: str = "3b83d63b-cf47-47a1-8a21-09ee1659cedb",
    status: str = "completed_requires_output_collection",
    source_status: str = "succeeded",
    output_file: str | None = None,
) -> Path:
    """Write a FIXTURE LFPS v2 status report."""
    folder = tmp_path / "outputs"
    folder.mkdir(exist_ok=True)
    run_id = "20260101T030000000000Z"
    filename = f"lfps_v2_status_{run_id}_{job_id}.json"
    path = folder / filename
    if output_file is None:
        output_file = (
            f"https://{LANDFIRE_LFPS_V2_OUTPUT_HOST}"
            f"{LANDFIRE_LFPS_V2_OUTPUT_PATH_PREFIX}"
            f"{job_id}_output/bundle.zip"
        )
    record = {
        "status": status,
        "api_version": "LFPS v2",
        "status_endpoint": LANDFIRE_LFPS_V2_STATUS_URL,
        "job_id": job_id,
        "source_status": source_status,
        "output_file": output_file,
        "job_status_checked": True,
        "rasters_downloaded": False,
        "classification_performed": False,
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def _make_safe_zip(
    *,
    include_tif: bool = True,
    include_all_xml: bool = True,
    tif_name: str = "output.tif",
    path_traversal: str | None = None,
    encrypted: bool = False,
    extra_members: int = 0,
) -> bytes:
    """
    FIXTURE: build a minimal in-memory ZIP for ZIP-safety tests.

    When encrypted=True the flag byte is set manually after writing.
    """
    buf = io.BytesIO()
    xml_names = [
        "LF2025_EVT_CONUS.xml",
        "LF2025_EVC_CONUS.xml",
        "LF2025_EVH_CONUS.xml",
    ]
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        if include_tif:
            zf.writestr(tif_name, b"FAKE_TIF_CONTENT")
        if include_all_xml:
            for xml_name in xml_names:
                zf.writestr(xml_name, b"<xml/>")
        if path_traversal:
            zf.writestr(path_traversal, b"bad")
        for i in range(extra_members):
            zf.writestr(f"extra_{i}.dat", b"x")
    data = buf.getvalue()
    if encrypted:
        # Flip the encryption bit (bit 0) in the local file header flags.
        # ZIP local file header: signature(4)+version(2)+flags(2)+...
        # First entry starts at offset 0; flags field is at offset 6.
        data = bytearray(data)
        data[6] |= 0x01
        data = bytes(data)
    return data


# ---------------------------------------------------------------------------
# 1. MappingRequest schema
# ---------------------------------------------------------------------------

class TestMappingRequest:
    def test_valid_inventory_planning(self):
        req = MappingRequest(
            project_name="Test Project",
            boundary_source="BIA NLAR object 42",
            mapping_objective="inventory_planning",
            requested_cover_scheme="broad_candidate_cover_types_v1",
        )
        assert req.mapping_objective == "inventory_planning"

    def test_valid_forest_management_plan(self):
        req = MappingRequest(
            project_name="FMP Project",
            boundary_source="Census reference",
            mapping_objective="forest_management_plan_development",
            requested_cover_scheme="broad_candidate_cover_types_v1",
        )
        assert req.mapping_objective == "forest_management_plan_development"

    def test_missing_project_name_raises(self):
        with pytest.raises(ValidationError):
            MappingRequest(
                project_name="",
                boundary_source="BIA NLAR",
                mapping_objective="inventory_planning",
                requested_cover_scheme="broad_candidate_cover_types_v1",
            )

    def test_unknown_objective_raises(self):
        with pytest.raises(ValidationError):
            MappingRequest(
                project_name="X",
                boundary_source="Y",
                mapping_objective="timber_sale",  # not a valid Literal
                requested_cover_scheme="broad_candidate_cover_types_v1",
            )

    def test_unknown_cover_scheme_raises(self):
        with pytest.raises(ValidationError):
            MappingRequest(
                project_name="X",
                boundary_source="Y",
                mapping_objective="inventory_planning",
                requested_cover_scheme="mescalero_v1",  # not a valid Literal
            )

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            MappingRequest(
                project_name="X",
                boundary_source="Y",
                mapping_objective="inventory_planning",
                requested_cover_scheme="broad_candidate_cover_types_v1",
                extra_field="oops",
            )


# ---------------------------------------------------------------------------
# 2. inspect_mapping_request
# ---------------------------------------------------------------------------

class TestInspectMappingRequest:
    def test_valid_request_returns_accepted_status(self):
        req = MappingRequest(
            project_name="Mescalero Pilot",
            boundary_source="BIA NLAR 42",
            mapping_objective="inventory_planning",
            requested_cover_scheme="broad_candidate_cover_types_v1",
        )
        result = server.inspect_mapping_request(req)
        assert result["status"] == "request_accepted_for_input_inspection"
        assert result["project_name"] == "Mescalero Pilot"
        assert "review_flags" in result
        assert "next_steps" in result
        assert "limitations" in result


# ---------------------------------------------------------------------------
# 3. find_bia_land_area_candidates
# ---------------------------------------------------------------------------

class TestFindBiaLandAreaCandidates:
    def _mock_response(self, features: list) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.is_redirect = False
        resp.content = json.dumps({"features": features}).encode()
        resp.raise_for_status = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.iter_bytes = MagicMock(
            return_value=iter([json.dumps({"features": features}).encode()])
        )
        return resp

    def test_valid_name_returns_candidates(self, monkeypatch):
        features = [
            {"attributes": {"OBJECTID": 1, "LARID": "NM-001", "LARName": "Mescalero Apache", "GISAcres": 50000}}
        ]
        raw = json.dumps({"features": features}).encode()

        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([raw]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.find_bia_land_area_candidates("Mescalero")

        assert result["status"] == "candidates_found_review_required"
        assert result["candidate_count"] == 1
        assert result["candidates"][0]["lar_name"] == "Mescalero Apache"

    def test_not_found_returns_not_found(self, monkeypatch):
        raw = json.dumps({"features": []}).encode()

        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([raw]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.find_bia_land_area_candidates("ZzzzNotReal")

        assert result["status"] == "not_found"
        assert result["candidate_count"] == 0

    def test_bad_name_chars_raises_tool_error(self):
        with pytest.raises(ToolError):
            server.find_bia_land_area_candidates("Bad;Name!")

    def test_digits_only_raises_tool_error(self):
        with pytest.raises(ToolError):
            server.find_bia_land_area_candidates("12345")

    def test_source_error_field_returns_source_failed(self):
        raw = json.dumps({"error": {"code": 400, "message": "bad"}}).encode()

        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([raw]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.find_bia_land_area_candidates("Mescalero")

        assert result["status"] == "source_failed"

    def test_redirect_returns_source_failed(self):
        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 302
            resp.is_redirect = True
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([b""]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.find_bia_land_area_candidates("Mescalero")

        assert result["status"] == "source_failed"

    def test_non_json_response_returns_source_failed(self):
        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([b"<html>not json</html>"]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.find_bia_land_area_candidates("Mescalero")

        assert result["status"] == "source_failed"


# ---------------------------------------------------------------------------
# 4. download_bia_land_area
# ---------------------------------------------------------------------------

class TestDownloadBiaLandArea:
    def test_zero_object_id_raises_tool_error(self):
        with pytest.raises(ToolError):
            server.download_bia_land_area(0)

    def test_negative_object_id_raises_tool_error(self):
        with pytest.raises(ToolError):
            server.download_bia_land_area(-5)

    def test_successful_download_saves_files(self, tmp_path):
        data = _simple_polygon_geojson()
        data["features"][0]["properties"]["OBJECTID"] = 99
        raw = json.dumps(data).encode()

        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([raw]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client, \
             patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            (tmp_path / "outputs").mkdir()
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.download_bia_land_area(99)

        assert result["status"] == "downloaded_requires_geometry_review"
        assert Path(result["boundary_geojson"]).is_file()
        assert Path(result["source_manifest"]).is_file()

    def test_exceeded_transfer_limit_returns_review_required(self, tmp_path):
        raw = json.dumps({
            "type": "FeatureCollection",
            "features": [_simple_polygon_geojson()["features"][0]],
            "exceededTransferLimit": True,
        }).encode()

        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([raw]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client, \
             patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            (tmp_path / "outputs").mkdir()
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.download_bia_land_area(99)

        assert result["status"] == "review_required"
        assert not result["boundary_saved"]


# ---------------------------------------------------------------------------
# 5. find_census_reservation_reference
# ---------------------------------------------------------------------------

class TestFindCensusReservationReference:
    def _census_feature_collection(self) -> dict:
        feat = _simple_polygon_geojson()["features"][0].copy()
        feat["properties"] = {"BASENAME": "Mescalero Apache", "NAME": "Mescalero Apache Reservation"}
        return {"type": "FeatureCollection", "features": [feat]}

    def test_valid_name_returns_downloaded(self, tmp_path):
        data = self._census_feature_collection()
        raw = json.dumps(data).encode()

        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([raw]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client, \
             patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            (tmp_path / "outputs").mkdir()
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.find_census_reservation_reference("Mescalero Apache")

        assert result["status"] == "downloaded_requires_review"
        assert Path(result["boundary_geojson"]).is_file()
        assert Path(result["source_manifest"]).is_file()

    def test_source_in_manifest_is_census_layer(self, tmp_path):
        data = self._census_feature_collection()
        raw = json.dumps(data).encode()

        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([raw]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client, \
             patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            (tmp_path / "outputs").mkdir()
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.find_census_reservation_reference("Mescalero Apache")

        manifest = json.loads(
            Path(result["source_manifest"]).read_text(encoding="utf-8")
        )
        assert manifest["source_layer"] == CENSUS_BOUNDARY_LAYER

    def test_bad_name_raises_tool_error(self):
        with pytest.raises(ToolError):
            server.find_census_reservation_reference("Bad!Name")

    def test_digits_only_raises_tool_error(self):
        with pytest.raises(ToolError):
            server.find_census_reservation_reference("9999")

    def test_not_found_returns_not_found(self, tmp_path):
        raw = json.dumps({"type": "FeatureCollection", "features": []}).encode()

        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([raw]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.find_census_reservation_reference("ZzzzNotReal")

        assert result["status"] == "not_found"
        assert result["source"] == CENSUS_BOUNDARY_LAYER

    def test_ambiguous_returns_review_required(self, tmp_path):
        feats = [
            _simple_polygon_geojson()["features"][0],
            _simple_polygon_geojson()["features"][0],
        ]
        raw = json.dumps({"type": "FeatureCollection", "features": feats}).encode()

        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([raw]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.find_census_reservation_reference("Ambiguous")

        assert result["status"] == "review_required"

    def test_limitations_list_has_four_distinct_entries(self, tmp_path):
        """Regression: string-concatenation bug previously merged first two bullets."""
        data = self._census_feature_collection()
        raw = json.dumps(data).encode()

        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([raw]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client, \
             patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            (tmp_path / "outputs").mkdir()
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.find_census_reservation_reference("Mescalero Apache")

        assert len(result["review_flags"]) == 4
        # First bullet must begin with "Census comparison/fallback reference"
        assert result["review_flags"][0].startswith(
            "Census comparison/fallback reference"
        )
        # First bullet must NOT be a merged double-sentence starting with "Census comparison"
        # and immediately containing "Census reference geography" as a continuation
        assert "Census reference geography" not in result["review_flags"][0]

    def test_source_error_returns_source_failed(self):
        raw = json.dumps({"error": {"code": 400}}).encode()

        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([raw]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.find_census_reservation_reference("Mescalero")

        assert result["status"] == "source_failed"
        assert not result["boundary_saved"]

    def test_bad_geometry_type_returns_invalid(self, tmp_path):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-105.9, 33.1]},
                    "properties": {},
                }
            ],
        }
        raw = json.dumps(data).encode()

        def fake_stream(method, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.is_redirect = False
            resp.raise_for_status = MagicMock()
            resp.iter_bytes = MagicMock(return_value=iter([raw]))
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.stream = fake_stream
            result = server.find_census_reservation_reference("Mescalero")

        assert result["status"] == "invalid_geometry_response"


# ---------------------------------------------------------------------------
# 6. inspect_mapping_inputs — artifact-identifier guard
# ---------------------------------------------------------------------------

class TestInspectMappingInputs:
    def test_bad_filename_format_raises_tool_error(self, tmp_path):
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                server.inspect_mapping_inputs("../../etc/passwd")

    def test_full_path_raises_tool_error(self, tmp_path):
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                server.inspect_mapping_inputs(
                    str(tmp_path / "outputs" / "test_lar_20260101T000000000000Z.geojson")
                )

    def test_nonexistent_file_raises_tool_error(self, tmp_path):
        (tmp_path / "outputs").mkdir()
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                server.inspect_mapping_inputs("missing_20260101T000000000000Z.geojson")

    def test_valid_boundary_returns_passes_status(self, tmp_path):
        path = _write_boundary_geojson(tmp_path)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.inspect_mapping_inputs(path.name)
        assert result["status"] == "boundary_checks_passed_review_required"
        assert result["geometry_valid"] is True
        assert result["boundary_acres"] > 0

    def test_valid_boundary_produces_gpkg_and_qc(self, tmp_path):
        path = _write_boundary_geojson(tmp_path)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.inspect_mapping_inputs(path.name)
        assert Path(result["boundary_geopackage"]).is_file()
        assert Path(result["qc_report"]).is_file()

    def test_missing_crs_raises_tool_error(self, tmp_path):
        # Write a GeoJSON with no CRS — GeoPandas will read it as None CRS.
        folder = tmp_path / "outputs"
        folder.mkdir()
        geojson = _simple_polygon_geojson()
        path = folder / "no_crs_20260101T000000000000Z.geojson"
        path.write_text(json.dumps(geojson), encoding="utf-8")
        # Monkey-patch gpd.read_file to return a GeoDataFrame with crs=None
        gdf = gpd.read_file(path)
        gdf = gdf.set_crs(None, allow_override=True)
        with patch("server.OUTPUT_FOLDER", folder), \
             patch("server.gpd.read_file", return_value=gdf):
            with pytest.raises(ToolError, match="CRS is missing"):
                server.inspect_mapping_inputs(path.name)


# ---------------------------------------------------------------------------
# 7. inspect_naip_coverage — artifact-identifier guard
# ---------------------------------------------------------------------------

class TestInspectNaipCoverage:
    def test_bad_filename_raises_tool_error(self, tmp_path):
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                server.inspect_naip_coverage("../../bad")

    def test_nonexistent_boundary_raises_tool_error(self, tmp_path):
        (tmp_path / "outputs").mkdir()
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                server.inspect_naip_coverage("missing_20260101T000000000000Z.geojson")

    def test_source_failure_returns_source_failed(self, tmp_path):
        path = _write_boundary_geojson(tmp_path)

        def fake_get(url, **kwargs):
            raise server.httpx.ConnectError("SIMULATED_FAILURE: connection refused")

        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"), \
             patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.get = fake_get
            result = server.inspect_naip_coverage(path.name)

        assert result["status"] == "source_failed"
        assert not result["imagery_downloaded"]


# ---------------------------------------------------------------------------
# 8. prepare_landfire_v2_sample_request
# ---------------------------------------------------------------------------

class TestPrepareLandfireV2SampleRequest:
    def test_bad_filename_raises_tool_error(self, tmp_path):
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                server.prepare_landfire_v2_sample_request("../../bad.json")

    def test_nonexistent_manifest_raises_tool_error(self, tmp_path):
        (tmp_path / "outputs").mkdir()
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                server.prepare_landfire_v2_sample_request(
                    "missing_naip_sample_20260101T000000000000Z_source.json"
                )

    def test_valid_manifest_produces_request_record(self, tmp_path):
        bpath = _write_boundary_geojson(tmp_path)
        mpath = _write_naip_manifest(tmp_path, bpath)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.prepare_landfire_v2_sample_request(mpath.name)
        assert result["status"] == "request_prepared_requires_submission_approval"
        assert result["api_version"] == "LFPS v2"
        assert result["submission_method"] == "GET"
        assert result["contact_email_stored"] is False
        assert Path(result["prepared_request"]).is_file()

    def test_failed_grid_validation_returns_review_required(self, tmp_path):
        bpath = _write_boundary_geojson(tmp_path)
        mpath = _write_naip_manifest(tmp_path, bpath)
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        manifest["grid_validation_passed"] = False
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.prepare_landfire_v2_sample_request(mpath.name)
        assert result["status"] == "review_required"
        assert not result["job_submitted"]

    def test_aoi_too_large_returns_review_required(self, tmp_path):
        bpath = _write_boundary_geojson(tmp_path)
        mpath = _write_naip_manifest(tmp_path, bpath)
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        # Expand envelope to exceed 0.25-degree limit
        manifest["reference_envelope_lonlat"] = [-106.5, 33.0, -106.0, 33.5]
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.prepare_landfire_v2_sample_request(mpath.name)
        assert result["status"] == "review_required"

    def test_non_conus_aoi_returns_review_required(self, tmp_path):
        bpath = _write_boundary_geojson(tmp_path)
        mpath = _write_naip_manifest(tmp_path, bpath)
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        manifest["reference_envelope_lonlat"] = [-160.0, 60.0, -159.9, 60.1]
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.prepare_landfire_v2_sample_request(mpath.name)
        assert result["status"] == "review_required"

    def test_request_record_does_not_contain_email(self, tmp_path):
        bpath = _write_boundary_geojson(tmp_path)
        mpath = _write_naip_manifest(tmp_path, bpath)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.prepare_landfire_v2_sample_request(mpath.name)
        record_text = Path(result["prepared_request"]).read_text(encoding="utf-8")
        assert "contact_email_stored" in record_text
        # The raw word "email" should only appear as the metadata key, not a value
        record = json.loads(record_text)
        assert record["contact_email_stored"] is False
        assert "Email" not in record.get("submit_parameters_without_email", {})


# ---------------------------------------------------------------------------
# 9. recover_landfire_v2_job_manifest
# ---------------------------------------------------------------------------

class TestRecoverLandfireV2JobManifest:
    VALID_JOB_ID = "3b83d63b-cf47-47a1-8a21-09ee1659cedb"

    def test_bad_request_filename_raises_tool_error(self, tmp_path):
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                server.recover_landfire_v2_job_manifest("../../bad.json", self.VALID_JOB_ID)

    def test_bad_job_id_format_raises_tool_error(self, tmp_path):
        bpath = _write_boundary_geojson(tmp_path)
        mpath = _write_naip_manifest(tmp_path, bpath)
        rpath = _write_lfps_v2_request(tmp_path, mpath)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError, match="UUID"):
                server.recover_landfire_v2_job_manifest(rpath.name, "not-a-uuid")

    def test_valid_recovery_writes_manifest(self, tmp_path):
        bpath = _write_boundary_geojson(tmp_path)
        mpath = _write_naip_manifest(tmp_path, bpath)
        rpath = _write_lfps_v2_request(tmp_path, mpath)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.recover_landfire_v2_job_manifest(
                rpath.name, self.VALID_JOB_ID
            )
        assert result["status"] == "submitted_manifest_recovered_needs_status_check"
        assert result["job_id"] == self.VALID_JOB_ID
        assert Path(result["recovery_manifest"]).is_file()

    def test_recovery_manifest_has_no_email(self, tmp_path):
        bpath = _write_boundary_geojson(tmp_path)
        mpath = _write_naip_manifest(tmp_path, bpath)
        rpath = _write_lfps_v2_request(tmp_path, mpath)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.recover_landfire_v2_job_manifest(
                rpath.name, self.VALID_JOB_ID
            )
        record = json.loads(
            Path(result["recovery_manifest"]).read_text(encoding="utf-8")
        )
        assert record["contact_email_stored"] is False
        # No literal email address should appear in the manifest values
        manifest_text = Path(result["recovery_manifest"]).read_text(encoding="utf-8")
        assert not re.search(r"[^@\s]{1,64}@[^@\s]{1,253}\.[^@\s]{2,63}", manifest_text)


# ---------------------------------------------------------------------------
# 10. check_landfire_v2_sample_job
# ---------------------------------------------------------------------------

class TestCheckLandfireV2SampleJob:
    VALID_JOB_ID = "3b83d63b-cf47-47a1-8a21-09ee1659cedb"

    def _job_manifest_filename(self, job_id: str) -> str:
        return f"lfps_v2_job_recovered_20260101T030000000000Z_{job_id}.json"

    def _write_job_manifest(self, tmp_path: Path, job_id: str) -> Path:
        folder = tmp_path / "outputs"
        folder.mkdir(exist_ok=True)
        path = folder / self._job_manifest_filename(job_id)
        record = {
            "status": "submitted_manifest_recovered_needs_status_check",
            "api_version": "LFPS v2",
            "status_endpoint": LANDFIRE_LFPS_V2_STATUS_URL,
            "job_id": job_id,
            "job_submitted": True,
            "rasters_downloaded": False,
            "classification_performed": False,
        }
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return path

    def test_bad_filename_raises_tool_error(self, tmp_path):
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                server.check_landfire_v2_sample_job("../../bad.json")

    def test_wrong_api_version_in_manifest_returns_review_required(self, tmp_path):
        path = self._write_job_manifest(tmp_path, self.VALID_JOB_ID)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["api_version"] = "LFPS v1"
        path.write_text(json.dumps(record), encoding="utf-8")
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.check_landfire_v2_sample_job(path.name)
        assert result["status"] == "review_required"

    def test_mismatched_status_endpoint_returns_review_required(self, tmp_path):
        path = self._write_job_manifest(tmp_path, self.VALID_JOB_ID)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["status_endpoint"] = "https://evil.example.com/status"
        path.write_text(json.dumps(record), encoding="utf-8")
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.check_landfire_v2_sample_job(path.name)
        assert result["status"] == "review_required"

    def test_source_failure_returns_source_failed(self, tmp_path):
        path = self._write_job_manifest(tmp_path, self.VALID_JOB_ID)

        def fake_get(url, **kwargs):
            raise server.httpx.ConnectError("SIMULATED_FAILURE")

        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"), \
             patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.get = fake_get
            result = server.check_landfire_v2_sample_job(path.name)

        assert result["status"] == "source_failed"
        assert not result["rasters_downloaded"]

    def test_successful_status_response_returns_completed(self, tmp_path):
        path = self._write_job_manifest(tmp_path, self.VALID_JOB_ID)
        api_response = {
            "success": True,
            "jobId": self.VALID_JOB_ID,
            "status": "succeeded",
            "queuePosition": None,
            "messages": [],
            "outputFile": (
                f"https://{LANDFIRE_LFPS_V2_OUTPUT_HOST}"
                f"{LANDFIRE_LFPS_V2_OUTPUT_PATH_PREFIX}"
                f"{self.VALID_JOB_ID}_output/bundle.zip"
            ),
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_redirect = False
        mock_resp.raise_for_status = MagicMock()
        mock_resp.content = json.dumps(api_response).encode()
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = json.dumps(api_response)
        mock_resp.json = MagicMock(return_value=api_response)

        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"), \
             patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.get = MagicMock(return_value=mock_resp)
            result = server.check_landfire_v2_sample_job(path.name)

        assert result["status"] == "completed_requires_output_collection"
        assert result["job_id"] == self.VALID_JOB_ID


# ---------------------------------------------------------------------------
# 11. collect_landfire_v2_sample_result — ZIP safety (SIMULATED_FAILURE)
# ---------------------------------------------------------------------------

class TestCollectLandfireV2ZipSafety:
    VALID_JOB_ID = "3b83d63b-cf47-47a1-8a21-09ee1659cedb"
    APPROVAL = "download_and_validate_this_exact_lfps_v2_bundle"

    def _status_report_path(self, tmp_path: Path) -> Path:
        return _write_lfps_v2_job_manifest(tmp_path, job_id=self.VALID_JOB_ID)

    def _patch_download(self, zip_bytes: bytes):
        """Return a context-manager mock that streams zip_bytes."""
        resp = MagicMock()
        resp.status_code = 200
        resp.is_redirect = False
        resp.raise_for_status = MagicMock()
        resp.headers = {"content-length": str(len(zip_bytes))}
        # iter_bytes yields the full payload in one chunk
        resp.iter_bytes = MagicMock(return_value=iter([zip_bytes]))
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)

        mock_client = MagicMock()
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.stream = MagicMock(return_value=resp)
        return mock_client

    def test_bad_approval_phrase_raises_tool_error(self, tmp_path):
        status_path = self._status_report_path(tmp_path)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                server.collect_landfire_v2_sample_result(
                    status_path.name, "wrong_phrase"
                )

    def test_bad_filename_format_raises_tool_error(self, tmp_path):
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                server.collect_landfire_v2_sample_result(
                    "../../bad.json", self.APPROVAL
                )

    def test_non_completed_status_returns_review_required(self, tmp_path):
        status_path = _write_lfps_v2_job_manifest(
            tmp_path,
            job_id=self.VALID_JOB_ID,
            status="submitted_waiting_in_queue",
            source_status="queued",
        )
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.collect_landfire_v2_sample_result(
                status_path.name, self.APPROVAL
            )
        assert result["status"] == "review_required"

    def test_disallowed_output_url_returns_review_required(self, tmp_path):
        status_path = _write_lfps_v2_job_manifest(
            tmp_path,
            job_id=self.VALID_JOB_ID,
            output_file="https://evil.example.com/malicious/bundle.zip",
        )
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.collect_landfire_v2_sample_result(
                status_path.name, self.APPROVAL
            )
        assert result["status"] == "review_required"
        assert "allowlist" in result["message"].lower()

    def test_path_traversal_in_zip_raises_and_returns_error(self, tmp_path):
        """SIMULATED_FAILURE: ZIP member with path traversal is rejected."""
        safe_zip = _make_safe_zip()
        # Build a bad ZIP with a traversal path
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../escape.txt", b"bad")
            zf.writestr("output.tif", b"FAKE_TIF")
            for xml in ["LF2025_EVT_CONUS.xml", "LF2025_EVC_CONUS.xml", "LF2025_EVH_CONUS.xml"]:
                zf.writestr(xml, b"<xml/>")
        bad_zip = buf.getvalue()

        status_path = self._status_report_path(tmp_path)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"), \
             patch("server.httpx.Client", return_value=self._patch_download(bad_zip)):
            result = server.collect_landfire_v2_sample_result(
                status_path.name, self.APPROVAL
            )
        assert result["status"] == "bundle_validation_or_extraction_failed"
        assert "unsafe file path" in result["error"]

    def test_encrypted_zip_member_is_rejected(self, tmp_path):
        """SIMULATED_FAILURE: encrypted ZIP member is rejected.

        The server checks item.flag_bits & 0x1 from zipfile.ZipFile.infolist().
        We build a normal ZIP then patch infolist() so the first member reports
        flag_bits = 1, exercising the server's encryption guard without relying
        on internal ZIP binary format details.
        """
        safe_zip = _make_safe_zip()

        # Build a ZipInfo list where the first member has flag_bits == 1.
        with zipfile.ZipFile(io.BytesIO(safe_zip)) as real_zf:
            real_members = real_zf.infolist()

        encrypted_info = zipfile.ZipInfo(real_members[0].filename)
        encrypted_info.file_size = real_members[0].file_size
        encrypted_info.compress_size = real_members[0].compress_size
        encrypted_info.flag_bits = 1  # encryption bit set

        patched_members = [encrypted_info] + real_members[1:]

        status_path = self._status_report_path(tmp_path)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"), \
             patch("server.httpx.Client", return_value=self._patch_download(safe_zip)), \
             patch("server.zipfile.ZipFile") as mock_zip_cls:
            # Make ZipFile(...) return a context manager whose infolist()
            # returns our patched member list with encryption bit set.
            mock_zf = MagicMock()
            mock_zf.__enter__ = lambda s: s
            mock_zf.__exit__ = MagicMock(return_value=False)
            mock_zf.infolist = MagicMock(return_value=patched_members)
            mock_zip_cls.return_value = mock_zf

            result = server.collect_landfire_v2_sample_result(
                status_path.name, self.APPROVAL
            )
        assert result["status"] == "bundle_validation_or_extraction_failed"
        assert "encrypted" in result["error"]

    def test_too_many_zip_members_is_rejected(self, tmp_path):
        """SIMULATED_FAILURE: ZIP with >50 members is rejected."""
        bad_zip = _make_safe_zip(extra_members=50)  # 1 tif + 3 xml + 50 extra = 54

        status_path = self._status_report_path(tmp_path)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"), \
             patch("server.httpx.Client", return_value=self._patch_download(bad_zip)):
            result = server.collect_landfire_v2_sample_result(
                status_path.name, self.APPROVAL
            )
        assert result["status"] == "bundle_validation_or_extraction_failed"
        assert "50-file" in result["error"]

    def test_missing_xml_metadata_is_rejected(self, tmp_path):
        """SIMULATED_FAILURE: ZIP missing expected XML metadata is rejected."""
        bad_zip = _make_safe_zip(include_all_xml=False)

        status_path = self._status_report_path(tmp_path)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"), \
             patch("server.httpx.Client", return_value=self._patch_download(bad_zip)):
            result = server.collect_landfire_v2_sample_result(
                status_path.name, self.APPROVAL
            )
        assert result["status"] == "bundle_validation_or_extraction_failed"
        assert "missing" in result["error"].lower()

    def test_zero_tif_files_in_zip_is_rejected(self, tmp_path):
        """SIMULATED_FAILURE: ZIP with no GeoTIFF is rejected."""
        bad_zip = _make_safe_zip(include_tif=False)

        status_path = self._status_report_path(tmp_path)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"), \
             patch("server.httpx.Client", return_value=self._patch_download(bad_zip)):
            result = server.collect_landfire_v2_sample_result(
                status_path.name, self.APPROVAL
            )
        assert result["status"] == "bundle_validation_or_extraction_failed"
        assert "GeoTIFF" in result["error"]

    def test_existing_zip_prevents_overwrite(self, tmp_path):
        """Regression: an existing bundle must not be silently overwritten."""
        status_path = self._status_report_path(tmp_path)
        existing_zip = tmp_path / "outputs" / f"lfps_v2_bundle_{self.VALID_JOB_ID}.zip"
        existing_zip.write_bytes(b"existing")
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            result = server.collect_landfire_v2_sample_result(
                status_path.name, self.APPROVAL
            )
        assert result["status"] == "review_required"
        assert "already exists" in result["message"]


# ---------------------------------------------------------------------------
# 12. Email redaction — unit test of the inner redact_email helper
# ---------------------------------------------------------------------------

class TestEmailRedaction:
    """
    redact_email is a nested function inside submit_landfire_v2_sample_job.
    We test its behaviour indirectly by exercising the submit path with a
    SIMULATED_FAILURE that forces error messages containing the email to be
    returned, then confirming the raw email is absent from the result.
    """

    VALID_JOB_ID = "3b83d63b-cf47-47a1-8a21-09ee1659cedb"
    TEST_EMAIL = "testuser@example.gov"
    APPROVAL = "submit_this_exact_lfps_v2_request"

    def test_email_not_in_error_response_on_network_failure(self, tmp_path):
        """SIMULATED_FAILURE: network error during submit must not leak raw email."""
        bpath = _write_boundary_geojson(tmp_path)
        mpath = _write_naip_manifest(tmp_path, bpath)
        rpath = _write_lfps_v2_request(tmp_path, mpath)

        def fail_get(url, **kwargs):
            raise server.httpx.ConnectError(
                f"SIMULATED_FAILURE connecting with email={self.TEST_EMAIL}"
            )

        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"), \
             patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.get = fail_get
            result = server.submit_landfire_v2_sample_job(
                rpath.name, self.TEST_EMAIL, self.APPROVAL
            )

        result_text = json.dumps(result)
        assert self.TEST_EMAIL not in result_text
        assert result["status"] == "source_failed"

    def test_email_not_in_unexpected_response(self, tmp_path):
        """SIMULATED_FAILURE: non-JSON submit response must not leak raw email."""
        bpath = _write_boundary_geojson(tmp_path)
        mpath = _write_naip_manifest(tmp_path, bpath)
        rpath = _write_lfps_v2_request(tmp_path, mpath)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_redirect = False
        mock_resp.raise_for_status = MagicMock()
        mock_resp.content = b"<html>web app</html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = f"<html>email={self.TEST_EMAIL}</html>"

        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"), \
             patch("server.httpx.Client") as mock_client:
            instance = mock_client.return_value.__enter__.return_value
            instance.get = MagicMock(return_value=mock_resp)
            result = server.submit_landfire_v2_sample_job(
                rpath.name, self.TEST_EMAIL, self.APPROVAL
            )

        result_text = json.dumps(result)
        assert self.TEST_EMAIL not in result_text


# ===========================================================================
# Slice 2 — TestInspectLandfireV2Inputs
# Tests for _inspect_landfire_v2_inputs() helper and
# inspect_landfire_v2_cover_type_inputs() public tool.
#
# All committed tests use synthetic in-memory rasters and minimal XML
# fixtures. No Mescalero raster or outputs/ artifacts are required.
# One optional test (C-opt) is skipped when the local collection manifest
# is absent.
#
# Fixtures labelled SYNTHETIC do not represent real LANDFIRE outputs.
# ===========================================================================

import csv
import io
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from server import (
    _inspect_landfire_v2_inputs,
    _safe_cell_area,
    _parse_xml_product_info,
    _classify_value_against_domain,
    inspect_landfire_v2_cover_type_inputs,
    OUTPUT_FOLDER,
)
from mcp.server.mcpserver.exceptions import ToolError


# ---------------------------------------------------------------------------
# SYNTHETIC raster and XML builders
# ---------------------------------------------------------------------------

_SYNTH_JOB_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_SYNTH_EPSG = 5070
_SYNTH_TRANSFORM = from_origin(-885825.0, 1171005.0, 30.0, 30.0)  # 30 m cells

_SENTINEL_KEYS = (
    "classification_performed",
    "forest_land_determination_performed",
    "crosswalk_applied",
    "candidate_cover_types_produced",
    "candidate_polygons_produced",
)


def _make_synthetic_tif(
    tmp_path: Path,
    evt_data=None,
    evc_data=None,
    evh_data=None,
    band_descriptions=None,
    crs_epsg: int = _SYNTH_EPSG,
    nodata: int = -9999,
) -> Path:
    """SYNTHETIC: write a 4×4 three-band GeoTIFF with controlled values."""
    if evt_data is None:
        evt_data = np.array([
            [7101, 7102, 7101, nodata],
            [7101, 7102, 7102, 7101],
            [nodata, 7101, 7102, 7101],
            [7101, 7101, 7101, 7102],
        ], dtype=np.int16)
    if evc_data is None:
        evc_data = np.array([
            [111, 121, 111, nodata],
            [111, 121, 121, 111],
            [nodata, 111, 121, 111],
            [111, 111, 111, 121],
        ], dtype=np.int16)
    if evh_data is None:
        evh_data = np.array([
            [105, 107, 105, nodata],
            [105, 107, 107, 105],
            [nodata, 105, 107, 105],
            [105, 105, 105, 107],
        ], dtype=np.int16)
    if band_descriptions is None:
        band_descriptions = (
            "LF2025_EVT_CONUS",
            "LF2025_EVC_CONUS",
            "LF2025_EVH_CONUS",
        )

    tif_path = tmp_path / "synth.tif"
    crs = CRS.from_epsg(crs_epsg)
    with rasterio.open(
        str(tif_path),
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=3,
        dtype=np.int16,
        crs=crs,
        transform=_SYNTH_TRANSFORM,
        nodata=nodata,
    ) as dst:
        dst.write(evt_data, 1)
        dst.write(evc_data, 2)
        dst.write(evh_data, 3)
        dst.update_tags(1, name=band_descriptions[0])
        dst.update_tags(2, name=band_descriptions[1])
        dst.update_tags(3, name=band_descriptions[2])

    # rasterio stores band descriptions via descriptions property only when
    # set via dataset.descriptions; patch via update_tags workaround is not
    # reliable.  Instead, re-open and set descriptions explicitly.
    import subprocess, sys
    # Use a memory-file round-trip to set band descriptions cleanly.
    with rasterio.open(str(tif_path), "r+") as dst:
        dst.descriptions = band_descriptions

    return tif_path


def _make_minimal_evt_xml(tmp_path: Path, rdom_min: float = 4401.0, rdom_max: float = 9994.0) -> Path:
    """SYNTHETIC: minimal EVT XML with citation and rdom VALUE domain."""
    content = f"""<?xml version='1.0' encoding='UTF-8'?>
<metadata>
  <idinfo>
    <citation>
      <citeinfo>
        <title>SYNTHETIC EVT LF 2025</title>
        <edition>LF 2025</edition>
        <pubdate>20260430</pubdate>
        <onlink>https://doi.org/10.5066/SYNTHETIC</onlink>
      </citeinfo>
    </citation>
  </idinfo>
  <eainfo>
    <detailed>
      <attr>
        <attrlabl>VALUE</attrlabl>
        <attrdef>Code that identifies vegetation type.</attrdef>
        <attrdomv>
          <edom>
            <edomv>-9999</edomv>
            <edomvd>Fill-NoData</edomvd>
          </edom>
        </attrdomv>
        <attrdomv>
          <rdom>
            <rdommin>{rdom_min}</rdommin>
            <rdommax>{rdom_max}</rdommax>
          </rdom>
        </attrdomv>
      </attr>
      <attr>
        <attrlabl>CLASSNAMES</attrlabl>
        <attrdef>Vegetation type name.</attrdef>
        <attrdomv>
          <udom>See the LF ADD CSV for per-code names.</udom>
        </attrdomv>
      </attr>
    </detailed>
  </eainfo>
</metadata>"""
    p = tmp_path / "LF2025_EVT_CONUS.xml"
    p.write_text(content, encoding="utf-8")
    return p


def _make_minimal_evc_xml(tmp_path: Path) -> Path:
    """SYNTHETIC: minimal EVC XML with rdom and udom CLASSNAMES."""
    content = """<?xml version='1.0' encoding='UTF-8'?>
<metadata>
  <idinfo>
    <citation>
      <citeinfo>
        <title>SYNTHETIC EVC LF 2025</title>
        <edition>LF 2025</edition>
        <pubdate>20260430</pubdate>
        <onlink>https://doi.org/10.5066/SYNTHETIC</onlink>
      </citeinfo>
    </citation>
  </idinfo>
  <eainfo>
    <detailed>
      <attr>
        <attrlabl>VALUE</attrlabl>
        <attrdef>The code that identifies the percent canopy cover.</attrdef>
        <attrdomv>
          <edom>
            <edomv>-9999</edomv>
            <edomvd>Fill-NoData</edomvd>
          </edom>
        </attrdomv>
        <attrdomv>
          <rdom>
            <rdommin>11</rdommin>
            <rdommax>399</rdommax>
          </rdom>
        </attrdomv>
      </attr>
      <attr>
        <attrlabl>CLASSNAMES</attrlabl>
        <attrdef>EVC class name.</attrdef>
        <attrdomv>
          <udom>Tree cover 10 to 100%. Shrub cover 10 to 100%. Herb cover 10 to 100%.</udom>
        </attrdomv>
      </attr>
    </detailed>
  </eainfo>
</metadata>"""
    p = tmp_path / "LF2025_EVC_CONUS.xml"
    p.write_text(content, encoding="utf-8")
    return p


def _make_minimal_evh_xml(tmp_path: Path) -> Path:
    """SYNTHETIC: minimal EVH XML with rdom and udom CLASSNAMES."""
    content = """<?xml version='1.0' encoding='UTF-8'?>
<metadata>
  <idinfo>
    <citation>
      <citeinfo>
        <title>SYNTHETIC EVH LF 2025</title>
        <edition>LF 2025</edition>
        <pubdate>20260430</pubdate>
        <onlink>https://doi.org/10.5066/SYNTHETIC</onlink>
      </citeinfo>
    </citation>
  </idinfo>
  <eainfo>
    <detailed>
      <attr>
        <attrlabl>VALUE</attrlabl>
        <attrdef>Value representing height class.</attrdef>
        <attrdomv>
          <edom>
            <edomv>-9999</edomv>
            <edomvd>Fill-NoData</edomvd>
          </edom>
        </attrdomv>
        <attrdomv>
          <rdom>
            <rdommin>11</rdommin>
            <rdommax>310</rdommax>
          </rdom>
        </attrdomv>
      </attr>
      <attr>
        <attrlabl>CLASSNAMES</attrlabl>
        <attrdef>EVH class name.</attrdef>
        <attrdomv>
          <udom>101 to 199 - Tree heights 1 meter to 99 meters or greater.
201 to 230 - Shrub heights - 1 meter to 3 meters or greater.
301 to 310 - Herb heights - 0.1 meter to 1 meter or greater.</udom>
        </attrdomv>
      </attr>
    </detailed>
  </eainfo>
</metadata>"""
    p = tmp_path / "LF2025_EVH_CONUS.xml"
    p.write_text(content, encoding="utf-8")
    return p


def _make_synthetic_manifest(
    tmp_path: Path,
    tif_path: Path,
    evt_xml: Path,
    evc_xml: Path,
    evh_xml: Path,
    job_id: str = _SYNTH_JOB_ID,
) -> dict:
    """SYNTHETIC: minimal LFPS v2 collection manifest dict."""
    return {
        "status": "bundle_collected_requires_gis_review",
        "api_version": "LFPS v2",
        "job_id": job_id,
        "geotiff_file": str(tif_path),
        "expected_metadata_xml_files": {
            "LF2025_EVT_CONUS.xml": str(evt_xml),
            "LF2025_EVC_CONUS.xml": str(evc_xml),
            "LF2025_EVH_CONUS.xml": str(evh_xml),
        },
    }


def _write_manifest_file(tmp_path: Path, manifest: dict) -> Path:
    """Write a collection manifest as lfps_v2_collection_<ts>_<uuid>.json."""
    folder = tmp_path / "outputs"
    folder.mkdir(exist_ok=True)
    filename = f"lfps_v2_collection_20260101T000000000000Z_{manifest['job_id']}.json"
    p = folder / filename
    p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Helper: build the full synthetic fixture set
# ---------------------------------------------------------------------------

def _make_full_fixture(tmp_path: Path, **kwargs) -> tuple:
    """Return (manifest_dict, manifest_path, tif_path) for a full fixture set."""
    tif_path = _make_synthetic_tif(tmp_path, **kwargs)
    evt_xml = _make_minimal_evt_xml(tmp_path)
    evc_xml = _make_minimal_evc_xml(tmp_path)
    evh_xml = _make_minimal_evh_xml(tmp_path)
    manifest = _make_synthetic_manifest(tmp_path, tif_path, evt_xml, evc_xml, evh_xml)
    manifest_path = _write_manifest_file(tmp_path, manifest)
    return manifest, manifest_path, tif_path


# ---------------------------------------------------------------------------
# Optional Mescalero fixture check
# ---------------------------------------------------------------------------

_MESCALERO_MANIFEST_GLOB = (
    Path(__file__).parent.parent
    / "outputs"
)

def _find_mescalero_manifest():
    """Return the first local LFPS v2 collection manifest found, or None."""
    for p in _MESCALERO_MANIFEST_GLOB.glob("lfps_v2_collection_*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("api_version") == "LFPS v2" and data.get("geotiff_file"):
                return p
        except Exception:
            pass
    return None

_LOCAL_MANIFEST = _find_mescalero_manifest()
_LOCAL_MANIFEST_PRESENT = _LOCAL_MANIFEST is not None


# ===========================================================================
# Test class
# ===========================================================================

class TestInspectLandfireV2Inputs:
    """Slice 2 — inspect_landfire_v2_cover_type_inputs tests."""

    # --- C-1: Valid synthetic raster ----------------------------------------

    def test_c1_valid_case_all_sentinels_false(self, tmp_path):
        """C-1: All sentinel fields present and False for a valid synthetic input."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        for key in _SENTINEL_KEYS:
            assert result[key] is False, f"Sentinel {key!r} must be False"
        assert result["inspection_status"] in ("success", "partial")

    def test_c1_inspection_status_present(self, tmp_path):
        """C-1: inspection_status must be one of success/partial/failed."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        assert result["inspection_status"] in ("success", "partial", "failed")

    def test_c1_evt_codes_observed_populated(self, tmp_path):
        """C-1: evt_codes_observed contains the known synthetic codes."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        codes = [r["evt_code"] for r in result["evt_band"]["evt_codes_observed"]]
        assert 7101 in codes
        assert 7102 in codes

    def test_c1_acreage_math_correct(self, tmp_path):
        """C-1: cell acreage = cell_count * cell_area_acres."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        rg = result["raster_geometry"]
        cell_acres = rg["cell_area_acres"]
        assert cell_acres is not None
        for row in result["evt_band"]["evt_codes_observed"]:
            expected = round(row["cell_count"] * cell_acres, 4)
            assert abs(row["acres"] - expected) < 0.0001

    def test_c1_nodata_excluded_from_valid_count(self, tmp_path):
        """C-1: NoData cells are not counted in evt_valid_cell_count."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        evt = result["evt_band"]
        assert evt["nodata_cell_count"] > 0
        assert evt["valid_cell_count"] + evt["nodata_cell_count"] == evt["total_cells"]

    def test_c1_band_identification_all_found(self, tmp_path):
        """C-1: Band identification status is all_identified."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        bi = result["band_identification"]
        assert bi["band_identification_status"] == "all_identified"
        for bk in ("EVT", "EVC", "EVH"):
            assert bi[bk]["band_index_found"] is not None

    def test_c1_evc_evh_value_counts_present(self, tmp_path):
        """C-1: EVC and EVH value counts are populated for valid cells."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        assert len(result["evc_band"]["evc_value_counts"]) > 0
        assert len(result["evh_band"]["evh_value_counts"]) > 0

    def test_c1_no_mean_median_std_for_evc(self, tmp_path):
        """C-1: Mean/median/std are not reported for EVC encoded classes."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        evc = result["evc_band"]
        # These keys must not exist; if they do, fail.
        for key in ("mean", "median", "std", "evc_mean", "evc_median", "evc_std"):
            assert key not in evc, f"EVC must not report {key!r}"

    def test_c1_no_mean_median_std_for_evh(self, tmp_path):
        """C-1: Mean/median/std are not reported for EVH encoded classes."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        evh = result["evh_band"]
        for key in ("mean", "median", "std", "evh_mean", "evh_median", "evh_std"):
            assert key not in evh, f"EVH must not report {key!r}"

    def test_c1_statistics_note_present_evc(self, tmp_path):
        """C-1: EVC statistics_note present and non-empty."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        note = result["evc_band"].get("statistics_note", "")
        assert note, "EVC statistics_note must be present and non-empty"
        assert "encoded" in note.lower() or "percent" in note.lower()

    def test_c1_statistics_note_present_evh(self, tmp_path):
        """C-1: EVH statistics_note present and references encoded classes."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        note = result["evh_band"].get("statistics_note", "")
        assert note, "EVH statistics_note must be present and non-empty"
        assert "encoded" in note.lower() or "metre" in note.lower()

    # --- C-2: Missing EVT XML -----------------------------------------------

    def test_c2_missing_evt_xml_partial_not_crash(self, tmp_path):
        """C-2: Missing EVT XML produces partial/failed status, not a crash."""
        tif_path = _make_synthetic_tif(tmp_path)
        evc_xml = _make_minimal_evc_xml(tmp_path)
        evh_xml = _make_minimal_evh_xml(tmp_path)
        # Deliberately omit evt_xml path
        manifest = _make_synthetic_manifest(
            tmp_path, tif_path,
            tmp_path / "NONEXISTENT_EVT.xml",  # will not exist
            evc_xml, evh_xml
        )
        manifest_path = _write_manifest_file(tmp_path, manifest)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        assert result["inspection_status"] in ("partial", "failed", "success")
        for key in _SENTINEL_KEYS:
            assert result[key] is False
        # Warning about missing XML must be present
        warnings_text = " ".join(result.get("warnings", []))
        assert "EVT" in warnings_text and (
            "missing" in warnings_text.lower() or "not found" in warnings_text.lower()
        )

    # --- C-3: EVT code outside XML domain -----------------------------------

    def test_c3_evt_code_outside_domain_warned(self, tmp_path):
        """C-3: EVT code outside XML rdom produces outside_numeric_range entry and warning."""
        # Use an EVT code of 100 — well outside the 4401–9994 synthetic range
        evt_data = np.full((4, 4), 100, dtype=np.int16)
        evt_data[0, 0] = -9999
        manifest, manifest_path, _ = _make_full_fixture(tmp_path, evt_data=evt_data)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        codes = result["evt_band"]["evt_codes_observed"]
        out_of_domain = [r for r in codes if r["domain_membership"] == "outside_numeric_range"]
        assert len(out_of_domain) > 0, "EVT code 100 must be flagged outside_numeric_range"
        assert 100 in result["evt_band"]["evt_codes_outside_xml_domain"]
        # Domain boundary must come from XML, not hard-coded 99999
        warnings_text = " ".join(result.get("warnings", []))
        assert "4401" in warnings_text or "9994" in warnings_text, (
            "Warning must reference the XML-declared domain bounds, not a hard-coded value"
        )

    # --- C-4: Invalid filename ----------------------------------------------

    def test_c4_invalid_filename_raises_tool_error(self, tmp_path):
        """C-4: Invalid filename raises ToolError before any file access."""
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                inspect_landfire_v2_cover_type_inputs("not_a_valid_filename.json")

    def test_c4_path_traversal_raises_tool_error(self, tmp_path):
        """C-4: Path traversal attempt raises ToolError."""
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            with pytest.raises(ToolError):
                inspect_landfire_v2_cover_type_inputs(
                    "../lfps_v2_collection_20260101T000000000000Z_"
                    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.json"
                )

    # --- C-5: NoData-only EVT band ------------------------------------------

    def test_c5_nodata_only_evt_band(self, tmp_path):
        """C-5: All-NoData EVT band yields valid_cell_count=0 and empty code list."""
        all_nodata = np.full((4, 4), -9999, dtype=np.int16)
        manifest, manifest_path, _ = _make_full_fixture(tmp_path, evt_data=all_nodata)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        evt = result["evt_band"]
        assert evt["valid_cell_count"] == 0
        assert evt["evt_codes_observed"] == []
        assert evt["nodata_cell_count"] == 16
        for key in _SENTINEL_KEYS:
            assert result[key] is False

    # --- C-6: Ambiguous band descriptions -----------------------------------

    def test_c6_ambiguous_band_descriptions_fails(self, tmp_path):
        """C-6: Two bands matching EVT causes inspection_status=failed."""
        tif_path = _make_synthetic_tif(
            tmp_path,
            band_descriptions=(
                "LF2025_EVT_CONUS",
                "LF2025_EVT_DUPLICATE",   # second band also matches EVT
                "LF2025_EVH_CONUS",
            ),
        )
        evt_xml = _make_minimal_evt_xml(tmp_path)
        evc_xml = _make_minimal_evc_xml(tmp_path)
        evh_xml = _make_minimal_evh_xml(tmp_path)
        manifest = _make_synthetic_manifest(tmp_path, tif_path, evt_xml, evc_xml, evh_xml)
        manifest_path = _write_manifest_file(tmp_path, manifest)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        assert result["inspection_status"] == "failed"
        for key in _SENTINEL_KEYS:
            assert result[key] is False
        # Verify no partial data leaked
        assert "evt_band" not in result

    # --- C-7: Missing required band description ----------------------------

    def test_c7_missing_evh_band_description_fails(self, tmp_path):
        """C-7: EVH band absent from all descriptions causes inspection_status=failed."""
        tif_path = _make_synthetic_tif(
            tmp_path,
            band_descriptions=(
                "LF2025_EVT_CONUS",
                "LF2025_EVC_CONUS",
                "UNKNOWN_BAND",           # EVH not present
            ),
        )
        evt_xml = _make_minimal_evt_xml(tmp_path)
        evc_xml = _make_minimal_evc_xml(tmp_path)
        evh_xml = _make_minimal_evh_xml(tmp_path)
        manifest = _make_synthetic_manifest(tmp_path, tif_path, evt_xml, evc_xml, evh_xml)
        manifest_path = _write_manifest_file(tmp_path, manifest)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        assert result["inspection_status"] == "failed"
        for key in _SENTINEL_KEYS:
            assert result[key] is False

    # --- C-8: EVC encoding note and no-percent-cover claim -----------------

    def test_c8_evc_statistics_note_no_percent_cover_label(self, tmp_path):
        """C-8: EVC band carries statistics_note; no field claims percent cover."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        evc = result["evc_band"]
        note = evc.get("statistics_note", "")
        assert note
        # Must not label the band as direct percent values
        assert "percent canopy" in note.lower() or "not percent" in note.lower() or "encoded" in note.lower()
        # No field labeled mean/median/std
        for bad_key in ("mean", "median", "std"):
            assert bad_key not in evc

    # --- C-9: EVH encoding note and no-metres claim ------------------------

    def test_c9_evh_statistics_note_no_metres_label(self, tmp_path):
        """C-9: EVH band carries statistics_note; no field claims values are metres."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        evh = result["evh_band"]
        note = evh.get("statistics_note", "")
        assert note
        # Must not label the band as direct height values in metres
        assert "not" in note.lower() or "encoded" in note.lower()
        for bad_key in ("mean", "median", "std"):
            assert bad_key not in evh

    # --- C-10: Non-metre CRS -----------------------------------------------

    def test_c10_non_metre_crs_area_null(self, tmp_path):
        """C-10: EPSG:4326 raster produces cell_area_m2=None and a warning."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path, crs_epsg=4326)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        rg = result["raster_geometry"]
        assert rg["cell_area_m2"] is None
        assert rg["cell_area_acres"] is None
        warnings_text = " ".join(result.get("warnings", []))
        assert "cell area" in warnings_text.lower() or "crs" in warnings_text.lower()

    # --- C-11: Affine-based cell area (not hard-coded 900) -----------------

    def test_c11_cell_area_from_affine_not_hardcoded(self, tmp_path):
        """C-11: cell_area_m2 equals |det(affine)|, not a hard-coded 900."""
        # Use a non-standard 45 m cell to distinguish from 30 m
        custom_transform = from_origin(-885825.0, 1171005.0, 45.0, 45.0)

        # Rebuild tif with 45 m transform
        tif_path = tmp_path / "synth45m.tif"
        crs = CRS.from_epsg(5070)
        arr = np.full((4, 4), 7101, dtype=np.int16)
        with rasterio.open(
            str(tif_path), "w", driver="GTiff",
            height=4, width=4, count=3, dtype=np.int16,
            crs=crs, transform=custom_transform, nodata=-9999,
        ) as dst:
            dst.write(arr, 1)
            dst.write(arr, 2)
            dst.write(arr, 3)
        with rasterio.open(str(tif_path), "r+") as dst:
            dst.descriptions = (
                "LF2025_EVT_CONUS",
                "LF2025_EVC_CONUS",
                "LF2025_EVH_CONUS",
            )

        (tmp_path / "xml45").mkdir(exist_ok=True)
        evt_xml = _make_minimal_evt_xml(tmp_path / "xml45")
        evc_xml = _make_minimal_evc_xml(tmp_path / "xml45")
        evh_xml = _make_minimal_evh_xml(tmp_path / "xml45")
        manifest = _make_synthetic_manifest(
            tmp_path, tif_path, evt_xml, evc_xml, evh_xml,
            job_id="cccccccc-dddd-eeee-ffff-000000000001",
        )
        manifest_path = _write_manifest_file(tmp_path, manifest)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        rg = result["raster_geometry"]
        expected_area = abs(custom_transform.a * custom_transform.e - custom_transform.b * custom_transform.d)
        assert rg["cell_area_m2"] is not None
        assert abs(rg["cell_area_m2"] - expected_area) < 0.001
        assert rg["cell_area_m2"] != 900.0, "Must not be hard-coded 900"

    # --- C-12: Unknown EVC value outside XML domain ------------------------

    def test_c12_unknown_evc_outside_xml_domain(self, tmp_path):
        """C-12: EVC value outside XML rdom produces outside_numeric_range entry."""
        # EVC domain is 11–399; use value 500 which is outside
        evc_data = np.full((4, 4), 500, dtype=np.int16)
        evc_data[0, 0] = -9999
        manifest, manifest_path, _ = _make_full_fixture(tmp_path, evc_data=evc_data)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        evc = result["evc_band"]
        assert 500 in evc["evc_codes_outside_xml_domain"]
        # Membership must be reported
        outside_rows = [r for r in evc["evc_value_counts"] if r["domain_membership"] == "outside_numeric_range"]
        assert len(outside_rows) > 0
        # Warning must reference the XML-declared range (11–399), not hard-coded percent
        warnings_text = " ".join(result.get("warnings", []))
        assert "11" in warnings_text or "399" in warnings_text

    # --- C-13: Unknown EVH value outside XML domain ------------------------

    def test_c13_unknown_evh_outside_xml_domain(self, tmp_path):
        """C-13: EVH value outside XML rdom produces outside_numeric_range entry."""
        # EVH domain is 11–310; use value 400
        evh_data = np.full((4, 4), 400, dtype=np.int16)
        evh_data[0, 0] = -9999
        manifest, manifest_path, _ = _make_full_fixture(tmp_path, evh_data=evh_data)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        evh = result["evh_band"]
        assert 400 in evh["evh_codes_outside_xml_domain"]
        outside_rows = [r for r in evh["evh_value_counts"] if r["domain_membership"] == "outside_numeric_range"]
        assert len(outside_rows) > 0
        warnings_text = " ".join(result.get("warnings", []))
        assert "310" in warnings_text or "11" in warnings_text

    # --- C-14: All three artifacts written ---------------------------------

    def test_c14_three_artifacts_written(self, tmp_path):
        """C-14: MD, JSON, and CSV files are written with correct names."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        with patch("server.OUTPUT_FOLDER", tmp_path / "outputs"):
            # Write manifest to the patched folder
            folder = tmp_path / "outputs"
            folder.mkdir(exist_ok=True)
            filename = f"lfps_v2_collection_20260101T000000000000Z_{_SYNTH_JOB_ID}.json"
            manifest_file = folder / filename
            manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            result = inspect_landfire_v2_cover_type_inputs(filename)

        assert result["inspection_status"] in ("success", "partial")
        assert result["csv_artifact_created"] is True

        md_path = Path(result["inspection_report_md"])
        json_path = Path(result["inspection_report_json"])
        csv_path = Path(result["evt_inventory_csv"])

        assert md_path.exists(), "Markdown report must exist"
        assert json_path.exists(), "JSON summary must exist"
        assert csv_path.exists(), "EVT inventory CSV must exist"

        # Check CSV has required columns (Slice 2b: label_from_xml removed,
        # new label columns evt_name/evt_name_source/evt_lf/evt_phys/evt_gp_n/saf_srm added)
        with csv_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required_cols = {
                "evt_code", "evt_name", "evt_name_source", "label_missing",
                "evt_lf", "evt_phys", "evt_gp_n", "saf_srm",
                "cell_count", "square_meters", "acres",
                "valid_cell_fraction", "domain_membership",
                "source_tif", "source_xml",
            }
            assert required_cols.issubset(set(reader.fieldnames or []))

    # --- C-15: EVT label availability note always present ------------------

    def test_c15_evt_label_note_always_present(self, tmp_path):
        """C-15: evt_label_availability_note present in evt_band and in warnings."""
        manifest, manifest_path, _ = _make_full_fixture(tmp_path)
        result = _inspect_landfire_v2_inputs(manifest, manifest_path)
        note = result["evt_band"].get("evt_label_availability_note", "")
        assert note, "evt_label_availability_note must be present and non-empty"
        assert "ADD CSV" in note or "external" in note.lower()
        # Must also appear in warnings
        warnings_text = " ".join(result.get("warnings", []))
        assert "ADD CSV" in warnings_text or "external" in warnings_text.lower()

    # --- C-16: No overwrite on repeat call ---------------------------------

    def test_c16_no_overwrite_raises_tool_error(self, tmp_path):
        """C-16: Second call on same manifest raises ToolError."""
        manifest, _, _ = _make_full_fixture(tmp_path)
        folder = tmp_path / "outputs"
        folder.mkdir(exist_ok=True)
        filename = f"lfps_v2_collection_20260101T000000000000Z_{_SYNTH_JOB_ID}.json"
        manifest_file = folder / filename
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        with patch("server.OUTPUT_FOLDER", folder):
            inspect_landfire_v2_cover_type_inputs(filename)
            with pytest.raises(ToolError, match="already exists"):
                inspect_landfire_v2_cover_type_inputs(filename)

    # --- Failure artifacts written on hard failure -------------------------

    def test_failure_artifacts_written_on_bad_geotiff(self, tmp_path):
        """Hard failure writes MD and JSON artifacts with all sentinels False."""
        evt_xml = _make_minimal_evt_xml(tmp_path)
        evc_xml = _make_minimal_evc_xml(tmp_path)
        evh_xml = _make_minimal_evh_xml(tmp_path)
        manifest = _make_synthetic_manifest(
            tmp_path,
            tmp_path / "NONEXISTENT.tif",  # GeoTIFF does not exist
            evt_xml, evc_xml, evh_xml,
            job_id="ffffffff-0000-1111-2222-333333333333",
        )
        folder = tmp_path / "outputs"
        folder.mkdir(exist_ok=True)
        filename = (
            "lfps_v2_collection_20260101T000000000000Z_"
            "ffffffff-0000-1111-2222-333333333333.json"
        )
        manifest_file = folder / filename
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        with patch("server.OUTPUT_FOLDER", folder):
            result = inspect_landfire_v2_cover_type_inputs(filename)

        assert result["inspection_status"] == "failed"
        assert result["csv_artifact_created"] is False
        for key in _SENTINEL_KEYS:
            assert result[key] is False

        md_path = Path(result["inspection_report_md"])
        json_path = Path(result["inspection_report_json"])
        assert md_path.exists(), "Failure Markdown artifact must be written"
        assert json_path.exists(), "Failure JSON artifact must be written"

    # --- Unit tests for helpers -------------------------------------------

    def test_safe_cell_area_epsg5070_correct(self):
        """_safe_cell_area uses |det| for EPSG:5070."""
        from rasterio.transform import from_origin
        from rasterio.crs import CRS
        t = from_origin(0, 0, 30.0, 30.0)
        crs = CRS.from_epsg(5070)
        m2, acres, limit = _safe_cell_area(t, crs)
        expected = abs(t.a * t.e - t.b * t.d)
        assert m2 is not None
        assert abs(m2 - expected) < 0.001
        assert limit is None

    def test_safe_cell_area_non_metre_crs_returns_null(self):
        """_safe_cell_area returns None for EPSG:4326."""
        from rasterio.transform import from_origin
        from rasterio.crs import CRS
        t = from_origin(0, 0, 0.001, 0.001)
        crs = CRS.from_epsg(4326)
        m2, acres, limit = _safe_cell_area(t, crs)
        assert m2 is None
        assert acres is None
        assert limit is not None

    def test_classify_value_within_range(self):
        """_classify_value_against_domain: within range returns within_numeric_range_only."""
        result = _classify_value_against_domain(7101, -9999, "range", 4401, 9994)
        assert result == "within_numeric_range_only"

    def test_classify_value_outside_range(self):
        """_classify_value_against_domain: outside range returns outside_numeric_range."""
        result = _classify_value_against_domain(100, -9999, "range", 4401, 9994)
        assert result == "outside_numeric_range"

    def test_classify_value_nodata(self):
        """_classify_value_against_domain: nodata value returns nodata."""
        result = _classify_value_against_domain(-9999, -9999, "range", 4401, 9994)
        assert result == "nodata"

    def test_classify_value_no_domain_info(self):
        """_classify_value_against_domain: unknown domain type returns metadata_domain_unavailable."""
        result = _classify_value_against_domain(999, -9999, "unknown", None, None)
        assert result == "metadata_domain_unavailable"

    def test_parse_xml_product_info_rdom(self, tmp_path):
        """_parse_xml_product_info: extracts rdom min/max from synthetic EVT XML."""
        xml_path = _make_minimal_evt_xml(tmp_path, rdom_min=4401.0, rdom_max=9994.0)
        info = _parse_xml_product_info(xml_path)
        assert info["parse_status"] == "parsed"
        assert info["value_domain_type"] == "range"
        assert info["value_domain_min"] == 4401.0
        assert info["value_domain_max"] == 9994.0
        assert info["title"] == "SYNTHETIC EVT LF 2025"
        assert "doi.org" in (info["doi"] or "")

    def test_parse_xml_product_info_missing_file(self, tmp_path):
        """_parse_xml_product_info: missing file returns parse_status=failed."""
        info = _parse_xml_product_info(tmp_path / "NONEXISTENT.xml")
        assert info["parse_status"] == "failed"
        assert info["title"] is None

    # --- C-opt: Actual Mescalero manifest (skip if absent) -----------------

    @pytest.mark.skipif(not _LOCAL_MANIFEST_PRESENT, reason="Local Mescalero manifest not found")
    def test_copt_mescalero_manifest_runs_without_error(self, tmp_path):
        """C-opt: Actual Mescalero collection manifest inspection (local only)."""
        # Read the manifest but run inspection against local paths
        # without patching OUTPUT_FOLDER, since artifacts should go to real outputs/
        manifest_data = json.loads(_LOCAL_MANIFEST.read_text(encoding="utf-8"))
        result = _inspect_landfire_v2_inputs(manifest_data, _LOCAL_MANIFEST)

        assert result["inspection_status"] != "failed", (
            f"Inspection failed with warnings: {result.get('warnings')}"
        )
        for key in _SENTINEL_KEYS:
            assert result[key] is False

        evt_codes = result.get("evt_band", {}).get("evt_codes_observed", [])
        assert len(evt_codes) > 0, "At least one EVT code must be observed"

        # Verify no classification leaked
        assert result["classification_performed"] is False
