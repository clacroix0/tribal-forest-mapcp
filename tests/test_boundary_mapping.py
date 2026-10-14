"""Tests for boundary_mapping. Array logic and orchestration run without a raster library (the two
rasterio-dependent functions are replaced by fakes in those tests). Tests marked REAL need rasterio and are
skipped where it is unavailable. No network access and no real LANDFIRE data."""
import csv
import json
import math
import sys
from collections import deque
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from pydantic import ValidationError
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "boundary_mapping.py").is_file():
    ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import boundary_mapping as bm

JOB = "63182cc4-dbd5-4874-9ac5-05236aa40d31"
ACQ = "bacq_20261013T170840_63182cc4"
CW_NAME = "test_crosswalk_v2.json"


def crosswalk(**changes):
    cw = {"crosswalk_id": "test_cw_v2", "crosswalk_version": "v2", "cover_scheme_id": "mescalero_v1", "cover_scheme_version": "v1",
          "approved_by": "user", "crosswalk_approval_note": "SYNTHETIC approval note", "nodata_value": -9999, "unmapped_valid_output_code": 255,
          "evt_add_url": "https://example.invalid/evt.csv", "evt_add_sha256": "0" * 64, "universal_review_flags": ["disturbance_not_evaluated"],
          "output_code_table": [
              {"output_code": 1, "output_label": "candidate_P", "candidate_forest_land": True, "description": "P"},
              {"output_code": 2, "output_label": "candidate_PJ", "candidate_forest_land": True, "description": "PJ"},
              {"output_code": 5, "output_label": "candidate_G", "candidate_forest_land": False, "description": "G"},
              {"output_code": 8, "output_label": "candidate_UNCERTAIN_PINE_OAK", "candidate_forest_land": None, "description": "Q"},
              {"output_code": 255, "output_label": "unmapped_evt", "candidate_forest_land": None, "description": "U"},
              {"output_code": -9999, "output_label": "nodata", "candidate_forest_land": None, "description": "N"}],
          "entries": [
              {"evt_code": 7054, "output_code": 1, "output_label": "candidate_P", "candidate_forest_land": True},
              {"evt_code": 7025, "output_code": 2, "output_label": "candidate_PJ", "candidate_forest_land": True},
              {"evt_code": 7146, "output_code": 5, "output_label": "candidate_G", "candidate_forest_land": False},
              {"evt_code": 7024, "output_code": 8, "output_label": "candidate_UNCERTAIN_PINE_OAK", "candidate_forest_land": None}]}
    cw.update(changes)
    return cw


def put_crosswalk(project_data, cw, name=CW_NAME):
    folder = project_data / "crosswalks"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(cw), encoding="utf-8")


def bfs(values, valid):
    h, w = values.shape
    seen = np.zeros((h, w), bool)
    result = []
    for r in range(h):
        for c in range(w):
            if valid[r, c] and not seen[r, c]:
                v, n, queue = values[r, c], 0, deque([(r, c)])
                seen[r, c] = True
                while queue:
                    y, x = queue.popleft()
                    n += 1
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < h and 0 <= xx < w and valid[yy, xx] and not seen[yy, xx] and values[yy, xx] == v:
                            seen[yy, xx] = True
                            queue.append((yy, xx))
                result.append((int(v), n))
    return sorted(result)


def comps(values, valid):
    v, s = bm.component_sizes(np.asarray(values), np.asarray(valid))
    return sorted(zip(map(int, v), map(int, s)))


# ---- connected components ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(40))
def test_components_match_flood_fill(seed):
    rng = np.random.default_rng(seed)
    h, w = int(rng.integers(1, 30)), int(rng.integers(1, 30))
    values = rng.integers(0, int(rng.integers(1, 6)), size=(h, w))
    valid = rng.random((h, w)) > float(rng.choice([0.0, 0.1, 0.4]))
    assert comps(values, valid) == bfs(values, valid)


def test_diagonal_cells_are_separate():
    assert comps([[1, 2], [2, 1]], np.ones((2, 2), bool)) == [(1, 1), (1, 1), (2, 1), (2, 1)]


def test_invalid_gap_separates_same_value():
    assert comps([[1, 1, 1]], [[True, False, True]]) == [(1, 1), (1, 1)]


def test_uniform_and_empty_and_single():
    assert comps(np.full((4, 5), 3), np.ones((4, 5), bool)) == [(3, 20)]
    assert comps(np.full((3, 3), 3), np.zeros((3, 3), bool)) == []
    assert comps([[7]], [[True]]) == [(7, 1)]


def test_checkerboard_count():
    board = (np.indices((6, 6)).sum(axis=0) % 2).astype(int)
    assert len(comps(board, np.ones((6, 6), bool))) == 36


def test_u_shape_joins_across_rows():
    grid = np.array([[1, 0, 1], [1, 0, 1], [1, 1, 1]])
    assert comps(grid, np.ones((3, 3), bool)) == [(0, 2), (1, 7)]


# ---- crosswalk loading ----------------------------------------------------------------------------------
def test_valid_crosswalk_loads_with_hash(tmp_path):
    put_crosswalk(tmp_path, crosswalk())
    data, digest = bm.load_crosswalk(tmp_path, CW_NAME)
    assert data["crosswalk_version"] == "v2" and len(digest) == 64


def bad(**changes):
    return crosswalk(**changes)


def drop(key):
    cw = crosswalk(); cw.pop(key); return cw


@pytest.mark.parametrize("cw,message", [
    (drop("crosswalk_approval_note"), "missing required"),
    (drop("entries"), "missing required"),
    (bad(approved_by="someone"), "approval"),
    (bad(approved_by=None), "approval"),
    (bad(nodata_value=-1), "NoData"),
    (bad(unmapped_valid_output_code=77), "NoData"),
    (bad(entries=[]), "non-empty"),
    (bad(crosswalk_version=""), "non-empty"),
])
def test_bad_crosswalks_rejected(tmp_path, cw, message):
    put_crosswalk(tmp_path, cw)
    with pytest.raises(bm.MappingError, match=message):
        bm.load_crosswalk(tmp_path, CW_NAME)


def test_duplicate_and_inconsistent_entries_rejected(tmp_path):
    cw = crosswalk()
    cw["entries"].append(dict(cw["entries"][0]))
    put_crosswalk(tmp_path, cw)
    with pytest.raises(bm.MappingError, match="unique"):
        bm.load_crosswalk(tmp_path, CW_NAME)
    cw = crosswalk(); cw["entries"][0]["output_code"] = 99
    put_crosswalk(tmp_path, cw)
    with pytest.raises(bm.MappingError, match="disagrees"):
        bm.load_crosswalk(tmp_path, CW_NAME)
    cw = crosswalk(); cw["entries"][0]["output_label"] = "candidate_WRONG"
    put_crosswalk(tmp_path, cw)
    with pytest.raises(bm.MappingError, match="disagrees"):
        bm.load_crosswalk(tmp_path, CW_NAME)
    cw = crosswalk(); cw["entries"][0]["candidate_forest_land"] = False
    put_crosswalk(tmp_path, cw)
    with pytest.raises(bm.MappingError, match="disagrees"):
        bm.load_crosswalk(tmp_path, CW_NAME)


def test_duplicate_output_codes_or_labels_rejected(tmp_path):
    cw = crosswalk(); cw["output_code_table"].append(dict(cw["output_code_table"][0]))
    put_crosswalk(tmp_path, cw)
    with pytest.raises(bm.MappingError, match="unique"):
        bm.load_crosswalk(tmp_path, CW_NAME)


def test_crosswalk_path_rules(tmp_path):
    with pytest.raises(bm.MappingError):
        bm.load_crosswalk(tmp_path, "missing.json")
    with pytest.raises(bm.MappingError):
        bm.load_crosswalk(tmp_path, "../x.json")
    with pytest.raises(ValidationError):
        bm.MappingRequest(acquisition_directory=ACQ, crosswalk_filename="../x.json")


# ---- classification and clipping ----------------------------------------------------------------------
def grid():
    evt = np.array([[7054, 7054, 7025, 7025, 7146],
                    [7054, 9999, 7025, -9999, 7146],
                    [7054, 7054, 7024, 7024, 7146]], dtype=np.int32)
    inside = np.ones(evt.shape, bool)
    inside[:, 0] = False
    return evt, inside


def test_classification_codes_and_outside_mask():
    evt, inside = grid()
    r = bm.classify_and_clip(evt, inside, crosswalk())
    assert (r["out"][:, 0] == -9999).all() and (r["fl"][:, 0] == -9999).all()
    assert r["out"][0, 1] == 1 and r["out"][0, 2] == 2 and r["out"][0, 4] == 5 and r["out"][2, 2] == 8
    assert r["out"][1, 1] == 255 and r["unmapped_evt"] == [(9999, 1)]
    assert r["out"][1, 3] == -9999 and r["evt_nodata_inside_cells"] == 1
    assert (r["outside_cells"], r["inside_cells"], r["valid_cells"], r["total_cells"]) == (3, 12, 11, 15)
    assert r["valid_cells"] + r["outside_cells"] + r["evt_nodata_inside_cells"] == r["total_cells"]


def test_forest_land_codes_distinguish_unknown_from_nonforest():
    evt, inside = grid()
    r = bm.classify_and_clip(evt, inside, crosswalk())
    assert r["fl"][0, 1] == bm.FL_TRUE and r["fl"][0, 4] == bm.FL_FALSE
    assert r["fl"][2, 2] == bm.FL_UNKNOWN and r["fl"][1, 1] == bm.FL_UNKNOWN


def test_outside_cells_with_valid_evt_are_not_counted():
    evt, inside = grid()
    r = bm.classify_and_clip(evt, inside, crosswalk())
    assert r["valid"][:, 0].sum() == 0


def test_shape_mismatch_rejected():
    with pytest.raises(bm.MappingError):
        bm.classify_and_clip(np.zeros((2, 2), np.int32), np.ones((3, 3), bool), crosswalk())


def test_empty_valid_area_is_handled():
    r = bm.classify_and_clip(np.full((2, 2), -9999, np.int32), np.ones((2, 2), bool), crosswalk())
    assert r["valid_cells"] == 0 and bm.class_stats(r["out"], r["valid"], crosswalk(), 900.0) == []


def test_class_stats_totals_and_exclusions():
    evt, inside = grid()
    cw = crosswalk()
    r = bm.classify_and_clip(evt, inside, cw)
    rows = bm.class_stats(r["out"], r["valid"], cw, 900.0)
    assert sum(x["cell_count"] for x in rows) == r["valid_cells"]
    assert all(x["output_code"] != -9999 for x in rows)
    assert {x["output_label"] for x in rows} == {"candidate_P", "candidate_PJ", "candidate_G", "candidate_UNCERTAIN_PINE_OAK", "unmapped_evt"}
    assert math.isclose(sum(x["acres"] for x in rows), r["valid_cells"] * 900 / bm.ACRE_M2, abs_tol=0.0005)


def test_stray_output_code_rejected():
    out = np.array([[1, 42]], np.int32)
    with pytest.raises(bm.MappingError, match="outside the output table"):
        bm.class_stats(out, np.ones((1, 2), bool), crosswalk(), 900.0)


def test_forest_stats_sum_to_valid():
    evt, inside = grid()
    r = bm.classify_and_clip(evt, inside, crosswalk())
    rows = bm.forest_stats(r["fl"], r["valid"], 900.0)
    assert sum(x["cell_count"] for x in rows) == r["valid_cells"]


# ---- patch summary ---------------------------------------------------------------------------------------
def test_patch_summary_counts_and_threshold():
    evt, inside = grid()
    cw = crosswalk()
    r = bm.classify_and_clip(evt, inside, cw)
    summary = bm.patch_summary(r["out"], r["valid"], cw, 900.0, 10_000.0)
    expected = bfs(r["out"], r["valid"])
    assert summary["total_patches"] == len(expected)
    assert summary["by_class"]["candidate_P"]["cells"] == sum(n for v, n in expected if v == 1)
    assert summary["below_threshold_total"] == len(expected)
    assert summary["single_cell_patches"] == sum(1 for _, n in expected if n == 1)
    tight = bm.patch_summary(r["out"], r["valid"], cw, 900.0, 1000.0)
    assert tight["below_threshold_total"] == sum(1 for _, n in expected if n * 900 < 1000.0)


def test_below_threshold_p_pj_counts_only_those_classes():
    out = np.array([[1, 5, 2, 8]], np.int32)
    summary = bm.patch_summary(out, np.ones((1, 4), bool), crosswalk(), 900.0, 10_000.0)
    assert summary["below_threshold_p_pj"] == 2 and summary["below_threshold_total"] == 4


def test_patch_summary_empty():
    summary = bm.patch_summary(np.full((2, 2), -9999, np.int32), np.zeros((2, 2), bool), crosswalk(), 900.0, 10_000.0)
    assert summary["total_patches"] == 0 and summary["largest_patch_cells"] == 0


def test_threshold_must_be_positive_and_finite():
    for bad_value in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            bm.MappingRequest(acquisition_directory=ACRE if False else ACQ, small_patch_threshold_m2=bad_value)


# ---- orchestration with fakes ----------------------------------------------------------------------------------
INFO = {"shape": [3, 5], "transform": [30.0, 0.0, -920655.0, 0.0, -30.0, 1194825.0], "epsg": 5070, "cell_area_m2": 900.0}


@pytest.fixture
def project(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    pdata = tmp_path / "project_data"
    outputs.mkdir()
    put_crosswalk(pdata, crosswalk())
    boundary = outputs / "ref_boundary.geojson"
    gpd.GeoDataFrame({"geometry": [box(-105.9, 33.0, -105.8, 33.1)]}, crs="EPSG:4326").to_file(boundary, driver="GeoJSON", engine="pyogrio")
    acq = outputs / ACQ
    (acq / "extract" / "data").mkdir(parents=True)
    tif = acq / "extract" / "data" / "layers.tif"
    tif.write_bytes(b"SYNTHETIC TIFF PLACEHOLDER")
    collection = {"document_type": "mapcp_boundary_collection_v1", "usable_for_mapping": True, "classification_performed": False,
                  "job_id": JOB, "boundary_filename": boundary.name, "boundary_sha256": bm._digest(boundary),
                  "extract": {"folder": "extract", "geotiff_member": "data/layers.tif", "geotiff_sha256": bm._digest(tif)}}
    (acq / "collection.json").write_text(json.dumps(collection), encoding="utf-8")
    monkeypatch.setattr(bm, "_read_inputs", lambda tif_path, boundary_path: (grid()[0], grid()[1], dict(INFO)))
    monkeypatch.setattr(bm, "_current_raw_limits", lambda: {"max_pixels": 10, "max_patches": 3, "source": "test"})
    def fake_write(paths, out, fl, info, tags):
        for key in ("cover_type_tif", "forest_land_tif"):
            Path(paths[key]).write_bytes(out.astype("int16").tobytes() if key == "cover_type_tif" else fl.astype("int16").tobytes())
    monkeypatch.setattr(bm, "_write_and_verify_rasters", fake_write)
    return outputs, pdata, acq, tif, boundary


def preview(project, **kw):
    outputs, pdata, *_ = project
    return bm.preview_boundary_mapping(outputs, bm.MappingRequest(acquisition_directory=ACQ, crosswalk_filename=CW_NAME, **kw), pdata)


def create(project, preview_result, **kw):
    outputs, pdata, *_ = project
    request = bm.CreateMappingRequest(acquisition_directory=kw.get("acq", ACQ), preview_directory=preview_result.artifacts["preview_directory"],
                                      crosswalk_filename=CW_NAME)
    return bm.create_boundary_mapping(outputs, request, pdata)


def test_preview_writes_only_a_small_report(project):
    result = preview(project)
    assert result.status == "preview_complete_review_required", result.errors
    outputs = project[0]
    folder = outputs / result.artifacts["preview_directory"]
    assert [p.name for p in folder.iterdir()] == ["mapping_preview.json"]
    assert not list(outputs.glob("cmap_*"))
    report = json.loads((folder / "mapping_preview.json").read_text())
    assert report["rasters_written"] is False and report["inputs"]["crosswalk_sha256"]
    s = result.summary
    assert s["patches"]["total_patches"] == len(bfs(*(lambda r: (r["out"], r["valid"]))(bm.classify_and_clip(*grid(), crosswalk()))))
    assert s["limit_assessment"] == {"raster_cells_exceed_raw_patch_pixel_limit": True, "patches_exceed_raw_patch_limit": True}
    assert s["unmapped_evt_codes"] == [{"evt_code": 9999, "cells": 1, "acres": round(900 / bm.ACRE_M2, 2)}]
    assert s["outside_boundary_cells"] == 3 and s["evt_nodata_inside_boundary_cells"] == 1


def test_repeated_previews_do_not_overwrite(project):
    one, two = preview(project), preview(project)
    assert one.artifacts["preview_directory"] != two.artifacts["preview_directory"]


@pytest.mark.parametrize("breaker", ["tif", "boundary", "collection_unusable", "no_collection", "crosswalk_unapproved", "crosswalk_missing"])
def test_preview_blocks_bad_inputs(project, breaker):
    outputs, pdata, acq, tif, boundary = project
    if breaker == "tif":
        tif.write_bytes(b"changed")
    elif breaker == "boundary":
        boundary.write_text(boundary.read_text() + " ")
    elif breaker == "collection_unusable":
        doc = json.loads((acq / "collection.json").read_text()); doc["usable_for_mapping"] = False
        (acq / "collection.json").write_text(json.dumps(doc))
    elif breaker == "no_collection":
        (acq / "collection.json").unlink()
    elif breaker == "crosswalk_unapproved":
        put_crosswalk(pdata, crosswalk(approved_by="nobody"))
    else:
        (pdata / "crosswalks" / CW_NAME).unlink()
    result = preview(project)
    assert result.status == "failed" and not list(outputs.glob("mapdry_*"))


def test_create_writes_the_expected_file_set(project):
    outputs = project[0]
    result = create(project, preview(project))
    assert result.status == "mapping_complete_review_required", result.errors
    for name in result.artifacts.values():
        assert (outputs / name).is_file() and not (outputs / (name + ".part")).exists()
    assert set(result.artifacts) == {"cover_type_tif", "forest_land_tif", "codebook_csv", "cover_type_acreage_csv", "forest_land_acreage_csv", "methods_json"}
    assert result.artifacts["methods_json"] == "cmap_63182cc4_v2_methods.json"


def test_methods_satisfy_what_the_raw_patch_step_checks(project):
    outputs = project[0]
    result = create(project, preview(project))
    doc = json.loads((outputs / result.artifacts["methods_json"]).read_text())
    assert doc["document_type"] == "candidate_cover_type_methods_and_provenance"
    assert doc["mapping_status"] == "complete" and doc["rasters_written"] is True and not doc["write_errors"]
    for key in ("classification_performed", "crosswalk_applied", "candidate_cover_types_produced", "candidate_forest_land_produced"):
        assert doc["sentinels"][key] is True
    assert all(doc["acreage_closure"].values())
    for key in ("job_id", "crosswalk_id", "crosswalk_version", "cover_scheme_id", "cover_scheme_version", "crosswalk_approval_note"):
        assert isinstance(doc[key], str) and doc[key].strip()
    assert doc["nodata_value"] == -9999 and doc["raster_shape"] == INFO["shape"] and doc["raster_transform"] == INFO["transform"]
    assert doc["total_pixels"] == 15 and doc["valid_cell_count"] == 11 and doc["nodata_cell_count"] == 4
    assert doc["outside_boundary_cells"] == 3 and doc["evt_nodata_inside_boundary_cells"] == 1
    area = doc["cell_area_m2"]
    for row in doc["cover_type_stats"]:
        assert math.isclose(row["square_meters"], row["cell_count"] * area, rel_tol=1e-9, abs_tol=0.02)
        assert math.isclose(row["acres"], row["square_meters"] / bm.ACRE_M2, abs_tol=0.00011)
    assert math.isclose(doc["valid_acres"], doc["valid_cell_count"] * area / bm.ACRE_M2, abs_tol=0.00011)
    assert doc["sentinels"]["candidate_polygons_produced"] is False and doc["sentinels"]["boundary_clipping_performed"] is True


def test_codebook_matches_stats_and_forest_status(project):
    outputs = project[0]
    result = create(project, preview(project))
    doc = json.loads((outputs / result.artifacts["methods_json"]).read_text())
    with (outputs / result.artifacts["codebook_csv"]).open(encoding="utf-8-sig", newline="") as stream:
        rows = {int(r["output_code"]): r for r in csv.DictReader(stream)}
    assert set(rows[1]) >= {"output_code", "output_label", "candidate_forest_land", "description", "source_evt_codes"}
    for s in doc["cover_type_stats"]:
        row = rows[s["output_code"]]
        assert row["output_label"] == s["output_label"]
        assert row["candidate_forest_land"] == {True: "true", False: "false", None: "null"}[s["candidate_forest_land"]]
    assert rows[8]["source_evt_codes"] == "7024" and rows[5]["candidate_forest_land"] == "false"


def test_acreage_csvs_keep_outside_and_nodata_separate(project):
    outputs = project[0]
    result = create(project, preview(project))
    text = (outputs / result.artifacts["cover_type_acreage_csv"]).read_text(encoding="utf-8-sig")
    assert "outside_boundary_masked" in text and "evt_nodata_inside_boundary" in text
    forest = (outputs / result.artifacts["forest_land_acreage_csv"]).read_text(encoding="utf-8-sig")
    assert "candidate_forest_land_unknown" in forest


def test_create_requires_matching_preview(project):
    outputs = project[0]
    p = preview(project)
    other = bm.create_boundary_mapping(outputs, bm.CreateMappingRequest(acquisition_directory="bacq_other", preview_directory=p.artifacts["preview_directory"],
                                                                         crosswalk_filename=CW_NAME), project[1])
    assert other.status == "failed" and not list(outputs.glob("cmap_*"))


def test_create_blocks_changed_inputs(project):
    outputs, pdata, acq, tif, boundary = project
    p = preview(project)
    put_crosswalk(pdata, crosswalk(crosswalk_approval_note="CHANGED AFTER PREVIEW"))
    result = create(project, p)
    assert result.status == "failed" and "changed since the preview" in result.errors[0] and not list(outputs.glob("cmap_*"))


def test_create_blocks_tampered_preview_counts(project):
    outputs = project[0]
    p = preview(project)
    path = outputs / p.artifacts["preview_directory"] / "mapping_preview.json"
    doc = json.loads(path.read_text()); doc["summary"]["classes"][0]["cell_count"] += 1
    path.write_text(json.dumps(doc))
    result = create(project, p)
    assert result.status == "failed" and "differ from the preview" in result.errors[0]


def test_create_never_overwrites(project):
    outputs = project[0]
    p = preview(project)
    first = create(project, p)
    sizes = {n: (outputs / n).stat().st_size for n in first.artifacts.values()}
    second = create(project, p)
    assert second.status == "failed" and "will not be overwritten" in second.errors[0]
    assert sizes == {n: (outputs / n).stat().st_size for n in first.artifacts.values()}


def test_write_failure_removes_partial_files(project, monkeypatch):
    outputs = project[0]
    p = preview(project)
    def partial(paths, out, fl, info, tags):
        Path(paths["cover_type_tif"]).write_bytes(b"partial")
        raise OSError("SIMULATED disk failure")
    monkeypatch.setattr(bm, "_write_and_verify_rasters", partial)
    result = create(project, p)
    assert result.status == "failed" and "SIMULATED" in result.errors[0]
    assert not list(outputs.glob("cmap_*"))


def test_raster_readback_failure_blocks_output(project, monkeypatch):
    outputs = project[0]
    p = preview(project)
    def mismatch(paths, out, fl, info, tags):
        Path(paths["cover_type_tif"]).write_bytes(b"x")
        raise bm.MappingError("Read-back mismatch: cover_type_tif")
    monkeypatch.setattr(bm, "_write_and_verify_rasters", mismatch)
    assert create(project, p).status == "failed" and not list(outputs.glob("cmap_*"))


def test_request_validation():
    for name in ("../bacq_x", "bacq_x/y", "bacq x"):
        with pytest.raises(ValidationError):
            bm.MappingRequest(acquisition_directory=name)
    with pytest.raises(ValidationError):
        bm.CreateMappingRequest(acquisition_directory=ACQ, preview_directory="../mapdry_x")
    with pytest.raises(ValidationError):
        bm.MappingRequest(acquisition_directory=ACQ, unknown_field=1)


# ---- REAL raster tests (need rasterio) ---------------------------------------------------------------------------
def real_tif(path, descriptions=None):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    descriptions = descriptions or bm.EXPECTED_BANDS
    evt = np.full((20, 20), 7054, dtype="int32")
    evt[:, 10:] = 7025
    evt[0:2, 0:2] = -9999
    with rasterio.open(path, "w", driver="GTiff", height=20, width=20, count=3, dtype="int32", crs="EPSG:5070",
                       transform=from_origin(-917_000.0, 1_160_000.0, 30.0, 30.0), nodata=-9999) as dst:
        dst.write(evt, 1); dst.write(np.full((20, 20), 110, dtype="int32"), 2); dst.write(np.full((20, 20), 101, dtype="int32"), 3)
        for i, name in enumerate(descriptions, start=1):
            dst.set_band_description(i, name)
    return evt


def real_boundary(path):
    gpd.GeoDataFrame({"geometry": [box(-916_850.0, 1_159_550.0, -916_550.0, 1_159_850.0)]}, crs="EPSG:5070").to_crs(4326).to_file(path, driver="GeoJSON", engine="pyogrio")


def test_real_read_inputs_clips_to_boundary(tmp_path):
    pytest.importorskip("rasterio")
    real_tif(tmp_path / "t.tif"); real_boundary(tmp_path / "b.geojson")
    evt, inside, info = bm._read_inputs(tmp_path / "t.tif", tmp_path / "b.geojson")
    assert evt.shape == inside.shape == (20, 20) and info["shape"] == [20, 20]
    assert 80 <= inside.sum() <= 121 and not inside[0:2, 0:2].any()
    assert set(np.unique(evt[inside])) <= {7054, 7025}


def test_real_read_inputs_rejects_wrong_band_order(tmp_path):
    pytest.importorskip("rasterio")
    real_tif(tmp_path / "t.tif", descriptions=["LF2025_EVC_CONUS", "LF2025_EVT_CONUS", "LF2025_EVH_CONUS"]); real_boundary(tmp_path / "b.geojson")
    with pytest.raises(bm.MappingError, match="bands"):
        bm._read_inputs(tmp_path / "t.tif", tmp_path / "b.geojson")


def test_real_write_round_trip(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    out = np.full((4, 5), -9999, np.int32); out[1:3, 1:4] = 1
    fl = np.full((4, 5), -9999, np.int32); fl[1:3, 1:4] = 2
    info = {"shape": [4, 5], "transform": [30.0, 0.0, -920655.0, 0.0, -30.0, 1194825.0], "epsg": 5070, "cell_area_m2": 900.0}
    paths = {"cover_type_tif": tmp_path / "ct.tif", "forest_land_tif": tmp_path / "fl.tif"}
    bm._write_and_verify_rasters(paths, out, fl, info, {"job_id": JOB})
    with rasterio.open(paths["cover_type_tif"]) as src:
        assert src.nodata == -9999 and src.crs.to_epsg() == 5070 and np.array_equal(src.read(1), out)
        assert src.tags()["job_id"] == JOB
