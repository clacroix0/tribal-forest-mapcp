from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import geopandas as gpd
import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from pyproj import CRS, Transformer
from shapely import union_all
from shapely.geometry import box
from shapely.ops import transform as transform_geometry

METHOD_VERSION = "full_boundary_preparation_v1"
ACRE_M2 = 4046.8564224
MAX_BOUNDARY_BYTES = 5_000_000
MAX_BOUNDARY_FEATURES = 10_000
MAX_BOUNDARY_COORDINATES = 1_000_000
LFPS_SUBMIT_URL = "https://lfps.usgs.gov/api/job/submit"
LFPS_STATUS_URL = "https://lfps.usgs.gov/api/job/status"
PRODUCTS = ["LF2025_EVT", "LF2025_EVC", "LF2025_EVH"]
RESOLUTION_M = 30.0
OUTPUT_EPSG = 5070

# Historical prototype limits are reported, not changed or treated as vendor limits.
EXISTING_SAMPLE_AOI_LIMIT_DEGREES = 0.25
EXISTING_RAW_PIXEL_LIMIT = 250_000
EXISTING_RAW_PATCH_LIMIT = 20_000
EXISTING_BUNDLE_LIMIT_BYTES = 100_000_000


class BoundaryPreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    boundary_filename: str = Field(pattern=r"^[A-Za-z0-9_.-]+\.geojson$", max_length=240)
    project_name: str = Field(default="Public boundary mapping project", min_length=1, max_length=120)
    product_profile: Literal["lf2025_evt_evc_evh_conus"] = "lf2025_evt_evc_evh_conus"


class BoundaryPreparationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["prepared_review_required", "failed"]
    stage: str
    request_prepared: bool = False
    execution_ready: bool = False
    job_submitted: bool = False
    rasters_downloaded: bool = False
    classification_performed: bool = False
    summary: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)


class BoundaryPreparationError(ValueError):
    pass


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _coordinate_count(frame) -> int:
    from shapely import get_num_coordinates
    return int(sum(get_num_coordinates(geom) for geom in frame.geometry))


def inspect_boundary_frame(frame: gpd.GeoDataFrame) -> dict:
    """Validate supplied geometry and estimate a bounded lower-48 request. No IO or network."""
    if frame.empty or len(frame) > MAX_BOUNDARY_FEATURES:
        raise BoundaryPreparationError("Boundary is empty or exceeds the feature limit.")
    if frame.crs is None:
        raise BoundaryPreparationError("Boundary CRS is missing; do not guess it.")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise BoundaryPreparationError("Boundary has null or empty geometry.")
    if not frame.geometry.is_valid.all():
        raise BoundaryPreparationError("Boundary geometry is invalid; no automatic repair performed.")
    if not set(frame.geometry.geom_type) <= {"Polygon", "MultiPolygon"}:
        raise BoundaryPreparationError("Boundary must contain Polygon or MultiPolygon features.")
    if _coordinate_count(frame) > MAX_BOUNDARY_COORDINATES:
        raise BoundaryPreparationError("Boundary coordinate limit exceeded.")
    geographic = frame.to_crs(epsg=4326)
    west, south, east, north = [float(v) for v in geographic.total_bounds]
    if not all(math.isfinite(v) for v in (west, south, east, north)):
        raise BoundaryPreparationError("Boundary has non-finite bounds.")
    if not (-125 <= west < east <= -66 and 24 <= south < north <= 50):
        raise BoundaryPreparationError("Version 1 supports the lower-48 bounding extent only; use a separately approved regional profile elsewhere.")
    projected = frame.to_crs(epsg=OUTPUT_EPSG)
    if not projected.geometry.is_valid.all() or projected.geometry.is_empty.any():
        raise BoundaryPreparationError("Boundary became invalid after projection.")
    geometry = union_all(projected.geometry.to_numpy())
    if not geometry.is_valid or geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise BoundaryPreparationError("Projected boundary union is invalid.")
    area = float(geometry.area)
    if not math.isfinite(area) or area <= 0:
        raise BoundaryPreparationError("Projected boundary area is not positive and finite.")
    tolerance = max(0.01, area * 1e-9)
    overlap = max(0.0, float(projected.geometry.area.sum() - area))
    if overlap > tolerance:
        raise BoundaryPreparationError("Boundary features overlap; do not double-count or silently dissolve overlapping project areas.")
    # Densify the geographic download rectangle to estimate its projected footprint.
    xs = np.linspace(west, east, 101)
    ys = np.linspace(south, north, 101)
    edge_x = np.concatenate([xs, np.full(101, east), xs[::-1], np.full(101, west)])
    edge_y = np.concatenate([np.full(101, south), ys, np.full(101, north), ys[::-1]])
    transformer = Transformer.from_crs(4326, OUTPUT_EPSG, always_xy=True)
    px, py = transformer.transform(edge_x, edge_y)
    if not np.isfinite(px).all() or not np.isfinite(py).all():
        raise BoundaryPreparationError("Projected download envelope is invalid.")
    boundary_bounds = [float(v) for v in geometry.bounds]
    xmin = min(float(np.min(px)), boundary_bounds[0])
    ymin = min(float(np.min(py)), boundary_bounds[1])
    xmax = max(float(np.max(px)), boundary_bounds[2])
    ymax = max(float(np.max(py)), boundary_bounds[3])
    # Padding is a planning allowance, NOT knowledge of the service's native grid origin.
    columns = int(math.ceil((xmax - xmin) / RESOLUTION_M)) + 2
    rows = int(math.ceil((ymax - ymin) / RESOLUTION_M)) + 2
    pixels = columns * rows
    area_equivalent_cells = area / (RESOLUTION_M ** 2)
    array_estimates = {
        "source_three_band_int32_scenario_bytes": pixels * 3 * 4,
        "candidate_two_band_int16_scenario_bytes": pixels * 2 * 2,
        "one_boolean_mask_scenario_bytes": pixels,
        "note": "Illustrative uncompressed arrays only. Source dtype, ZIP size, GDAL buffers, copies, geometry and total peak RAM are unknown.",
    }
    ids = {}
    for col in ("OBJECTID", "LARID", "LARName", "NAME", "BASENAME"):
        if col in frame:
            ids[col] = [str(v) if v is not None else None for v in frame[col].tolist()]
    warnings = [
        "Public boundary geometry does not establish ownership, trust status, jurisdiction, legal access, Tribal approval or forestry management authority.",
        "Download AOI is a geographic rectangle; final mapping must mask/clip to the actual selected polygon.",
        "Grid dimensions are estimates; native grid origin, returned coverage and NoData must be verified after acquisition.",
        "Current LFPS API/product availability and remote size limits were not checked by this preparation-only operation.",
        "The existing sample submission tool is not compatible with this boundary-request document.",
        "Full-area source codes and crosswalk coverage must be inspected after acquisition; sample crosswalk completeness is not sufficient.",
        "Full-area raster processing, boundary masking, polygon scaling and seam handling are separate unfinished stages.",
    ]
    width, height = east - west, north - south
    exceeds_sample = width > EXISTING_SAMPLE_AOI_LIMIT_DEGREES or height > EXISTING_SAMPLE_AOI_LIMIT_DEGREES
    exceeds_pixels = pixels > EXISTING_RAW_PIXEL_LIMIT
    if exceeds_sample:
        warnings.append("Proposed AOI exceeds existing MapCP sample prepare/submit bounds; the sample submission path would reject it.")
    if exceeds_pixels:
        warnings.append("Estimated downloaded grid exceeds the existing raw-patch pixel limit; do not remove it blindly.")
    return {
        "workflow_profile": "lower48_5070_30m_v1", "feature_count": len(frame),
        "geometry_valid": True, "input_crs": CRS.from_user_input(frame.crs).to_string(),
        "area_crs": "EPSG:5070", "area_method": "planar union area in NAD83 / Conus Albers",
        "area_m2": area, "boundary_acres": area / ACRE_M2,
        "boundary_overlap_m2": overlap, "area_tolerance_m2": tolerance,
        "coordinate_count": _coordinate_count(frame), "source_identifiers": ids,
        "download_aoi_wgs84": [west, south, east, north],
        "download_aoi_width_degrees": width, "download_aoi_height_degrees": height,
        "boundary_bounds_epsg5070": boundary_bounds,
        "estimated_download_bounds_epsg5070": [xmin, ymin, xmax, ymax],
        "estimated_grid_columns": columns, "estimated_grid_rows": rows,
        "estimated_download_pixels": pixels,
        "area_equivalent_30m_cells": area_equivalent_cells,
        "cell_estimate_note": "Polygon area divided by 900 m2; not an observed raster count or coverage estimate.",
        "planning_grid_padding_cells_per_axis": 2,
        "array_estimates": array_estimates,
        "existing_limit_checks": {
            "sample_aoi_limit_degrees": EXISTING_SAMPLE_AOI_LIMIT_DEGREES,
            "exceeds_sample_aoi_limit": exceeds_sample,
            "raw_patch_max_pixels": EXISTING_RAW_PIXEL_LIMIT,
            "exceeds_raw_patch_pixel_limit": exceeds_pixels,
            "raw_patch_max_patches": EXISTING_RAW_PATCH_LIMIT,
            "full_area_patch_count_known": False,
            "bundle_limit_bytes": EXISTING_BUNDLE_LIMIT_BYTES,
            "compressed_bundle_size_known": False,
        },
        "warnings": warnings,
    }


def prepare_boundary_mapping_request(outputs_root: Path, request: BoundaryPreparationRequest) -> BoundaryPreparationResult:
    """Preparation only: no HTTP calls, no email, no raster acquisition or classification."""
    started = time.perf_counter()
    stage = "validate_boundary_file"
    run_dir = None
    try:
        root = Path(outputs_root).resolve()
        source = (root / request.boundary_filename).resolve()
        if source.parent != root or not source.is_file():
            raise BoundaryPreparationError("Boundary must be an existing direct outputs-folder file; paths and escaping symlinks are rejected.")
        if source.stat().st_size > MAX_BOUNDARY_BYTES:
            raise BoundaryPreparationError("Boundary exceeds the 5 MB preparation limit.")
        before = _digest(source)

        document = json.loads(
            source.read_text(encoding="utf-8-sig")
        )

        if (
            not isinstance(document, dict)
            or document.get("type") != "FeatureCollection"
            or not isinstance(document.get("features"), list)
        ):
            raise BoundaryPreparationError(
                "Boundary must be a GeoJSON FeatureCollection."
            )

        if len(document["features"]) > MAX_BOUNDARY_FEATURES:
            raise BoundaryPreparationError(
                "Boundary feature limit exceeded."
            )

        stage = "read_boundary"
        frame = gpd.read_file(source, engine="pyogrio")
        stage = "preflight"
        summary = inspect_boundary_frame(frame)
        disk = shutil.disk_usage(root)
        summary["local_disk_free_bytes_at_preparation"] = int(disk.free)
        summary["storage_requirement_verified"] = False
        summary["project_name"] = request.project_name
        summary["product_profile"] = request.product_profile
        west, south, east, north = summary["download_aoi_wgs84"]
        parameters = {
            "Layer_List": ";".join(PRODUCTS),
            "Include_Layer_List_XML_File": "true",
            "Area_of_Interest": f"{west:.12f} {south:.12f} {east:.12f} {north:.12f}",
            "Output_Projection": str(OUTPUT_EPSG),
        }
        if _digest(source) != before:
            raise BoundaryPreparationError("Boundary changed during preflight.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        run_dir = root / f"boundaryprep_{stamp}_{uuid.uuid4().hex[:8]}"
        stage = "write_preparation"
        run_dir.mkdir(exist_ok=False)
        request_path = run_dir / "boundary_request.json"
        summary_path = run_dir / "boundary_preflight.json"
        notes_path = run_dir / "REVIEW_BEFORE_SUBMISSION.txt"
        artifacts = {"prepared_request_json": str(request_path), "preflight_json": str(summary_path), "review_notes": str(notes_path)}
        prepared = {
            "document_type": "mapcp_full_boundary_request_v1",
            "status": "prepared_review_required", "execution_ready": False,
            "method_version": METHOD_VERSION, "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "project_name": request.project_name, "product_profile": request.product_profile,
            "source_boundary_filename": source.name, "source_boundary_sha256": before,
            "analysis_boundary": {"filename": source.name, "sha256": before, "area_crs": "EPSG:5070", "boundary_acres": summary["boundary_acres"]},
            "apiversion": "LFPS v2", "submission_method": "GET",
            "proposed_submission_endpoint": LFPS_SUBMIT_URL, "proposed_status_endpoint": LFPS_STATUS_URL,
            "proposed_parameters_without_email": parameters, "products": PRODUCTS,
            "remote_contract_verified_this_run": False,
            "remote_area_and_download_limits_verified": False,
            "existing_sample_submission_compatible": False,
            "submission_adapter_implemented": False,
            "job_submitted": False, "rasters_downloaded": False, "classification_performed": False,
            "contact_email_stored": False, "contact_email_supplied": False,
            "native_resolution_expected_m": RESOLUTION_M, "resampling_parameter_sent": False,
            "boundary_clipping_performed": False, "crosswalk_applied": False,
            "required_next_steps": [
                "Review the selected boundary and proposed products/extent.",
                "Verify current LFPS contract and permitted request/download size.",
                "Implement and test a boundary-aware submission/collection adapter; preserve exact reviewed request.",
                "Obtain explicit approval before remote submission.",
                "After acquisition inspect complete source-code coverage and approve crosswalk changes.",
                "Implement boundary masking, coverage accounting and full-area processing within approved limits.",
            ],
        }
        with request_path.open("x", encoding="utf-8") as stream:
            json.dump(prepared, stream, indent=2, allow_nan=False)
        details = {
            "document_type": "mapcp_full_boundary_preflight_v1", "status": "prepared_review_required",
            "method_version": METHOD_VERSION, "summary": summary,
            "source_boundary_filename": source.name, "source_boundary_sha256": before,
            "runtime_seconds": time.perf_counter() - started, "artifacts": artifacts,
            "processing_limits": {"boundary_bytes": MAX_BOUNDARY_BYTES, "features": MAX_BOUNDARY_FEATURES, "coordinates": MAX_BOUNDARY_COORDINATES},
            "software": {"geopandas": gpd.__version__, "numpy": np.__version__},
            "input_unchanged": True, "job_submitted": False,
        }
        with summary_path.open("x", encoding="utf-8") as stream:
            json.dump(details, stream, indent=2, allow_nan=False)
        notes_path.write_text(
            "This is a preparation document, NOT a submitted job.\n"
            "Do not feed it to submit_landfire_v2_sample_job or rename it to mimic a sample request.\n"
            "Confirm boundary suitability and proposed products/extent; public geometry does not establish legal authority.\n"
            "Current service limits were not checked. Storage/RAM estimates are not a resource guarantee.\n"
            "A new reviewed submission/collection adapter and full-area processing are still required.\n"
            "No contact email is needed at this stage. No network request occurred.\n", encoding="utf-8")
        if _digest(source) != before:
            raise BoundaryPreparationError("Boundary changed while writing preparation artifacts.")
        return BoundaryPreparationResult(status="prepared_review_required", stage="complete", request_prepared=True,
                                         summary=summary, warnings=summary["warnings"], artifacts=artifacts)
    except Exception as exc:
        errors = [f"{type(exc).__name__}: {exc}"]
        artifacts = {}
        if run_dir is not None and run_dir.is_dir():
            marker = run_dir / "FAILED_DO_NOT_USE.json"
            try:
                with marker.open("x", encoding="utf-8") as stream:
                    json.dump({"status": "failed", "stage": stage, "accept_outputs": False, "errors": errors}, stream, indent=2)
                artifacts = {"failure_report": str(marker), "incomplete_run_directory": str(run_dir)}
            except OSError as write_error:
                errors.append(f"Failure report write failed: {write_error}")
        return BoundaryPreparationResult(status="failed", stage=stage, errors=errors, artifacts=artifacts)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prepare a generic lower-48 boundary request; no network or downloads.")
    parser.add_argument("boundary_filename", help="GeoJSON filename directly inside outputs, not a path.")
    parser.add_argument("--project-name", default="Public boundary mapping project")
    args = parser.parse_args()
    req = BoundaryPreparationRequest(boundary_filename=args.boundary_filename, project_name=args.project_name)
    result = prepare_boundary_mapping_request(Path(__file__).resolve().parent / "outputs", req)
    print(result.model_dump_json(indent=2))
    raise SystemExit(0 if result.status == "prepared_review_required" else 1)
