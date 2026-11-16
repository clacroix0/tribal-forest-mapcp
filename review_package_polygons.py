"""Controlled raw-patch snapshots and validation for review export. No network."""
import math
import re
from pathlib import Path

from review_package import (ExportError, MAX_BYTES, MAX_METHODS_BYTES, _copy_regular,
                            _rows, read_json_bytes, require, sha256_file)

RAW_RUN_RE = re.compile(r"rawpatch_[0-9a-fA-F]{8}_v[1-9][0-9]{0,3}_[0-9]{8}T[0-9]{6}_[0-9a-f]{6}")
POLYGON_NAMES = ("raw_cover_type_patches.gpkg", "raw_patch_acreage.csv", "raw_patch_qc.json")
POLYGON_SCOPE = "preliminary_raster_and_raw_polygon_review"


def snapshot_raw_patches(root, stage, run_name, used):
    require(type(run_name) is str and RAW_RUN_RE.fullmatch(run_name),
            "invalid_input", "Use the exact returned rawpatch run folder name, never a path.")
    folder = root / run_name
    require(not folder.is_symlink() and folder.is_dir() and folder.resolve().parent == root,
            "unsafe_directory", "Raw-patch run must be a real directory directly inside outputs.")
    require(not (folder / "FAILED_DO_NOT_USE.json").exists(),
            "incomplete_polygons", "Failed polygon runs cannot be exported.")
    try:
        remaining = sum((folder / name).lstat().st_size for name in POLYGON_NAMES)
    except OSError:
        raise ExportError("missing_polygon_artifact", "A required raw-patch artifact is missing.") from None
    require(used + remaining <= MAX_BYTES, "size_limit", "Combined raster/polygon source size exceeds the export limit.")
    import shutil
    require(shutil.disk_usage(root).free >= 2 * remaining + used + 2 * 1024 * 1024,
            "insufficient_space", "Insufficient temporary space for polygon snapshot and ZIP.")
    for name in POLYGON_NAMES:
        limit = min(MAX_BYTES-used, MAX_METHODS_BYTES) if name.endswith((".json", ".csv")) else MAX_BYTES-used
        used += _copy_regular(folder / name, stage / name, limit)
    require(not folder.is_symlink() and not (folder / "FAILED_DO_NOT_USE.json").exists(),
            "source_changed", "Polygon run changed or failed during snapshot.")
    return used


def validate_raw_patches(stage, names, methods, run_name):
    report = read_json_bytes((stage / "raw_patch_qc.json").read_bytes())
    require(report.get("document_type") == "candidate_cover_type_raw_patch_qc" and
            report.get("status") == "complete_review_required" and
            report.get("candidate_polygons_produced") is True,
            "incomplete_polygons", "Polygon QC does not report a completed raw-patch run.")
    for key in ("candidate_stands_produced", "new_classification_performed", "smoothing",
                "small_patch_removal", "minimum_mapping_unit_applied"):
        require(report.get(key) is False, "unsupported_polygons", "Only unchanged raw patches are supported.")
    require(type(report.get("connectivity")) is int and report["connectivity"] == 4,
            "unsupported_polygons", "Only the existing four-neighbor raw patches are supported.")
    for key in ("job_id", "crosswalk_id", "crosswalk_version", "cover_scheme_id", "cover_scheme_version"):
        require(report.get(key) == methods.get(key) and isinstance(methods.get(key), str),
                "polygon_identity_mismatch", "Polygon and raster provenance disagree.")
    prefix = names["methods_json"].removesuffix("_methods.json").removeprefix("cmap_")
    require(run_name.startswith("rawpatch_" + prefix + "_"),
            "polygon_identity_mismatch", "Raw-patch run name differs from the mapping run.")
    require(report.get("source_methods_filename") == names["methods_json"] and
            report.get("source_raster_filename") == names["cover_type_tif"],
            "polygon_identity_mismatch", "Polygon source filenames differ from the packaged run.")
    hashes = report.get("source_sha256", {})
    for key, name in (("cover_type_tif", names["cover_type_tif"]),
                      ("codebook_csv", names["cover_type_codebook_csv"]),
                      ("slice3_methods", names["methods_json"])):
        require(isinstance(hashes, dict) and hashes.get(key) == sha256_file(stage / name),
                "polygon_source_changed", "Packaged source bytes differ from those used to generate the polygons.")
    require(report.get("raster_shape") == methods["raster_shape"] and
            report.get("raster_transform") == methods["raster_transform"],
            "polygon_identity_mismatch", "Polygon source grid differs from the mapping run.")
    saved = report.get("qc", {})
    for key in ("geometry_valid", "raster_roundtrip_matches", "per_class_closure_matches",
                "geopackage_readback_passed", "input_files_unchanged"):
        require(isinstance(saved, dict) and saved.get(key) is True,
                "incomplete_polygons", "Required polygon QC is missing or failed.")
    try:
        import geopandas as gpd
        import numpy as np
        import pyogrio
        import rasterio
        from pyproj import CRS
        from cover_type_patches import (LAYER, MAX_PATCHES, _build_frame, _check_source,
                                        _codebook, _polygon_qc, _readback)
    except ImportError:
        raise ExportError("gis_dependency_missing", "Polygon validation dependencies are unavailable.") from None
    try:
        gpkg = stage / "raw_cover_type_patches.gpkg"
        layers = pyogrio.list_layers(gpkg)
        require(len(layers) == 1 and layers[0][0] == LAYER,
                "invalid_polygons", "GeoPackage must contain only the expected raw-patch layer.")
        info = pyogrio.read_info(gpkg, layer=LAYER, force_feature_count=True)
        require(0 < info["features"] <= MAX_PATCHES,
                "size_limit", "Raw-patch feature count is empty or exceeds its existing limit.")
        require(type(report.get("patch_count")) is int and report["patch_count"] == info["features"],
                "invalid_polygons", "Polygon count differs from the recorded run.")
        actual = gpd.read_file(gpkg, layer=LAYER, engine="pyogrio")
        with rasterio.open(stage / names["cover_type_tif"]) as src:
            masked = src.read(1, masked=True)
            valid = ~np.ma.getmaskarray(masked)
            data = np.asarray(masked.data).astype("int32")
            book = _codebook(stage / names["cover_type_codebook_csv"])
            observed = _check_source(data, valid, src.nodata, src.transform, src.crs, methods, book)
            require(CRS.from_user_input(report.get("crs")) == CRS.from_user_input(src.crs),
                    "polygon_identity_mismatch", "Polygon QC CRS differs from the raster.")
            # Reconstruct expected patches for validation only; write no new polygon run.
            expected = _build_frame(data, valid, src.transform, src.crs, book, methods)
            expected["source_raster"] = names["cover_type_tif"]
            expected["source_methods"] = names["methods_json"]
            expected["provenance_reference"] = "raw_patch_qc.json"
            require(set(actual.columns) == set(expected.columns),
                    "invalid_polygons", "Unexpected or missing raw-patch attributes.")
            _readback(expected, actual, src.crs)
            fresh = _polygon_qc(actual, data, valid, src.transform, observed)
        rows = _rows(stage / "raw_patch_acreage.csv")
        require(len(rows) == len(fresh["per_class"]), "polygon_statistics_mismatch", "Polygon acreage classes differ.")
        by_code = {}
        for row in rows:
            code = int(row["output_code"])
            require(code not in by_code, "polygon_statistics_mismatch", "Duplicate polygon acreage class.")
            by_code[code] = row
        saved_rows = saved.get("per_class")
        require(isinstance(saved_rows, list) and len(saved_rows) == len(fresh["per_class"]),
                "polygon_statistics_mismatch", "Saved polygon QC classes differ.")
        for expected_row in fresh["per_class"]:
            row = by_code.get(expected_row["output_code"])
            recorded = [r for r in saved_rows if isinstance(r, dict) and r.get("output_code") == expected_row["output_code"]]
            require(row is not None and len(recorded) == 1, "polygon_statistics_mismatch", "Polygon class summary is missing or duplicated.")
            for candidate in (row, recorded[0]):
                for key, value in expected_row.items():
                    if isinstance(value, str):
                        ok = candidate.get(key) == value
                    else:
                        actual_value = float(candidate.get(key))
                        ok = math.isfinite(actual_value) and math.isclose(actual_value, value, rel_tol=0, abs_tol=1e-8)
                    require(ok, "polygon_statistics_mismatch", "Polygon summary disagrees with actual geometry.")
        for key in ("total_valid_cells", "nodata_cells", "valid_area_m2", "valid_acres", "nodata_acres"):
            value = saved.get(key)
            require(type(value) in (int, float) and math.isfinite(value) and
                    math.isclose(value, fresh[key], rel_tol=0, abs_tol=1e-8),
                    "polygon_statistics_mismatch", "Saved polygon QC totals disagree with current geometry.")
        return {"raw_run_directory": run_name, "layer": LAYER, "patch_count": len(actual),
                "source_hashes_match": True, "geometry_and_attributes_match_raw_raster_patches": True,
                "raster_roundtrip_matches": True, "acreage_summary_matches": True,
                "valid_acres": fresh["valid_acres"], "nodata_cells": fresh["nodata_cells"],
                "nodata_policy": "NoData remains holes/gaps, separately counted; it is not nonforest."}
    except ExportError:
        raise
    except Exception:
        raise ExportError("invalid_polygons", "Raw-patch geometry, attributes, or summaries failed validation.") from None
