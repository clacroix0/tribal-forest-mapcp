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
import pandas as pd
import shapely
from pandas.api.types import is_numeric_dtype
from pydantic import BaseModel, ConfigDict, Field
from pyproj import CRS
from shapely import union_all

METHOD_VERSION = "anchor_inclusions_v1"
LAYER = "candidate_cover_type_generalized"
RAW_LAYER = "candidate_cover_type_raw_patches"
ACRE_M2 = 4046.8564224
MAX_PATCHES = 200_000
MAX_COMPARISONS = 200_000
MAX_METADATA_BYTES = 5_000_000
MAX_GPKG_BYTES = 200_000_000
EDGE_TOLERANCE_M = 1e-8
AREA_TIE_TOLERANCE_M2 = 1e-8
BLOCKING_FLAGS = frozenset({
    "riparian_feature_preserved", "source_evt_code_unknown",
    "source_evt_code_unmapped", "evt_structure_conflict",
    "evc_evh_structure_conflict", "possible_disturbance_or_source_date_mismatch",
    "mixed_conflicting", "candidate_uncertain", "known_disturbance_feature",
})
REQUIRED_COLUMNS = frozenset({
    "patch_id", "output_code", "output_label", "forest_land_status",
    "area_m2", "area_acres", "review_flags", "geometry",
})
PROVENANCE_COLUMNS = (
    "crosswalk_id", "crosswalk_version", "cover_scheme_id", "cover_scheme_version",
)
LIMITATIONS = [
    "Preliminary review units, not stands, field inventory, or management authority.",
    "Display labels follow original anchors; original-class acreage comes from composition, not display labels.",
    "Hard boundaries were not evaluated; this version accepts no barrier data.",
    "Disturbance history was not evaluated; known flagged features are protected only where supplied in raw attributes.",
    "Class-level flags are not measured per-patch vegetation evidence.",
    "Small-only groups and patches without an eligible original anchor remain separate.",
]


class GeneralizationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    small_patch_threshold_m2: float = Field(default=10_000.0, gt=0)
    eligible_source_labels: list[Literal["candidate_P", "candidate_PJ"]] = Field(
        default_factory=lambda: ["candidate_P", "candidate_PJ"], min_length=1, max_length=2
    )
    compatibility_rule: Literal["approved_mescalero_P_PJ_trial"] = "approved_mescalero_P_PJ_trial"
    recipient_policy: Literal["original_patches_at_or_above_threshold"] = "original_patches_at_or_above_threshold"
    recipient_strategy: Literal["longest_shared_boundary"] = "longest_shared_boundary"
    excluded_patch_ids: list[str] = Field(default_factory=list, max_length=MAX_PATCHES)
    additional_protected_patch_ids: list[str] = Field(default_factory=list, max_length=MAX_PATCHES)


class GeneralizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    raw_run_directory: str = Field(
        pattern=r"^rawpatch_[A-Za-z0-9_-]+$",
        max_length=240,
    )

    expected_cover_scheme_id: str = Field(
        default="mescalero_v1",
        pattern=r"^[A-Za-z0-9_-]+$",
        max_length=120,
    )

    settings: GeneralizationSettings = Field(
        default_factory=GeneralizationSettings,
    )


class GeneralizationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["complete_review_required", "failed"]
    stage: str
    candidate_generalized_polygons_produced: bool = False
    candidate_stands_produced: bool = False
    new_classification_performed: bool = False
    raw_patch_count: int = 0
    review_unit_count: int = 0
    merged_patch_count: int = 0
    artifacts: dict[str, str] = Field(default_factory=dict)
    qc: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class GeneralizationValidationError(ValueError):
    pass


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _controlled_file(folder: Path, name: str, limit: int) -> Path:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise GeneralizationValidationError("Expected a simple controlled filename.")
    path = (folder / name).resolve()
    if path.parent != folder.resolve() or not path.is_file():
        raise GeneralizationValidationError(f"Missing or unsafe input: {name}")
    if path.stat().st_size > limit:
        raise GeneralizationValidationError(f"Input exceeds size limit: {name}")
    return path


def _flags(value) -> set[str]:
    if not isinstance(value, str):
        raise GeneralizationValidationError("review_flags must be strings, not nulls.")
    return {flag for flag in value.split("|") if flag}


def _validate_frame(frame: gpd.GeoDataFrame, settings: GeneralizationSettings):
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise GeneralizationValidationError(f"Missing raw fields: {sorted(missing)}")
    if frame.empty or len(frame) > MAX_PATCHES:
        raise GeneralizationValidationError("Empty raw layer or patch limit exceeded.")
    if frame.crs is None or CRS.from_user_input(frame.crs).to_epsg() != 5070:
        raise GeneralizationValidationError("Version 1 requires EPSG:5070; no reprojection is performed.")
    ids = frame.patch_id.tolist()
    if any(not isinstance(v, str) or not re.fullmatch(r"CTP_[0-9]{6}", v) for v in ids):
        raise GeneralizationValidationError("Invalid raw patch ID.")
    if len(set(ids)) != len(ids):
        raise GeneralizationValidationError("Duplicate raw patch IDs.")
    if (frame.geometry.isna().any() or frame.geometry.is_empty.any()
            or not frame.geometry.is_valid.all()
            or set(frame.geometry.geom_type) != {"Polygon"}):
        raise GeneralizationValidationError("Raw geometries must be valid nonempty Polygons; no repair is performed.")
    for column in ("area_m2", "area_acres", "output_code"):
        if not is_numeric_dtype(frame[column]) or not np.isfinite(frame[column].to_numpy()).all():
            raise GeneralizationValidationError(f"Invalid numeric field: {column}")
    if not np.equal(frame.output_code, np.floor(frame.output_code)).all():
        raise GeneralizationValidationError("Output codes must be integers.")
    if not np.allclose(frame.area_m2, frame.geometry.area, rtol=1e-9, atol=0.01):
        raise GeneralizationValidationError("Raw area attributes disagree with geometry.")
    if not np.allclose(frame.area_acres, frame.geometry.area / ACRE_M2, rtol=1e-9, atol=1e-8):
        raise GeneralizationValidationError("Raw acreage attributes disagree with geometry.")
    if not frame.forest_land_status.isin(["forest_land", "nonforest", "unknown"]).all():
        raise GeneralizationValidationError("Invalid forest-land status.")
    if any(not isinstance(label, str) or not label for label in frame.output_label):
        raise GeneralizationValidationError("Invalid output labels.")
    for _, group in frame.groupby("output_code"):
        if group.output_label.nunique() != 1 or group.forest_land_status.nunique() != 1:
            raise GeneralizationValidationError("Inconsistent class labels or forest-land status.")
    for label in ("candidate_P", "candidate_PJ"):
        subset = frame[frame.output_label == label]
        if len(subset) and (subset.output_code.nunique() != 1 or not (subset.forest_land_status == "forest_land").all()):
            raise GeneralizationValidationError("P/PJ must each have one code and forest-land status.")
    if len(set(settings.eligible_source_labels)) != len(settings.eligible_source_labels):
        raise GeneralizationValidationError("Duplicate eligible source labels.")
    for values in (settings.excluded_patch_ids, settings.additional_protected_patch_ids):
        if len(values) != len(set(values)) or set(values) - set(ids):
            raise GeneralizationValidationError("Duplicate or unknown excluded/protected patch IDs.")
    flags = [_flags(v) for v in frame.review_flags]
    areas = frame.geometry.area.to_numpy()
    if np.any(areas <= 0):
        raise GeneralizationValidationError("Polygon areas must be positive.")
    footprint = union_all(frame.geometry.to_numpy())
    tolerance = max(0.01, float(areas.sum()) * 1e-9)
    overlap = max(0.0, float(areas.sum() - footprint.area))
    if overlap > tolerance:
        raise GeneralizationValidationError("Raw layer has overlapping polygon area.")
    return flags, areas, footprint, tolerance


def generalize_frame(frame: gpd.GeoDataFrame, settings: GeneralizationSettings):
    """Pure, bounded geometry operation; writes no files. Returns units, membership, composition, QC."""
    frame = frame.sort_values("patch_id").reset_index(drop=True).copy()
    flags, areas, original_footprint, tolerance = _validate_frame(frame, settings)
    ids = frame.patch_id.tolist()
    protected_ids = set(settings.additional_protected_patch_ids)
    excluded_ids = set(settings.excluded_patch_ids)
    protected = [bool(v & BLOCKING_FLAGS) or ids[i] in protected_ids for i, v in enumerate(flags)]
    compatible = frame.output_label.isin(["candidate_P", "candidate_PJ"]).to_numpy()
    anchors = {
        i for i in range(len(frame))
        if compatible[i] and areas[i] >= settings.small_patch_threshold_m2
        and not protected[i] and ids[i] not in excluded_ids
    }
    recipients = list(range(len(frame)))
    reasons = [""] * len(frame)
    shared_lengths = [0.0] * len(frame)
    comparisons = 0
    index = frame.sindex
    for i in range(len(frame)):
        if ids[i] in excluded_ids:
            reasons[i] = "explicitly_excluded"
        elif protected[i]:
            reasons[i] = "protected"
        elif frame.output_label.iloc[i] not in settings.eligible_source_labels:
            reasons[i] = "source_class_not_eligible"
        elif areas[i] >= settings.small_patch_threshold_m2:
            reasons[i] = "at_or_above_threshold"
        else:
            candidates = []
            geom = frame.geometry.iloc[i]
            for j in sorted(set(int(v) for v in index.query(geom, predicate="intersects")) & anchors):
                comparisons += 1
                if comparisons > MAX_COMPARISONS:
                    raise GeneralizationValidationError("Adjacency comparison limit exceeded.")
                length = float(geom.boundary.intersection(frame.geometry.iloc[j].boundary).length)
                if length > EDGE_TOLERANCE_M:
                    candidates.append((j, length))
            if not candidates:
                reasons[i] = "no_eligible_edge_sharing_anchor"
                continue
            maximum = max(length for _, length in candidates)
            tied = [(j, length) for j, length in candidates if maximum - length <= EDGE_TOLERANCE_M]
            largest = max(areas[j] for j, _ in tied)
            tied = [(j, length) for j, length in tied if largest - areas[j] <= AREA_TIE_TOLERANCE_M2]
            chosen, length = min(tied, key=lambda pair: ids[pair[0]])
            recipients[i] = chosen
            shared_lengths[i] = length
            reasons[i] = "merged_inclusion"
    groups = {}
    for i, recipient in enumerate(recipients):
        groups.setdefault(recipient, []).append(i)
    unit_records, membership, composition = [], [], []
    for anchor, members in sorted(groups.items(), key=lambda pair: ids[pair[0]]):
        unit_id = "CTG_" + ids[anchor].removeprefix("CTP_")
        geom = union_all(frame.geometry.iloc[members].to_numpy())
        if geom.geom_type != "Polygon" or geom.is_empty or not geom.is_valid:
            raise GeneralizationValidationError("Grouped unit is not a valid connected Polygon.")
        total = float(sum(areas[i] for i in members))
        if not math.isclose(geom.area, total, rel_tol=1e-9, abs_tol=0.01):
            raise GeneralizationValidationError("Unit area does not match member areas.")
        anchor_row = frame.iloc[anchor]
        labels = {frame.output_label.iloc[i] for i in members}
        all_flags = set().union(*(flags[i] for i in members))
        if len(labels) > 1:
            all_flags.add("generalized_unit_contains_multiple_original_classes")
        record = {
            "review_unit_id": unit_id, "anchor_patch_id": ids[anchor],
            "display_output_code": int(anchor_row.output_code),
            "display_output_label": anchor_row.output_label,
            "display_label_basis": "anchor_original_class" if len(members) > 1 else "original_patch_class",
            "forest_land_status": anchor_row.forest_land_status,
            "contains_multiple_classes": len(labels) > 1,
            "member_patch_count": len(members), "inclusion_count": len(members) - 1,
            "area_m2": float(geom.area), "area_acres": float(geom.area / ACRE_M2),
            "review_flags": "|".join(sorted(all_flags)),
            "geometry_stage": "generalized_review", "method_version": METHOD_VERSION,
            "geometry": geom,
        }
        for col in PROVENANCE_COLUMNS:
            if col in frame:
                if frame.iloc[members][col].nunique(dropna=False) != 1:
                    raise GeneralizationValidationError(f"Inconsistent unit provenance: {col}")
                record[col] = anchor_row[col]
        unit_records.append(record)
        for i in members:
            membership.append({
                "patch_id": ids[i], "review_unit_id": unit_id, "anchor_patch_id": ids[anchor],
                "role": "inclusion" if i != anchor else "anchor" if len(members) > 1 else "standalone",
                "reason": reasons[i], "original_output_code": int(frame.output_code.iloc[i]),
                "original_output_label": frame.output_label.iloc[i],
                "forest_land_status": frame.forest_land_status.iloc[i],
                "original_area_m2": float(areas[i]), "original_area_acres": float(areas[i] / ACRE_M2),
                "shared_boundary_with_anchor_m": float(shared_lengths[i]),
                "original_review_flags": frame.review_flags.iloc[i],
            })
        for code in sorted({int(frame.output_code.iloc[i]) for i in members}):
            subset = [i for i in members if int(frame.output_code.iloc[i]) == code]
            area = float(sum(areas[i] for i in subset))
            composition.append({
                "review_unit_id": unit_id, "original_output_code": code,
                "original_output_label": frame.output_label.iloc[subset[0]],
                "forest_land_status": frame.forest_land_status.iloc[subset[0]],
                "patch_count": len(subset), "area_m2": area, "area_acres": area / ACRE_M2,
                "fraction_of_unit": area / total, "percent_of_unit": 100.0 * area / total,
            })
    units = gpd.GeoDataFrame(unit_records, geometry="geometry", crs=frame.crs)
    membership = pd.DataFrame(membership).sort_values("patch_id").reset_index(drop=True)
    composition = pd.DataFrame(composition).sort_values(["review_unit_id", "original_output_code"]).reset_index(drop=True)
    if membership.patch_id.duplicated().any() or set(membership.patch_id) != set(ids):
        raise GeneralizationValidationError("Patch membership is incomplete or duplicated.")
    output_footprint = union_all(units.geometry.to_numpy())
    gap = float(original_footprint.difference(output_footprint).area)
    extra = float(output_footprint.difference(original_footprint).area)
    overlap = max(0.0, float(units.geometry.area.sum() - output_footprint.area))
    if max(gap, extra, overlap) > tolerance:
        raise GeneralizationValidationError("Generalized footprint overlap/gap/coverage QC failed.")
    per_class = []
    for code, subset in frame.groupby("output_code", sort=True):
        before = float(subset.geometry.area.sum())
        after = float(composition.loc[composition.original_output_code == code, "area_m2"].sum())
        if not math.isclose(before, after, rel_tol=1e-9, abs_tol=0.01):
            raise GeneralizationValidationError("Original class acreage was not preserved.")
        per_class.append({"output_code": int(code), "output_label": subset.output_label.iloc[0],
                          "raw_area_m2": before, "composition_area_m2": after, "acres": after / ACRE_M2})
    composition_totals = {
        unit_id: (rows.area_m2.sum(), rows.fraction_of_unit.sum())
        for unit_id, rows in composition.groupby("review_unit_id", sort=False)
    }
    for unit in units.itertuples():
        area_total, fraction_total = composition_totals.get(unit.review_unit_id, (0.0, 0.0))
        if not math.isclose(area_total, unit.area_m2, rel_tol=1e-9, abs_tol=0.01) or not math.isclose(fraction_total, 1.0, abs_tol=1e-9):
            raise GeneralizationValidationError("Unit composition closure failed.")
    if any(recipients[i] != i for i in range(len(frame)) if protected[i] or ids[i] in excluded_ids):
        raise GeneralizationValidationError("Protected or excluded patch was absorbed.")
    merged = int((membership.role == "inclusion").sum())
    qc = {
        "geometry_valid": True, "membership_complete_unique": True,
        "original_class_area_preserved": True, "unit_composition_closure_passed": True,
        "protected_patches_preserved": True, "raw_patch_count": len(frame),
        "review_unit_count": len(units), "merged_patch_count": merged,
        "polygon_count_reduction": len(frame) - len(units),
        "valid_area_m2": float(units.geometry.area.sum()),
        "valid_acres": float(units.geometry.area.sum() / ACRE_M2),
        "gap_m2": gap, "extra_coverage_m2": extra, "overlap_m2": overlap,
        "area_tolerance_m2": tolerance, "adjacency_comparisons": comparisons,
        "edge_tolerance_m": EDGE_TOLERANCE_M,
        "area_tie_tolerance_m2": AREA_TIE_TOLERANCE_M2,
        "hard_boundaries_evaluated": False, "disturbance_history_evaluated": False,
        "unmerged_reason_counts": {str(k): int(v) for k, v in membership.loc[membership.role == "standalone", "reason"].value_counts().items()},
        "per_original_class": per_class,
    }
    return units, membership, composition, qc


def _readback(expected, actual):
    if len(expected) != len(actual) or actual.crs is None or CRS.from_user_input(actual.crs) != CRS.from_user_input(expected.crs):
        raise GeneralizationValidationError("GeoPackage read-back count/CRS failed.")
    if set(expected.columns) - set(actual.columns):
        raise GeneralizationValidationError("GeoPackage lost attributes.")
    left = expected.sort_values("review_unit_id").reset_index(drop=True)
    right = actual.sort_values("review_unit_id").reset_index(drop=True)
    if right.review_unit_id.duplicated().any():
        raise GeneralizationValidationError("Read-back duplicate unit IDs.")
    for col in left.columns:
        if col == "geometry":
            if not all(a.equals(b) for a, b in zip(left.geometry, right.geometry)):
                raise GeneralizationValidationError("GeoPackage changed geometry.")
        elif is_numeric_dtype(left[col]):
            if not np.allclose(left[col], right[col], rtol=1e-9, atol=1e-8):
                raise GeneralizationValidationError(f"GeoPackage changed numeric attribute: {col}")
        elif left[col].fillna("").astype(str).tolist() != right[col].fillna("").astype(str).tolist():
            raise GeneralizationValidationError(f"GeoPackage changed attribute: {col}")


def _write_csv(path, frame):
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(frame.columns))
        writer.writeheader()
        writer.writerows(frame.to_dict(orient="records"))
    actual = pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)
    if list(actual.columns) != list(frame.columns) or len(actual) != len(frame):
        raise GeneralizationValidationError("CSV read-back schema/count failed.")
    for col in frame:
        if is_numeric_dtype(frame[col]):
            if not np.allclose(frame[col], pd.to_numeric(actual[col]), rtol=1e-9, atol=1e-8):
                raise GeneralizationValidationError("CSV numeric read-back failed.")
        elif frame[col].astype(str).tolist() != actual[col].astype(str).tolist():
            raise GeneralizationValidationError("CSV text read-back failed.")


def create_generalized_cover_type_patches(outputs_root: Path, request: GeneralizationRequest) -> GeneralizationResult:
    """Read controlled successful raw outputs; preserve baseline; write an isolated review run.

    This function does not authenticate human approval. The calling application must
    obtain approval for the exact settings before a consequential tool invocation.
    """
    started = time.perf_counter()
    stage = "validate_raw_run"
    run_dir = None
    try:
        root = Path(outputs_root).resolve()
        raw_dir = (root / request.raw_run_directory).resolve()
        if raw_dir.parent != root or not raw_dir.is_dir():
            raise GeneralizationValidationError("Raw run must be a direct controlled outputs subfolder.")
        if (raw_dir / "FAILED_DO_NOT_USE.json").exists():
            raise GeneralizationValidationError("Raw run is marked failed.")
        qc_path = _controlled_file(raw_dir, "raw_patch_qc.json", MAX_METADATA_BYTES)
        gpkg = _controlled_file(raw_dir, "raw_cover_type_patches.gpkg", MAX_GPKG_BYTES)
        report = json.loads(qc_path.read_text(encoding="utf-8-sig"))
        if not isinstance(report, dict):
            raise GeneralizationValidationError("Raw QC must be an object.")
        if report.get("cover_scheme_id") != request.expected_cover_scheme_id:
            raise GeneralizationValidationError(
                "Raw cover scheme differs from the explicitly selected scheme."
            )
        if (report.get("document_type") != "candidate_cover_type_raw_patch_qc"
                or report.get("status") != "complete_review_required"
                or report.get("candidate_polygons_produced") is not True
                or report.get("candidate_stands_produced") is not False
                or report.get("new_classification_performed") is not False
                or report.get("connectivity") != 4):
            raise GeneralizationValidationError("Raw QC does not identify a successful four-neighbor raw run.")
        for key in ("geometry_valid", "raster_roundtrip_matches", "per_class_closure_matches", "geopackage_readback_passed", "input_files_unchanged"):
            if report.get("qc", {}).get(key) is not True:
                raise GeneralizationValidationError(f"Raw QC check is not true: {key}")
        tracked = {"raw_geopackage": gpkg, "raw_qc": qc_path}
        source_names = {
            "cover_type_tif": report.get("source_raster_filename"),
            "slice3_methods": report.get("source_methods_filename"),
        }
        methods_name = source_names["slice3_methods"]
        if not isinstance(methods_name, str) or not methods_name.endswith("_methods.json"):
            raise GeneralizationValidationError("Invalid original methods filename.")
        source_names["codebook_csv"] = methods_name.removesuffix("_methods.json") + "_cover_type_codebook.csv"
        for key, name in source_names.items():
            source = _controlled_file(root, name, MAX_GPKG_BYTES if key == "cover_type_tif" else MAX_METADATA_BYTES)
            if _digest(source) != report.get("source_sha256", {}).get(key):
                raise GeneralizationValidationError(f"Original input hash changed: {key}")
            tracked[key] = source
        before_hashes = {key: _digest(path) for key, path in tracked.items()}
        stage = "read_validate_raw_patches"
        frame = gpd.read_file(gpkg, layer=RAW_LAYER, engine="pyogrio")
        if len(frame) != report.get("patch_count"):
            raise GeneralizationValidationError("Raw patch count differs from QC.")
        for col in PROVENANCE_COLUMNS:
            if col not in frame or not isinstance(report.get(col), str) or not (frame[col] == report[col]).all():
                raise GeneralizationValidationError(f"Raw provenance mismatch: {col}")
        if "geometry_stage" not in frame or not (frame.geometry_stage == "raw").all():
            raise GeneralizationValidationError("Expected raw geometry stage.")
        _validate_frame(frame, request.settings)
        expected_class = {int(row["output_code"]): row for row in report.get("qc", {}).get("per_class", [])}
        if set(expected_class) != set(int(v) for v in frame.output_code.unique()):
            raise GeneralizationValidationError("Raw QC class set mismatch.")
        for code, subset in frame.groupby("output_code"):
            row = expected_class[int(code)]
            if (row.get("output_label") != subset.output_label.iloc[0]
                    or row.get("forest_land_status") != subset.forest_land_status.iloc[0]
                    or row.get("patch_count") != len(subset)
                    or not math.isclose(float(row["square_meters"]), subset.geometry.area.sum(), rel_tol=1e-9, abs_tol=0.01)):
                raise GeneralizationValidationError("Raw QC class metadata/area mismatch.")
        stage = "generalize"
        units, membership, composition, qc = generalize_frame(frame, request.settings)
        if not math.isclose(qc["valid_area_m2"], float(report["qc"]["valid_area_m2"]), rel_tol=1e-9, abs_tol=0.01):
            raise GeneralizationValidationError("Raw QC total-area mismatch.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        run_dir = root / f"genpatch_{stamp}_{uuid.uuid4().hex[:8]}"
        stage = "write_outputs"
        run_dir.mkdir(exist_ok=False)
        result_gpkg = run_dir / "generalized_cover_type_patches.gpkg"
        membership_path = run_dir / "patch_membership.csv"
        composition_path = run_dir / "unit_composition.csv"
        reasons_path = run_dir / "unmerged_patches.csv"
        summary_path = run_dir / "original_class_acreage.csv"
        methods_path = run_dir / "generalization_qc.json"
        instructions = run_dir / "OPEN_IN_ARCGIS_PRO.txt"
        units["source_raw_run"] = request.raw_run_directory
        units["provenance_reference"] = methods_path.name
        units.to_file(result_gpkg, layer=LAYER, driver="GPKG", engine="pyogrio", index=False)
        stage = "verify_outputs"
        actual = gpd.read_file(result_gpkg, layer=LAYER, engine="pyogrio")
        _readback(units, actual)
        _write_csv(membership_path, membership)
        _write_csv(composition_path, composition)
        _write_csv(reasons_path, membership[membership.role == "standalone"].copy())
        _write_csv(summary_path, pd.DataFrame(qc["per_original_class"]))
        qc["geopackage_readback_passed"] = True
        qc["csv_readback_passed"] = True
        qc["input_files_unchanged"] = before_hashes == {key: _digest(path) for key, path in tracked.items()}
        if not qc["input_files_unchanged"]:
            raise GeneralizationValidationError("An input changed during processing.")
        qc["source_nodata_cells"] = report["qc"].get("nodata_cells")
        qc["source_nodata_acres"] = report["qc"].get("nodata_acres")
        instructions.write_text(
            "Add generalized_cover_type_patches.gpkg in ArcGIS Pro.\n"
            f"Layer: {LAYER}\n"
            "Symbolize display_output_label; inspect contains_multiple_classes.\n"
            "Join patch_membership.csv to the original raw layer using patch_id.\n"
            "Relate unit_composition.csv using review_unit_id.\n"
            "Display labels do not replace original class composition or acreage.\n"
            "Compare the unchanged raw patches and classified raster.\n"
            "NoData holes remain; small protected and unmergeable patches remain.\n"
            "Hard boundaries and disturbance history were NOT evaluated.\n"
            "These are preliminary review units, not stands. Record professional review separately.\n",
            encoding="utf-8",
        )
        artifacts = {"geopackage": str(result_gpkg), "layer": LAYER,
                     "membership_csv": str(membership_path), "composition_csv": str(composition_path),
                     "unmerged_csv": str(reasons_path), "original_class_acreage_csv": str(summary_path),
                     "qc_json": str(methods_path), "opening_instructions": str(instructions)}
        output_hashes = {p.name: _digest(p) for p in (result_gpkg, membership_path, composition_path, reasons_path, summary_path, instructions)}
        final_report = {
            "document_type": "candidate_cover_type_generalization_qc",
            "status": "complete_review_required", "method_version": METHOD_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "runtime_seconds": time.perf_counter() - started,
            "settings": request.settings.model_dump(),
            "expected_cover_scheme_id": request.expected_cover_scheme_id,
            "scope": "approved Mescalero P/PJ trial only; not generic class onboarding",
            "source_raw_run_directory": request.raw_run_directory,
            "source_sha256": before_hashes, "output_sha256": output_hashes,
            "source_artifacts": {key: str(path) for key, path in tracked.items()},
            "blocking_flags": sorted(BLOCKING_FLAGS),
            "candidate_generalized_polygons_produced": True,
            "candidate_stands_produced": False, "new_classification_performed": False,
            "arcgis_pro_review_performed": False,
            "human_approval_verified_by_module": False,
            "approval_note": "The caller must obtain approval of exact settings; this module does not authenticate approval.",
            "qc": qc, "artifacts": artifacts, "limitations": LIMITATIONS,
            "software": {"geopandas": gpd.__version__, "shapely": shapely.__version__, "numpy": np.__version__},
            "processing_limits": {"max_patches": MAX_PATCHES, "max_adjacency_comparisons": MAX_COMPARISONS},
        }
        for col in PROVENANCE_COLUMNS:
            final_report[col] = report[col]
        stage = "write_report"
        with methods_path.open("x", encoding="utf-8") as stream:
            json.dump(final_report, stream, indent=2, allow_nan=False)
        return GeneralizationResult(
            status="complete_review_required", stage="complete",
            candidate_generalized_polygons_produced=True,
            raw_patch_count=qc["raw_patch_count"], review_unit_count=qc["review_unit_count"],
            merged_patch_count=qc["merged_patch_count"], artifacts=artifacts, qc=qc,
            warnings=list(LIMITATIONS),
        )
    except Exception as exc:
        errors = [f"{type(exc).__name__}: {exc}"]
        artifacts = {}
        if run_dir is not None and run_dir.is_dir():
            artifacts["incomplete_run_directory"] = str(run_dir)
            failure = run_dir / "FAILED_DO_NOT_USE.json"
            try:
                with failure.open("x", encoding="utf-8") as stream:
                    json.dump({"status": "failed", "stage": stage, "errors": errors, "accept_outputs": False}, stream, indent=2)
                artifacts["failure_report"] = str(failure)
            except OSError as write_error:
                errors.append(f"Failure marker write failed: {write_error}")
        return GeneralizationResult(status="failed", stage=stage, errors=errors, artifacts=artifacts)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generalize an approved raw Mescalero P/PJ sample; preserve baseline.")
    parser.add_argument("raw_run_directory", help="Raw run subfolder name inside outputs, not a path.")
    parser.add_argument("--threshold-m2", type=float, default=10_000.0)
    parser.add_argument("--exclude", nargs="*", default=[])
    parser.add_argument("--protect", nargs="*", default=[])
    args = parser.parse_args()
    request = GeneralizationRequest(
        raw_run_directory=args.raw_run_directory,
        settings=GeneralizationSettings(small_patch_threshold_m2=args.threshold_m2,
                                       excluded_patch_ids=args.exclude,
                                       additional_protected_patch_ids=args.protect),
    )
    result = create_generalized_cover_type_patches(Path(__file__).resolve().parent / "outputs", request)
    print(result.model_dump_json(indent=2))
    raise SystemExit(0 if result.status == "complete_review_required" else 1)
