"""Synthetic boundary/preparation tests; no LFPS jobs, raster acquisition, or field accuracy."""
from pathlib import Path
import json
import socket
import sys

import geopandas as gpd
import pytest
from pydantic import ValidationError
from shapely.geometry import box, Polygon, Point, MultiPolygon

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "boundary_mapping_preflight.py").is_file():
    ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import boundary_mapping_preflight as prep


def frame(geometries=None, crs="EPSG:4326"):
    return gpd.GeoDataFrame({"geometry": geometries or [box(-105.9, 33.0, -105.8, 33.1)]}, crs=crs)


def write_boundary(root, name="example_boundary.geojson", geometries=None):
    data = frame(geometries)
    path = root / name
    data.to_file(path, driver="GeoJSON", engine="pyogrio", index=False)
    return path


def test_valid_generic_boundary():
    result = prep.inspect_boundary_frame(frame())
    assert result["geometry_valid"] and result["boundary_acres"] > 0
    assert result["download_aoi_wgs84"] == [-105.9, 33.0, -105.8, 33.1]
    assert result["estimated_download_pixels"] == result["estimated_grid_rows"] * result["estimated_grid_columns"]
    assert result["array_estimates"]["source_three_band_int32_scenario_bytes"] == result["estimated_download_pixels"] * 12


def test_another_project_has_its_own_extent():
    first = prep.inspect_boundary_frame(frame())
    second = prep.inspect_boundary_frame(frame([box(-84.9, 45.0, -84.8, 45.1)]))
    assert first["download_aoi_wgs84"] != second["download_aoi_wgs84"]
    assert second["download_aoi_wgs84"] == [-84.9, 45.0, -84.8, 45.1]


def test_missing_crs_rejected():
    data = gpd.GeoDataFrame({"geometry": [box(0, 0, 1, 1)]})
    with pytest.raises(prep.BoundaryPreparationError, match="CRS"):
        prep.inspect_boundary_frame(data)


def test_invalid_polygon_rejected():
    bow = Polygon([(-105.9,33),(-105.8,33.1),(-105.9,33.1),(-105.8,33),(-105.9,33)])
    with pytest.raises(prep.BoundaryPreparationError, match="invalid"):
        prep.inspect_boundary_frame(frame([bow]))


def test_point_geometry_rejected():
    with pytest.raises(prep.BoundaryPreparationError, match="Polygon"):
        prep.inspect_boundary_frame(frame([Point(-105.8,33)]))


def test_empty_geometry_rejected():
    with pytest.raises(prep.BoundaryPreparationError, match="empty"):
        prep.inspect_boundary_frame(frame([Polygon()]))


def test_null_geometry_rejected():
    with pytest.raises(prep.BoundaryPreparationError, match="null"):
        prep.inspect_boundary_frame(gpd.GeoDataFrame({"geometry":[None]},crs=4326))


@pytest.mark.parametrize("bounds", [(-150,60,-149,61),(-157,20,-156,21),(-67,18,-66,19)])
def test_unsupported_region_rejected(bounds):
    with pytest.raises(prep.BoundaryPreparationError, match="lower-48"):
        prep.inspect_boundary_frame(frame([box(*bounds)]))


def test_overlapping_features_rejected():
    with pytest.raises(prep.BoundaryPreparationError, match="overlap"):
        prep.inspect_boundary_frame(frame([box(-105.9,33,-105.8,33.1),box(-105.85,33.05,-105.75,33.15)]))


def test_nonoverlapping_features_supported():
    result = prep.inspect_boundary_frame(frame([box(-105.9,33,-105.85,33.05),box(-105.8,33.1,-105.75,33.15)]))
    assert result["feature_count"] == 2 and result["boundary_overlap_m2"] <= result["area_tolerance_m2"]


def test_multipart_supported():
    result = prep.inspect_boundary_frame(frame([MultiPolygon([box(-105.9,33,-105.85,33.05),box(-105.8,33.1,-105.75,33.15)])]))
    assert result["feature_count"] == 1 and result["boundary_acres"] > 0


def test_hole_excluded_from_boundary_area():
    shell = box(-105.9,33,-105.8,33.1)
    hole = box(-105.88,33.02,-105.82,33.08)
    with_hole = Polygon(shell.exterior.coords,[hole.exterior.coords])
    assert prep.inspect_boundary_frame(frame([with_hole]))["boundary_acres"] < prep.inspect_boundary_frame(frame([shell]))["boundary_acres"]


def test_projected_and_geographic_input_equivalent():
    data = frame()
    one = prep.inspect_boundary_frame(data)
    two = prep.inspect_boundary_frame(data.to_crs(5070))
    assert two["boundary_acres"] == pytest.approx(one["boundary_acres"],rel=1e-9)


def test_large_aoi_is_prepared_but_warns_about_existing_limits():
    result = prep.inspect_boundary_frame(frame([box(-105.94,32.99,-105.31,33.4)]))
    limits = result["existing_limit_checks"]
    assert limits["exceeds_sample_aoi_limit"]
    assert limits["exceeds_raw_patch_pixel_limit"]
    assert limits["full_area_patch_count_known"] is False
    assert limits["compressed_bundle_size_known"] is False


def test_coordinate_limit_enforced(monkeypatch):
    monkeypatch.setattr(prep,"MAX_BOUNDARY_COORDINATES",1)
    with pytest.raises(prep.BoundaryPreparationError,match="coordinate"):
        prep.inspect_boundary_frame(frame())


def test_preparation_writes_without_network_and_preserves_input(tmp_path,monkeypatch):
    source = write_boundary(tmp_path)
    before = prep._digest(source)
    def forbidden(*args,**kwargs):
        raise AssertionError("Network access is forbidden in preparation tests")
    monkeypatch.setattr(socket,"create_connection",forbidden)
    monkeypatch.setattr(socket.socket,"connect",forbidden)
    req = prep.BoundaryPreparationRequest(boundary_filename=source.name,project_name="Synthetic public project")
    result = prep.prepare_boundary_mapping_request(tmp_path,req)
    assert result.status == "prepared_review_required",result.errors
    assert result.request_prepared and not result.execution_ready and not result.job_submitted
    assert not result.rasters_downloaded and not result.classification_performed
    assert prep._digest(source) == before
    proposal = json.loads(Path(result.artifacts["prepared_request_json"]).read_text())
    assert proposal["existing_sample_submission_compatible"] is False
    assert proposal["remote_contract_verified_this_run"] is False
    assert proposal["contact_email_stored"] is False
    assert "Email" not in proposal["proposed_parameters_without_email"]
    assert proposal["proposed_parameters_without_email"]["Layer_List"] == "LF2025_EVT;LF2025_EVC;LF2025_EVH"
    assert proposal["analysis_boundary"]["sha256"] == before


def test_repeated_preparation_never_overwrites(tmp_path):
    source = write_boundary(tmp_path)
    req = prep.BoundaryPreparationRequest(boundary_filename=source.name)
    one = prep.prepare_boundary_mapping_request(tmp_path,req)
    two = prep.prepare_boundary_mapping_request(tmp_path,req)
    assert one.status == two.status == "prepared_review_required"
    assert one.artifacts["prepared_request_json"] != two.artifacts["prepared_request_json"]
    assert Path(one.artifacts["prepared_request_json"]).is_file()


@pytest.mark.parametrize("name",["../b.geojson","a/b.geojson","C:\\b.geojson","https://x/b.geojson"])
def test_paths_urls_rejected(name):
    with pytest.raises(ValidationError):
        prep.BoundaryPreparationRequest(boundary_filename=name)


def test_missing_file_structured_failure(tmp_path):
    result = prep.prepare_boundary_mapping_request(tmp_path,prep.BoundaryPreparationRequest(boundary_filename="missing.geojson"))
    assert result.status == "failed" and not result.artifacts
    assert not list(tmp_path.glob("boundaryprep_*"))


def test_bad_json_structured_failure(tmp_path):
    (tmp_path/"bad.geojson").write_text("not JSON")
    result = prep.prepare_boundary_mapping_request(tmp_path,prep.BoundaryPreparationRequest(boundary_filename="bad.geojson"))
    assert result.status == "failed" and not list(tmp_path.glob("boundaryprep_*"))


def test_non_geojson_object_rejected(tmp_path):
    (tmp_path/"bad.geojson").write_text('{"url":"https://example.invalid"}')
    result = prep.prepare_boundary_mapping_request(tmp_path,prep.BoundaryPreparationRequest(boundary_filename="bad.geojson"))
    assert result.status == "failed" and "FeatureCollection" in result.errors[0]


def test_unknown_profile_and_email_rejected():
    with pytest.raises(ValidationError):
        prep.BoundaryPreparationRequest(boundary_filename="b.geojson",product_profile="alaska")
    with pytest.raises(ValidationError):
        prep.BoundaryPreparationRequest(boundary_filename="b.geojson",contact_email="person@example.invalid")


def test_boundary_size_limit_enforced(tmp_path,monkeypatch):
    source = write_boundary(tmp_path)
    monkeypatch.setattr(prep,"MAX_BOUNDARY_BYTES",1)
    result = prep.prepare_boundary_mapping_request(tmp_path,prep.BoundaryPreparationRequest(boundary_filename=source.name))
    assert result.status == "failed" and "5 MB" in result.errors[0]


def test_write_failure_marked(tmp_path,monkeypatch):
    source = write_boundary(tmp_path)
    original = Path.write_text
    def fail_notes(self,*args,**kwargs):
        if self.name == "REVIEW_BEFORE_SUBMISSION.txt":
            raise OSError("SIMULATED write failure")
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,"write_text",fail_notes)
    result = prep.prepare_boundary_mapping_request(tmp_path,prep.BoundaryPreparationRequest(boundary_filename=source.name))
    assert result.status == "failed"
    marker = json.loads(Path(result.artifacts["failure_report"]).read_text())
    assert marker["accept_outputs"] is False


def test_escaping_symlink_rejected(tmp_path):
    root = tmp_path/"outputs"
    root.mkdir()
    outside = write_boundary(tmp_path)
    try:
        (root/"linked.geojson").symlink_to(outside)
    except (OSError,NotImplementedError):
        pytest.skip("Symlink creation unavailable")
    result = prep.prepare_boundary_mapping_request(root,prep.BoundaryPreparationRequest(boundary_filename="linked.geojson"))
    assert result.status == "failed"
