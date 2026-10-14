from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import geopandas as gpd
import numpy as np
from pandas.api.types import is_numeric_dtype
from pydantic import BaseModel, ConfigDict, Field
from pyproj import CRS
from shapely import union_all
from shapely.geometry import Polygon, shape, mapping, box

ACRE_M2 = 4046.8564224
MAX_PIXELS = 4_000_000
MAX_PATCHES = 200_000
MAX_RASTER_BYTES = 100_000_000
MAX_METADATA_BYTES = 5_000_000
LAYER = "candidate_cover_type_raw_patches"
METHODS_PATTERN = r"cmap_[0-9a-fA-F]{8}_[A-Za-z0-9_-]+_methods\.json"

# These are the approved first-pass review requirements, not new typing rules.
APPROVED_LABEL_FLAGS = {
    "candidate_P": ["species_composition_not_directly_measured", "crown_cover_percentage_not_directly_measured"],
    "candidate_PJ": ["species_composition_not_directly_measured", "crown_cover_percentage_not_directly_measured"],
    "candidate_RIP_WOODY": ["riparian_feature_preserved", "riparian_subtype_not_resolved", "species_composition_not_directly_measured", "crown_cover_percentage_not_directly_measured"],
    "candidate_BR": ["oak_brush_vs_oak_woodland_review_required", "shrub_grass_mixture_not_resolved"],
    "candidate_G": ["ruderal_source_class"],
    "candidate_RIP_NONFOREST": ["riparian_feature_preserved", "ruderal_source_class"],
    "candidate_RIP_UNCERTAIN": ["riparian_feature_preserved", "riparian_forest_land_status_unresolved", "ruderal_source_class"],
    "candidate_UNCERTAIN_PINE_OAK": ["pine_oak_local_type_unresolved"],
    "unmapped_evt": ["source_evt_code_unmapped"],
    "candidate_MC": ["species_composition_not_directly_measured", "crown_cover_percentage_not_directly_measured"],
    "candidate_A": ["species_composition_not_directly_measured", "crown_cover_percentage_not_directly_measured"],
    "candidate_W": ["species_composition_not_directly_measured", "crown_cover_percentage_not_directly_measured"],
}
UNIVERSAL_FLAGS = ["overstory_understory_not_modeled", "disturbance_not_evaluated", "professional_forestry_review_required"]

class RawPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    methods_filename: str = Field(pattern=rf"^{METHODS_PATTERN}$")

class RawPatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["complete_review_required", "failed"]
    stage: str
    candidate_polygons_produced: bool = False
    candidate_stands_produced: bool = False
    new_classification_performed: bool = False
    connectivity: Literal[4] = 4
    patch_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    qc: dict = Field(default_factory=dict)

class PatchValidationError(ValueError):
    pass

def _input_file(root: Path, name: str, limit: int) -> Path:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise PatchValidationError("Input must be a filename, not a path.")
    path = (root / name).resolve()
    if path.parent != root.resolve():
        raise PatchValidationError("Input escaped the controlled outputs folder.")
    if not path.is_file():
        raise PatchValidationError(f"Missing input: {name}")
    if path.stat().st_size > limit:
        raise PatchValidationError(f"Input exceeds processing size limit: {name}")
    return path

def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise PatchValidationError("Methods JSON must be an object.")
    return value

def _forest_status(text: str) -> str:
    value = text.strip().lower()
    if value == "true":
        return "forest_land"
    if value == "false":
        return "nonforest"
    if value in {"null", ""}:
        return "unknown"
    raise PatchValidationError(f"Invalid candidate_forest_land value: {text!r}")

def _codebook(path: Path) -> dict[int, dict]:
    required = {"output_code", "output_label", "candidate_forest_land", "description", "source_evt_codes"}
    result = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not required.issubset(reader.fieldnames or []):
            raise PatchValidationError("Codebook is missing required columns.")
        for row in reader:
            code = int(row["output_code"])
            if code in result:
                raise PatchValidationError(f"Duplicate codebook output_code: {code}")
            label = row["output_label"].strip()
            if not label:
                raise PatchValidationError("Codebook output_label cannot be blank.")
            result[code] = {
                "output_label": label,
                "candidate_code": label.removeprefix("candidate_"),
                "candidate_name": row["description"],
                "forest_land_status": _forest_status(row["candidate_forest_land"]),
                "class_source_evt_codes": row["source_evt_codes"].strip(),
            }
    if not result:
        raise PatchValidationError("Codebook is empty.")
    return result

def _validate_methods(doc: dict) -> None:
    if doc.get("document_type") != "candidate_cover_type_methods_and_provenance":
        raise PatchValidationError("Not a Slice 3 candidate-cover-type methods document.")
    if doc.get("mapping_status") != "complete" or doc.get("rasters_written") is not True:
        raise PatchValidationError("Slice 3 does not report completed raster output.")
    if doc.get("write_errors"):
        raise PatchValidationError("Slice 3 contains unresolved write errors.")
    for key in ("classification_performed", "crosswalk_applied", "candidate_cover_types_produced", "candidate_forest_land_produced"):
        if doc.get("sentinels", {}).get(key) is not True:
            raise PatchValidationError(f"Slice 3 sentinel is not true: {key}")
    for key in ("cover_type_valid_sum_matches", "forest_land_valid_sum_matches", "total_pixel_sum_matches"):
        if doc.get("acreage_closure", {}).get(key) is not True:
            raise PatchValidationError(f"Slice 3 closure check is not true: {key}")
    for key in ("job_id", "crosswalk_id", "crosswalk_version", "cover_scheme_id", "cover_scheme_version", "crosswalk_approval_note"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            raise PatchValidationError(f"Missing Slice 3 provenance: {key}")


def _cell_area(transform, crs) -> float:
    parsed = CRS.from_user_input(crs)
    if parsed.to_epsg() != 5070:
        raise PatchValidationError("This bounded Slice 4 draft requires EPSG:5070; no reprojection is performed.")
    if not parsed.is_projected or any(not math.isclose(a.unit_conversion_factor, 1.0) for a in parsed.axis_info[:2]):
        raise PatchValidationError("Meter-based projected units are required.")
    values = [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f]
    if not all(math.isfinite(v) for v in values):
        raise PatchValidationError("Invalid affine transform.")
    if not (math.isclose(transform.a, 30.0, abs_tol=1e-8) and math.isclose(transform.e, -30.0, abs_tol=1e-8)
            and abs(transform.b) <= 1e-10 and abs(transform.d) <= 1e-10):
        raise PatchValidationError("This Slice 4 requires the existing north-up 30 m grid.")
    area = abs(transform.a * transform.e - transform.b * transform.d)
    if not math.isfinite(area) or area <= 0:
        raise PatchValidationError("Cell area is not positive and finite.")
    return area

def _check_source(data, valid, nodata, transform, crs, doc, book) -> dict:
    if nodata != doc.get("nodata_value") or nodata != -9999:
        raise PatchValidationError("Source NoData must match Slice 3 (-9999).")
    if list(data.shape) != doc.get("raster_shape"):
        raise PatchValidationError("Raster shape differs from Slice 3.")
    if CRS.from_user_input(crs).to_epsg() != doc.get("raster_crs_epsg"):
        raise PatchValidationError("Raster CRS differs from Slice 3.")
    actual = [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f]
    expected = doc.get("raster_transform")
    if not isinstance(expected, list) or len(expected) != 6 or not np.allclose(actual, expected, rtol=0, atol=1e-8):
        raise PatchValidationError("Raster transform differs from Slice 3.")
    nvalid = int(valid.sum())
    if nvalid == 0:
        raise PatchValidationError("Raster contains no valid cells; no polygon layer generated.")
    if (nvalid != doc.get("valid_cell_count") or data.size != doc.get("total_pixels")
            or data.size - nvalid != doc.get("nodata_cell_count")):
        raise PatchValidationError("Raster valid/NoData counts differ from Slice 3.")
    values, counts = np.unique(data[valid], return_counts=True)
    observed = {int(v): int(n) for v, n in zip(values, counts)}
    if set(observed) - set(book):
        raise PatchValidationError(f"Raster categories absent from codebook: {sorted(set(observed)-set(book))}")
    expected_counts = {}
    for row in doc.get("cover_type_stats", []):
        code = row["output_code"]
        if code in expected_counts:
            raise PatchValidationError("Duplicate category in Slice 3 statistics.")
        expected_counts[code] = row["cell_count"]
        if code not in book or row.get("output_label") != book[code]["output_label"]:
            raise PatchValidationError("Codebook label differs from Slice 3 statistics.")
        cfl = row.get("candidate_forest_land")
        status = "forest_land" if cfl is True else "nonforest" if cfl is False else "unknown"
        if status != book[code]["forest_land_status"]:
            raise PatchValidationError("Codebook forest-land status differs from Slice 3.")
    if observed != expected_counts:
        raise PatchValidationError("Raster class counts differ from Slice 3 statistics.")
    area = _cell_area(transform, crs)
    for row in doc["cover_type_stats"]:
        m2 = row["cell_count"] * area
        if not math.isclose(row["square_meters"], m2, rel_tol=1e-9, abs_tol=0.02):
            raise PatchValidationError("Slice 3 class square meters disagree with grid.")
        if not math.isclose(row["acres"], m2 / ACRE_M2, rel_tol=0, abs_tol=0.00011):
            raise PatchValidationError("Slice 3 class acres disagree with grid.")
    if not math.isclose(doc["valid_acres"], nvalid * area / ACRE_M2, rel_tol=0, abs_tol=0.00011):
        raise PatchValidationError("Slice 3 valid acres disagree with grid.")
    return observed

def _flags(label, doc) -> str:
    flags = set(UNIVERSAL_FLAGS)
    flags.update(doc.get("universal_review_flags", []))
    flags.update(APPROVED_LABEL_FLAGS.get(label, []))
    return "|".join(sorted(flags))

def _build_frame(data, valid, transform, crs, book, doc):
    from rasterio.features import shapes
    records = []
    for geom, value in shapes(data, mask=valid, transform=transform, connectivity=4):
        if len(records) >= MAX_PATCHES:
            raise PatchValidationError("Patch limit exceeded; no output accepted.")
        polygon = shape(geom)
        if polygon.is_empty or polygon.geom_type != "Polygon" or not polygon.is_valid:
            raise PatchValidationError("Invalid raw patch geometry; no automatic repair performed.")
        code = int(value)
        cell_area = _cell_area(transform, crs)
        cells_float = polygon.area / cell_area
        cells = round(cells_float)
        if cells < 1 or not math.isclose(cells_float, cells, rel_tol=0, abs_tol=1e-7):
            raise PatchValidationError("Raw patch area is not an integer number of cells.")
        attr = book[code]
        records.append({
            "output_code": code, **attr,
            "cell_count": int(cells), "area_m2": float(polygon.area),
            "area_acres": float(polygon.area / ACRE_M2),
            "review_flags": _flags(attr["output_label"], doc),
            "review_flag_scope": "conservative_class_level_not_patch_measured",
            "crosswalk_id": doc["crosswalk_id"], "crosswalk_version": doc["crosswalk_version"],
            "cover_scheme_id": doc["cover_scheme_id"], "cover_scheme_version": doc["cover_scheme_version"],
            "connectivity": 4, "geometry_stage": "raw",
            "geometry": polygon,
        })
    records.sort(key=lambda r: (r["output_code"], r["geometry"].bounds, r["geometry"].wkb_hex))
    for i, record in enumerate(records, 1):
        record["patch_id"] = f"CTP_{i:06d}"
    return gpd.GeoDataFrame(records, geometry="geometry", crs=crs)

def _polygon_qc(frame, data, valid, transform, observed) -> dict:
    from rasterio.features import rasterize, shapes
    if frame.empty or frame.patch_id.duplicated().any():
        raise PatchValidationError("Empty patch layer or duplicate patch IDs.")
    if not frame.geometry.is_valid.all() or frame.geometry.is_empty.any():
        raise PatchValidationError("Invalid or empty polygon geometry.")
    if set(frame.geometry.geom_type) != {"Polygon"}:
        raise PatchValidationError("Raw patches must be Polygon geometries.")
    reconstructed = rasterize(((g, int(c)) for g, c in zip(frame.geometry, frame.output_code)),
                              out_shape=data.shape, transform=transform, fill=-9999, dtype="int32")
    matches = np.array_equal(reconstructed[valid], data[valid]) and bool(np.all(reconstructed[~valid] == -9999))
    if not matches:
        raise PatchValidationError("Polygon-to-raster round trip changed values or filled NoData.")
    expected_parts = [shape(g) for g, v in shapes(valid.astype("uint8"), mask=valid, transform=transform, connectivity=4)]
    expected_footprint = union_all(expected_parts)
    footprint = union_all(frame.geometry.to_numpy())
    total_area = float(frame.geometry.area.sum())
    overlap = max(0.0, total_area - footprint.area)
    gap = expected_footprint.difference(footprint).area
    extra = footprint.difference(expected_footprint).area
    tolerance = max(0.01, expected_footprint.area * 1e-9)
    if max(overlap, gap, extra) > tolerance:
        raise PatchValidationError("Polygon overlap/gap/coverage QC failed.")
    per_class = []
    cell_area = abs(transform.a * transform.e - transform.b * transform.d)
    for code, count in sorted(observed.items()):
        subset = frame[frame.output_code == code]
        polygon_area = float(subset.geometry.area.sum())
        if int(subset.cell_count.sum()) != count or not math.isclose(polygon_area, count * cell_area, rel_tol=1e-9, abs_tol=0.01):
            raise PatchValidationError(f"Polygon cell-count or acreage closure failed for {code}.")
        per_class.append({"output_code": code, "output_label": subset.output_label.iloc[0],
                          "forest_land_status": subset.forest_land_status.iloc[0],
                          "patch_count": len(subset), "cell_count": count,
                          "square_meters": polygon_area, "acres": polygon_area / ACRE_M2})
    return {"geometry_valid": True, "raster_roundtrip_matches": True,
            "per_class_closure_matches": True, "total_valid_cells": int(valid.sum()),
            "nodata_cells": int(data.size - valid.sum()), "valid_area_m2": total_area,
            "valid_acres": total_area / ACRE_M2, "nodata_acres": int((~valid).sum()) * cell_area / ACRE_M2,
            "overlap_m2": float(overlap), "gap_m2": float(gap), "extra_coverage_m2": float(extra),
            "area_tolerance_m2": tolerance, "per_class": per_class}

def _digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def _readback(expected, actual, crs):
    if len(expected) != len(actual) or CRS.from_user_input(actual.crs) != CRS.from_user_input(crs):
        raise PatchValidationError("GeoPackage read-back count/CRS failed.")
    for column in expected.columns:
        if column not in actual:
            raise PatchValidationError(f"GeoPackage lost attribute: {column}")
    left = expected.sort_values("patch_id").reset_index(drop=True)
    right = actual.sort_values("patch_id").reset_index(drop=True)
    for column in left.columns:
        if column == "geometry":
            if not all(a.equals(b) for a, b in zip(left.geometry, right.geometry)):
                raise PatchValidationError("GeoPackage read-back geometry changed.")
        elif is_numeric_dtype(left[column]):
            if not np.allclose(left[column], right[column], rtol=1e-9, atol=1e-8):
                raise PatchValidationError(f"GeoPackage changed numeric attribute: {column}")
        elif left[column].fillna("").astype(str).tolist() != right[column].fillna("").astype(str).tolist():
            raise PatchValidationError(f"GeoPackage changed attribute: {column}")

def create_raw_cover_type_patches(outputs_root: Path, request: RawPatchRequest) -> RawPatchResult:
    """Read only controlled Slice 3 artifacts; write a new, isolated run folder."""
    started = time.perf_counter()
    stage = "validate_inputs"
    run_dir = None
    root = Path(outputs_root).resolve()
    try:
        methods_path = _input_file(root, request.methods_filename, MAX_METADATA_BYTES)
        doc = _json(methods_path)
        _validate_methods(doc)
        prefix = request.methods_filename.removesuffix("_methods.json")
        raster_path = _input_file(root, prefix + "_cover_type_30m.tif", MAX_RASTER_BYTES)
        book_path = _input_file(root, prefix + "_cover_type_codebook.csv", MAX_METADATA_BYTES)
        book = _codebook(book_path)
        import rasterio
        stage = "read_raster"
        with rasterio.open(raster_path) as src:
            if src.count != 1 or not np.issubdtype(np.dtype(src.dtypes[0]), np.integer):
                raise PatchValidationError("A single-band integer candidate raster is required.")
            if src.width * src.height > MAX_PIXELS:
                raise PatchValidationError("Raster exceeds bounded Slice 4 pixel limit.")
            if src.crs is None:
                raise PatchValidationError("Raster CRS is missing.")
            transform, crs, nodata = src.transform, src.crs, src.nodata
            _cell_area(transform, crs)
            masked = src.read(1, masked=True)
            valid = ~np.ma.getmaskarray(masked)
            values = np.asarray(masked.data)
            if values.size and (values.min() < np.iinfo(np.int32).min or values.max() > np.iinfo(np.int32).max):
                raise PatchValidationError("Raster values exceed supported int32 range.")
            data = values.astype("int32")
        stage = "validate_source_lineage"
        observed = _check_source(data, valid, nodata, transform, crs, doc, book)
        before_hashes = {"cover_type_tif": _digest(raster_path), "codebook_csv": _digest(book_path), "slice3_methods": _digest(methods_path)}
        stage = "polygonize"
        frame = _build_frame(data, valid, transform, crs, book, doc)
        qc = _polygon_qc(frame, data, valid, transform, observed)
        warnings = list(doc.get("warnings", []))
        if "unmapped_evt" in frame.output_label.tolist():
            warnings.append("Unmapped valid EVT category retained as polygons for review.")
        warnings.append("Review flags and class_source_evt_codes are class-level associations, not measured per-patch source evidence.")
        stage = "write_outputs"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        run_dir = root / f"rawpatch_{prefix.removeprefix('cmap_')}_{stamp}_{uuid.uuid4().hex[:6]}"
        run_dir.mkdir(exist_ok=False)
        gpkg = run_dir / "raw_cover_type_patches.gpkg"
        summary_path = run_dir / "raw_patch_acreage.csv"
        qc_path = run_dir / "raw_patch_qc.json"
        instructions = run_dir / "OPEN_IN_ARCGIS_PRO.txt"
        frame["source_raster"] = raster_path.name
        frame["source_methods"] = methods_path.name
        frame["provenance_reference"] = qc_path.name
        frame.to_file(gpkg, layer=LAYER, driver="GPKG", engine="pyogrio", index=False)
        stage = "verify_geopackage"
        actual = gpd.read_file(gpkg, layer=LAYER, engine="pyogrio")
        _readback(frame, actual, crs)
        _polygon_qc(actual, data, valid, transform, observed)
        qc["geopackage_readback_passed"] = True
        qc["input_files_unchanged"] = before_hashes == {"cover_type_tif": _digest(raster_path), "codebook_csv": _digest(book_path), "slice3_methods": _digest(methods_path)}
        if not qc["input_files_unchanged"]:
            raise PatchValidationError("An input changed during processing; do not accept this run.")
        stage = "write_reports"
        with summary_path.open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(qc["per_class"][0]))
            writer.writeheader()
            writer.writerows(qc["per_class"])
        artifacts = {"geopackage": str(gpkg), "layer": LAYER, "acreage_csv": str(summary_path), "qc_json": str(qc_path), "opening_instructions": str(instructions)}
        report = {"document_type": "candidate_cover_type_raw_patch_qc", "status": "complete_review_required",
                  "created_at_utc": datetime.now(timezone.utc).isoformat(), "runtime_seconds": time.perf_counter()-started,
                  "candidate_polygons_produced": True, "candidate_stands_produced": False,
                  "new_classification_performed": False, "connectivity": 4, "smoothing": False,
                  "small_patch_removal": False, "minimum_mapping_unit_applied": False,
                  "patch_count": len(frame), "arcgis_pro_review_performed": False,
                  "source_methods_filename": methods_path.name, "source_raster_filename": raster_path.name,
                  "source_sha256": before_hashes, "job_id": doc["job_id"],
                  "crosswalk_id": doc["crosswalk_id"], "crosswalk_version": doc["crosswalk_version"],
                  "cover_scheme_id": doc["cover_scheme_id"], "cover_scheme_version": doc["cover_scheme_version"],
                  "crosswalk_approval_note": doc["crosswalk_approval_note"],
                  "evt_add_url": doc.get("evt_add_url"), "evt_add_sha256": doc.get("evt_add_sha256"),
                  "raster_shape": list(data.shape), "raster_transform": list(transform)[:6], "crs": crs.to_string(),
                  "nodata_policy": "NoData excluded from cover-type polygons, retained as holes/gaps and separately counted in QC; no filling or merging.",
                  "review_flag_policy": "Conservative union of approved class-level requirements; not evidence that every patch contains every listed source EVT code.",
                  "warnings": warnings, "qc": qc, "artifacts": artifacts,
                  "processing_limits": {"max_pixels": MAX_PIXELS, "max_patches": MAX_PATCHES},
                  "software": {"rasterio": rasterio.__version__, "geopandas": gpd.__version__, "numpy": np.__version__},
                  "limitations": ["Raw patches are not stands or generalized review units.", "Preliminary mapping; not field inventory, Tribal approval, legal status, or management authority.", "Source EVT/EVC/EVH measurements are not recomputed per patch in this slice."]}
        instructions.write_text(
            "In ArcGIS Pro, add raw_cover_type_patches.gpkg and select candidate_cover_type_raw_patches.\n"
            "Symbolize this ONE layer using Unique Values on output_label or candidate_code.\n"
            "Open the attribute table for area_acres, forest_land_status and review_flags.\n"
            "Compare with the unchanged Slice 3 cover-type TIFF. Raw stair-step edges are intentional.\n"
            "Do not treat patches as stands. No smoothing, removal or 1-hectare generalization occurred.\n"
            "NoData is excluded from candidate polygons and separately accounted for in raw_patch_qc.json.\n"
            "Record your ArcGIS Pro review separately; this script does not perform it.\n", encoding="utf-8")
        with qc_path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
        return RawPatchResult(status="complete_review_required", stage="complete", candidate_polygons_produced=True,
                              patch_count=len(frame), warnings=warnings, artifacts=artifacts, qc=qc)
    except Exception as exc:
        errors = [f"{type(exc).__name__}: {exc}"]
        artifacts = {}
        if run_dir is not None:
            artifacts["incomplete_run_directory"] = str(run_dir)
            failure = run_dir / "FAILED_DO_NOT_USE.json"
            try:
                with failure.open("x", encoding="utf-8") as stream:
                    json.dump({"status": "failed", "stage": stage, "errors": errors,
                               "candidate_polygons_produced": False, "accept_outputs": False}, stream, indent=2)
                artifacts["failure_report"] = str(failure)
            except OSError as write_error:
                errors.append(f"Failure report write failed: {write_error}")
        return RawPatchResult(status="failed", stage=stage, errors=errors, artifacts=artifacts)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Create Slice 4 raw patches from existing Slice 3 outputs.")
    parser.add_argument("methods_filename", help="Simple Slice 3 methods JSON filename in outputs/.")
    args = parser.parse_args()
    req = RawPatchRequest(methods_filename=args.methods_filename)
    result = create_raw_cover_type_patches(Path(__file__).resolve().parent / "outputs", req)
    print(result.model_dump_json(indent=2))
    raise SystemExit(0 if result.status == "complete_review_required" else 1)
