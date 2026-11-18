"""Focused synthetic-artifact connection tests. No network or forest policy."""
import hashlib
import json

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

import source_configuration_workflow as workflow


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def run(tmp_path, monkeypatch):
    root = tmp_path / "outputs"
    root.mkdir()
    pdr = tmp_path / "project_data"
    ref = pdr / "reference_data" / "landfire" / "lf2025_pinned_5ccc130b"
    ref.mkdir(parents=True)
    data = b"VALUE,EVT_NAME,EVT_LF\n10,Synthetic tree,Tree\n"
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(workflow, "REFERENCE_SHA256", digest)
    (ref / "LF2025_EVT.csv").write_bytes(data)
    (ref / "LF2025_EVT.source.json").write_text(json.dumps({
        "source_url": workflow.REFERENCE_URL, "sha256": digest,
    }))
    boundary = root / "boundary.geojson"
    gpd.GeoDataFrame(geometry=[box(0, 0, 60, 60)], crs=5070).to_file(
        boundary, driver="GeoJSON", engine="pyogrio"
    )
    acquisition = root / "bacq_synthetic"
    extract = acquisition / "extract"
    extract.mkdir(parents=True)
    tif = extract / "synthetic.tif"
    with rasterio.open(tif, "w", driver="GTiff", width=2, height=2,
                       count=3, dtype="int16", crs="EPSG:5070",
                       transform=from_origin(0, 60, 30, 30), nodata=-9999) as dst:
        dst.write(np.array([[10, 40], [-9999, 10]], dtype="int16"), 1)
        dst.write(np.ones((2, 2), dtype="int16"), 2)
        dst.write(np.ones((2, 2), dtype="int16"), 3)
        dst.descriptions = tuple(workflow.bm.EXPECTED_BANDS)
    collection = {
        "document_type": "mapcp_boundary_collection_v1",
        "usable_for_mapping": True, "classification_performed": False,
        "boundary_filename": boundary.name, "boundary_sha256": sha(boundary),
        "extract": {"geotiff_member": tif.name, "geotiff_sha256": sha(tif)},
    }
    (acquisition / "collection.json").write_text(json.dumps(collection))
    return root, pdr, tif, ref


def call(run, **kwargs):
    return workflow.review_source_configuration(
        run[0], run[1], workflow.SourceReviewRequest(
            acquisition_directory="bacq_synthetic", **kwargs
        )
    )


def test_real_artifact_connection_is_draft_only_and_preserves_unknown(run):
    before = {str(p.relative_to(run[0].parent)) for p in run[0].parent.rglob("*")}
    result = call(run)
    assert result["status"] == "draft_review_complete_requires_human_review", result
    assert result["approval_authenticated"] is False
    assert result["files_written"] is False
    assert result["classification_performed"] is False
    rows = result["review"]["source_rows"]
    assert [r["source_evt_code"] for r in rows] == [10, 40]
    assert all(r["proposed_forest_land"] is None for r in rows)
    assert rows[1]["official_name"] is None
    coverage = result["review"]["coverage"]
    assert coverage["valid_source_cells"]["cell_count"] == 3
    assert coverage["valid_source_cells"]["square_meters"] == 2700
    assert coverage["evt_nodata_inside_boundary"]["cell_count"] == 1
    assert before == {str(p.relative_to(run[0].parent)) for p in run[0].parent.rglob("*")}


def test_changed_raster_rejected(run):
    with rasterio.open(run[2], "r+") as dst:
        dst.update_tags(changed="yes")
    assert call(run)["status"] == "failed"


def test_incompatible_grid_rejected_even_with_current_hash(run):
    with rasterio.open(run[2], "r+") as dst:
        dst.transform = from_origin(0, 60, 15, 15)
    path = run[0] / "bacq_synthetic" / "collection.json"
    doc = json.loads(path.read_text())
    doc["extract"]["geotiff_sha256"] = sha(run[2])
    path.write_text(json.dumps(doc))
    assert call(run)["status"] == "failed"


def test_mismatched_proposal_rejected(run):
    first = call(run)
    proposal = {key: first["proposal"][key] for key in (
        "source_configuration_sha256", "classes", "decisions"
    )}
    proposal["source_configuration_sha256"] = "0" * 64
    assert call(run, proposal=proposal)["status"] == "failed"


def test_changed_reference_rejected(run):
    (run[3] / "LF2025_EVT.csv").write_bytes(b"changed")
    assert call(run)["status"] == "failed"
