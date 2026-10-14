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
from pydantic import BaseModel, ConfigDict, Field

ACRE_M2 = 4046.8564224
NODATA = -9999
FL_TRUE, FL_FALSE, FL_UNKNOWN = 1, 0, 2
OUTPUT_EPSG = 5070
EXPECTED_BANDS = ["LF2025_EVT_CONUS", "LF2025_EVC_CONUS", "LF2025_EVH_CONUS"]
MAX_JSON_BYTES = 5_000_000
MAX_PIXELS = 25_000_000
CROSSWALK_REQUIRED = {"crosswalk_id", "crosswalk_version", "cover_scheme_id", "cover_scheme_version", "entries",
                      "output_code_table", "nodata_value", "unmapped_valid_output_code", "crosswalk_approval_note"}


class MappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    acquisition_directory: str = Field(pattern=r"^bacq_[A-Za-z0-9_-]+$", max_length=120)
    crosswalk_filename: str = Field(default="mescalero_v1_evt_crosswalk_v2.json", pattern=r"^[A-Za-z0-9_-]+\.json$", max_length=120)
    small_patch_threshold_m2: float = Field(default=10_000.0, gt=0, le=1e9, allow_inf_nan=False)


class CreateMappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    acquisition_directory: str = Field(pattern=r"^bacq_[A-Za-z0-9_-]+$", max_length=120)
    preview_directory: str = Field(pattern=r"^mapdry_[A-Za-z0-9_-]+$", max_length=120)
    crosswalk_filename: str = Field(default="mescalero_v1_evt_crosswalk_v2.json", pattern=r"^[A-Za-z0-9_-]+\.json$", max_length=120)


class MappingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: str
    stage: str
    summary: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)


class MappingError(ValueError):
    pass


# --- generic helpers --------------------------------------------------------------------------
def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _direct_dir(root: Path, name: str) -> Path:
    directory = (Path(root).resolve() / name).resolve()
    if directory.parent != Path(root).resolve() or not directory.is_dir():
        raise MappingError("Directory must be an existing direct subfolder of outputs.")
    return directory


def _direct_file(directory: Path, name: str, limit: int = MAX_JSON_BYTES) -> Path:
    path = (Path(directory) / name).resolve()
    if path.parent != Path(directory).resolve() or not path.is_file():
        raise MappingError(f"Missing or escaping file: {name}")
    if path.stat().st_size > limit:
        raise MappingError(f"File exceeds size limit: {name}")
    return path


def _read_json(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise MappingError("Expected a JSON object.")
    return value


def _write_json(path: Path, value: dict) -> None:
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def _fail(stage: str, exc: Exception | str) -> MappingResult:
    text = f"{type(exc).__name__}: {exc}" if isinstance(exc, Exception) else exc
    return MappingResult(status="failed", stage=stage, errors=[text])


# --- crosswalk ---------------------------------------------------------------------------------
def load_crosswalk(project_data_root: Path, name: str) -> tuple[dict, str]:
    root = (Path(project_data_root) / "crosswalks").resolve()
    path = (root / name).resolve()
    if path.parent != root or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise MappingError("Crosswalk must be a direct file in project_data/crosswalks (max 5 MB).")
    data = _read_json(path)
    missing = CROSSWALK_REQUIRED - set(data)
    if missing:
        raise MappingError(f"Crosswalk missing required fields: {sorted(missing)}")
    if data.get("approved_by") != "user":
        raise MappingError("Crosswalk has no recorded user approval (approved_by must be 'user').")
    for key in ("crosswalk_approval_note", "crosswalk_id", "crosswalk_version", "cover_scheme_id", "cover_scheme_version"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise MappingError(f"Crosswalk field must be a non-empty string: {key}")
    table = data["output_code_table"]
    entries = data["entries"]
    if not isinstance(table, list) or not isinstance(entries, list) or not table or not entries:
        raise MappingError("Crosswalk tables must be non-empty lists.")
    codes = [row.get("output_code") for row in table]
    labels = [row.get("output_label") for row in table]
    if any(not isinstance(c, int) for c in codes) or len(set(codes)) != len(codes):
        raise MappingError("Output codes must be unique integers.")
    if any(not isinstance(l, str) or not l for l in labels) or len(set(labels)) != len(labels):
        raise MappingError("Output labels must be unique non-empty strings.")
    if data["nodata_value"] != NODATA or data["unmapped_valid_output_code"] not in codes:
        raise MappingError("Crosswalk NoData value must be -9999 and the unmapped code must be in the output table.")
    evt_codes = [e.get("evt_code") for e in entries]
    if any(not isinstance(c, int) for c in evt_codes) or len(set(evt_codes)) != len(evt_codes):
        raise MappingError("Entry EVT codes must be unique integers.")
    by_code = {row["output_code"]: row for row in table}
    for entry in entries:
        row = by_code.get(entry.get("output_code"))
        if row is None or row["output_label"] != entry.get("output_label") or row.get("candidate_forest_land") != entry.get("candidate_forest_land"):
            raise MappingError(f"Entry {entry.get('evt_code')} disagrees with the output code table.")
    for row in table:
        if row.get("candidate_forest_land") not in (True, False, None):
            raise MappingError("candidate_forest_land must be true, false or null.")
    return data, _digest(path)


# --- pure array logic (no raster library needed) ----------------------------------------------------
def classify_and_clip(evt: np.ndarray, inside: np.ndarray, crosswalk: dict) -> dict:
    if evt.shape != inside.shape or evt.ndim != 2:
        raise MappingError("EVT and boundary mask shapes differ.")
    table = {row["output_code"]: row for row in crosswalk["output_code_table"]}
    evt_to_out = {int(e["evt_code"]): int(e["output_code"]) for e in crosswalk["entries"]}
    unmapped = int(crosswalk["unmapped_valid_output_code"])
    fl_by_out = {code: (FL_TRUE if row.get("candidate_forest_land") is True else FL_FALSE if row.get("candidate_forest_land") is False else FL_UNKNOWN)
                 for code, row in table.items()}
    valid = inside & (evt != NODATA)
    out = np.full(evt.shape, NODATA, dtype=np.int32)
    fl = np.full(evt.shape, NODATA, dtype=np.int32)
    unique, inverse = np.unique(evt[valid], return_inverse=True)
    out_codes = np.array([evt_to_out.get(int(c), unmapped) for c in unique], dtype=np.int32)
    fl_codes = np.array([fl_by_out[int(c)] for c in out_codes], dtype=np.int32)
    if unique.size:
        out[valid] = out_codes[inverse]
        fl[valid] = fl_codes[inverse]
    unmapped_seen = [(int(c), int((evt[valid] == c).sum())) for c in unique if int(c) not in evt_to_out]
    return {"out": out, "fl": fl, "valid": valid, "unmapped_evt": unmapped_seen,
            "outside_cells": int((~inside).sum()), "evt_nodata_inside_cells": int((inside & (evt == NODATA)).sum()),
            "inside_cells": int(inside.sum()), "valid_cells": int(valid.sum()), "total_cells": int(evt.size)}


def class_stats(out: np.ndarray, valid: np.ndarray, crosswalk: dict, cell_area_m2: float) -> list[dict]:
    values, counts = np.unique(out[valid], return_counts=True)
    count_by = {int(v): int(n) for v, n in zip(values, counts)}
    rows, total = [], int(valid.sum())
    for row in crosswalk["output_code_table"]:
        code = row["output_code"]
        n = count_by.pop(code, 0)
        if code == NODATA or n == 0:
            continue
        rows.append({"output_code": code, "output_label": row["output_label"], "candidate_forest_land": row.get("candidate_forest_land"),
                     "cell_count": n, "square_meters": round(n * cell_area_m2, 2), "acres": round(n * cell_area_m2 / ACRE_M2, 4),
                     "fraction_of_valid": round(n / total, 6) if total else None})
    if count_by:
        raise MappingError(f"Classified raster contains codes outside the output table: {sorted(count_by)}")
    return rows


def component_sizes(values: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """4-connected components of equal values among valid cells. Returns (value per component, cells per component).

    Run-length union-find; the same connectivity rasterio.features.shapes(connectivity=4) uses, so counts
    equal the number of raw patches the raw-patch step will create from the same raster.
    """
    h, w = values.shape
    v = np.where(valid, values, np.int64(-2 ** 31)).astype(np.int64)
    flat = v.ravel()
    start = np.empty((h, w), dtype=bool)
    start[:, 0] = True
    start[:, 1:] = v[:, 1:] != v[:, :-1]
    starts = np.flatnonzero(start.ravel())
    ends = np.append(starts[1:], h * w)
    run_val = flat[starts]
    keep = valid.ravel()[starts]
    starts, ends, run_val = starts[keep], ends[keep], run_val[keep]
    n = starts.size
    if n == 0:
        return np.array([], dtype=np.int64), np.array([], dtype=np.int64)
    rows, cols = starts // w, starts % w
    c0, c1, length = cols, cols + (ends - starts), ends - starts
    ptr = np.searchsorted(rows, np.arange(h + 1))
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    rv, a0, a1 = run_val.tolist(), c0.tolist(), c1.tolist()
    ptrs = ptr.tolist()
    for r in range(h - 1):
        i, i_end, j, j_end = ptrs[r], ptrs[r + 1], ptrs[r + 1], ptrs[r + 2]
        while i < i_end and j < j_end:
            if rv[i] == rv[j] and a0[i] < a1[j] and a0[j] < a1[i]:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
            if a1[i] <= a1[j]:
                i += 1
            else:
                j += 1
    roots = np.array([find(i) for i in range(n)], dtype=np.int64)
    uniq, first, inverse = np.unique(roots, return_index=True, return_inverse=True)
    sizes = np.bincount(inverse, weights=length).astype(np.int64)
    return run_val[first], sizes


def patch_summary(out: np.ndarray, valid: np.ndarray, crosswalk: dict, cell_area_m2: float, threshold_m2: float,
                  eligible_labels=("candidate_P", "candidate_PJ")) -> dict:
    values, sizes = component_sizes(out, valid)
    label_of = {row["output_code"]: row["output_label"] for row in crosswalk["output_code_table"]}
    areas = sizes * cell_area_m2
    small = areas < threshold_m2
    per_class = {}
    for code in np.unique(values) if values.size else []:
        sel = values == code
        s = sizes[sel]
        per_class[label_of[int(code)]] = {"patches": int(sel.sum()), "cells": int(s.sum()), "median_cells": float(np.median(s)),
                                          "largest_cells": int(s.max()), "below_threshold": int((small & sel).sum())}
    eligible = int(sum(per_class.get(l, {}).get("below_threshold", 0) for l in eligible_labels))
    pct = {str(q): float(np.percentile(sizes, q)) for q in (50, 90, 99)} if sizes.size else {}
    return {"total_patches": int(values.size), "single_cell_patches": int((sizes == 1).sum()), "below_threshold_total": int(small.sum()),
            "below_threshold_p_pj": eligible, "threshold_m2": threshold_m2, "size_percentiles_cells": pct,
            "largest_patch_cells": int(sizes.max()) if sizes.size else 0, "by_class": per_class}


def forest_stats(fl: np.ndarray, valid: np.ndarray, cell_area_m2: float) -> list[dict]:
    names = {FL_TRUE: "candidate_forest_land_true", FL_FALSE: "candidate_forest_land_false", FL_UNKNOWN: "candidate_forest_land_unknown"}
    return [{"forest_land_code": code, "meaning": name, "cell_count": int((fl[valid] == code).sum()),
             "acres": round(int((fl[valid] == code).sum()) * cell_area_m2 / ACRE_M2, 4)} for code, name in names.items()]


# --- rasterio-dependent shell (requires rasterio; tested locally) -----------------------------------------
def _read_inputs(tif_path: Path, boundary_path: Path):
    import rasterio
    from rasterio.features import geometry_mask
    boundary = gpd.read_file(boundary_path, engine="pyogrio").to_crs(epsg=OUTPUT_EPSG)
    geometry = boundary.union_all() if hasattr(boundary, "union_all") else boundary.unary_union
    with rasterio.open(tif_path) as src:
        descriptions = [d.strip() if isinstance(d, str) else None for d in src.descriptions]
        if src.count != 3 or descriptions != EXPECTED_BANDS:
            raise MappingError(f"Unexpected bands: count={src.count}, descriptions={descriptions}")
        if src.crs is None or src.crs.to_epsg() != OUTPUT_EPSG:
            raise MappingError("Raster CRS must be EPSG:5070.")
        if not all(math.isclose(abs(r), 30.0, abs_tol=0.01) for r in src.res):
            raise MappingError("Raster must have 30 m cells.")
        t = src.transform
        if not (math.isclose(t.a, 30.0, abs_tol=1e-8) and math.isclose(t.e, -30.0, abs_tol=1e-8) and abs(t.b) < 1e-10 and abs(t.d) < 1e-10):
            raise MappingError("Raster must be a north-up 30 m grid.")
        if src.width * src.height > MAX_PIXELS:
            raise MappingError("Raster exceeds the mapping pixel limit.")
        evt = src.read(1).astype(np.int32)
        inside = geometry_mask([geometry], out_shape=(src.height, src.width), transform=src.transform, invert=True, all_touched=False)
        info = {"shape": [int(src.height), int(src.width)], "transform": [float(v) for v in list(src.transform)[:6]], "epsg": OUTPUT_EPSG,
                "cell_area_m2": float(abs(t.a * t.e))}
    return evt, inside, info


def _write_and_verify_rasters(paths: dict, out: np.ndarray, fl: np.ndarray, info: dict, tags: dict) -> None:
    import rasterio
    from rasterio.transform import Affine
    profile = dict(driver="GTiff", height=info["shape"][0], width=info["shape"][1], count=1, dtype="int16",
                   crs=f"EPSG:{info['epsg']}", transform=Affine(*info["transform"]), nodata=NODATA, compress="deflate")
    for key, array, description in (("cover_type_tif", out, "Candidate cover-type raster"), ("forest_land_tif", fl, "Candidate forest-land raster")):
        with rasterio.open(paths[key], "w", **profile) as dst:
            dst.write(array.astype("int16"), 1)
            dst.update_tags(description=description, **tags)
        with rasterio.open(paths[key]) as check:
            if not np.array_equal(check.read(1).astype("int32"), array):
                raise MappingError(f"Read-back mismatch: {key}")
            if check.nodata != NODATA or check.crs.to_epsg() != info["epsg"] or [float(v) for v in list(check.transform)[:6]] != info["transform"]:
                raise MappingError(f"Read-back georeferencing mismatch: {key}")


# --- orchestration ----------------------------------------------------------------------------------------
def _load_collection(root: Path, acquisition_directory: str):
    directory = _direct_dir(root, acquisition_directory)
    doc = _read_json(_direct_file(directory, "collection.json"))
    if doc.get("document_type") != "mapcp_boundary_collection_v1" or doc.get("usable_for_mapping") is not True:
        raise MappingError("Collection is missing, failed validation, or not marked usable for mapping.")
    if doc.get("classification_performed") is not False:
        raise MappingError("Unexpected collection state.")
    member = doc["extract"]["geotiff_member"]
    tif = (directory / "extract" / member).resolve()
    if (directory / "extract").resolve() not in tif.parents or not tif.is_file():
        raise MappingError("GeoTIFF path escapes or is missing.")
    if _digest(tif) != doc["extract"]["geotiff_sha256"]:
        raise MappingError("GeoTIFF changed since collection.")
    boundary = _direct_file(Path(root).resolve(), doc["boundary_filename"])
    if _digest(boundary) != doc["boundary_sha256"]:
        raise MappingError("Boundary changed since collection.")
    return directory, doc, tif, boundary


def _current_raw_limits():
    try:
        import cover_type_patches as ctp
        return {"max_pixels": int(ctp.MAX_PIXELS), "max_patches": int(ctp.MAX_PATCHES), "source": "cover_type_patches.py (imported)"}
    except Exception:
        return {"max_pixels": None, "max_patches": None, "source": "cover_type_patches.py not importable; check its MAX_PIXELS and MAX_PATCHES"}


def _analyze(root: Path, project_data_root: Path, acquisition_directory: str, crosswalk_filename: str, threshold: float):
    started = time.perf_counter()
    directory, collection, tif, boundary = _load_collection(root, acquisition_directory)
    crosswalk, crosswalk_hash = load_crosswalk(project_data_root, crosswalk_filename)
    evt, inside, info = _read_inputs(tif, boundary)
    result = classify_and_clip(evt, inside, crosswalk)
    cell_area = info["cell_area_m2"]
    stats = class_stats(result["out"], result["valid"], crosswalk, cell_area)
    forest = forest_stats(result["fl"], result["valid"], cell_area)
    closure = {"cover_type_valid_sum_matches": sum(r["cell_count"] for r in stats) == result["valid_cells"],
               "forest_land_valid_sum_matches": sum(r["cell_count"] for r in forest) == result["valid_cells"],
               "total_pixel_sum_matches": result["valid_cells"] + result["outside_cells"] + result["evt_nodata_inside_cells"] == result["total_cells"]}
    if not all(closure.values()):
        raise MappingError(f"Acreage closure failed: {closure}")
    patches_started = time.perf_counter()
    patches = patch_summary(result["out"], result["valid"], crosswalk, cell_area, threshold)
    return {"directory": directory, "collection": collection, "tif": tif, "boundary": boundary, "crosswalk": crosswalk,
            "crosswalk_hash": crosswalk_hash, "info": info, "result": result, "stats": stats, "forest": forest, "closure": closure,
            "patches": patches, "seconds": time.perf_counter() - started, "patch_seconds": time.perf_counter() - patches_started}


def _inputs_record(a: dict) -> dict:
    return {"collection_job_id": a["collection"]["job_id"], "geotiff_sha256": a["collection"]["extract"]["geotiff_sha256"],
            "boundary_sha256": a["collection"]["boundary_sha256"], "crosswalk_sha256": a["crosswalk_hash"]}


def preview_boundary_mapping(outputs_root: Path, request: MappingRequest, project_data_root: Path | None = None) -> MappingResult:
    """Dry run: classify and clip in memory, count raw patches, write one small report. No rasters written."""
    try:
        root = Path(outputs_root).resolve()
        pdr = Path(project_data_root) if project_data_root else Path(__file__).resolve().parent / "project_data"
        a = _analyze(root, pdr, request.acquisition_directory, request.crosswalk_filename, request.small_patch_threshold_m2)
        r, limits = a["result"], _current_raw_limits()
        p = a["patches"]
        assessment = {"raster_cells_exceed_raw_patch_pixel_limit": (a["info"]["shape"][0] * a["info"]["shape"][1] > limits["max_pixels"]) if limits["max_pixels"] else None,
                      "patches_exceed_raw_patch_limit": (p["total_patches"] > limits["max_patches"]) if limits["max_patches"] else None}
        cell_area = a["info"]["cell_area_m2"]
        summary = {"inside_cells": r["inside_cells"], "inside_acres": round(r["inside_cells"] * cell_area / ACRE_M2, 2),
                   "outside_boundary_cells": r["outside_cells"], "evt_nodata_inside_boundary_cells": r["evt_nodata_inside_cells"],
                   "valid_cells": r["valid_cells"], "classes": a["stats"], "forest_land": a["forest"],
                   "unmapped_evt_codes": [{"evt_code": c, "cells": n, "acres": round(n * cell_area / ACRE_M2, 2)} for c, n in r["unmapped_evt"]],
                   "patches": p, "current_raw_patch_limits": limits, "limit_assessment": assessment, "closure": a["closure"],
                   "seconds_total": round(a["seconds"], 2), "seconds_patch_count": round(a["patch_seconds"], 2)}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        folder = root / f"mapdry_{stamp}_{uuid.uuid4().hex[:6]}"
        folder.mkdir(exist_ok=False)
        report = {"document_type": "mapcp_boundary_mapping_preview_v1", "status": "preview_complete_review_required",
                  "created_at_utc": datetime.now(timezone.utc).isoformat(), "acquisition_directory": request.acquisition_directory,
                  "crosswalk_filename": request.crosswalk_filename, "crosswalk_id": a["crosswalk"]["crosswalk_id"],
                  "crosswalk_version": a["crosswalk"]["crosswalk_version"], "inputs": _inputs_record(a), "grid": a["info"],
                  "summary": summary, "rasters_written": False,
                  "limitations": ["Counts come from in-memory classification of the clipped raster; nothing was written except this report.",
                                  "Patch counts use 4-neighbor connectivity, matching the raw-patch step.",
                                  "A patch count does not show that polygon building, QC or generalization will fit memory or time limits.",
                                  "Hard boundaries and disturbance history are not evaluated."]}
        _write_json(folder / "mapping_preview.json", report)
        return MappingResult(status="preview_complete_review_required", stage="complete", summary=summary,
                             artifacts={"preview_directory": folder.name, "report": "mapping_preview.json"},
                             warnings=["No rasters were written. Review the counts, then run create with this preview folder."])
    except Exception as exc:
        return _fail("preview", exc)


def create_boundary_mapping(outputs_root: Path, request: CreateMappingRequest, project_data_root: Path | None = None) -> MappingResult:
    """Write boundary-clipped candidate rasters in the same file set the raw-patch step already reads."""
    parts, renamed, written, paths = {}, [], [], {}
    try:
        root = Path(outputs_root).resolve()
        pdr = Path(project_data_root) if project_data_root else Path(__file__).resolve().parent / "project_data"
        preview_dir = _direct_dir(root, request.preview_directory)
        preview = _read_json(_direct_file(preview_dir, "mapping_preview.json"))
        if preview.get("document_type") != "mapcp_boundary_mapping_preview_v1" or preview.get("acquisition_directory") != request.acquisition_directory \
                or preview.get("crosswalk_filename") != request.crosswalk_filename:
            raise MappingError("Preview does not match this acquisition and crosswalk.")
        a = _analyze(root, pdr, request.acquisition_directory, request.crosswalk_filename, preview["summary"]["patches"]["threshold_m2"])
        if _inputs_record(a) != preview["inputs"]:
            raise MappingError("Inputs changed since the preview; run the preview again.")
        before = {r["output_code"]: r["cell_count"] for r in preview["summary"]["classes"]}
        if {r["output_code"]: r["cell_count"] for r in a["stats"]} != before:
            raise MappingError("Recomputed class counts differ from the preview.")
        cw, r, info = a["crosswalk"], a["result"], a["info"]
        job_id = a["collection"]["job_id"]
        prefix = f"cmap_{job_id.split('-')[0]}_{cw['crosswalk_version']}"
        names = {"cover_type_tif": f"{prefix}_cover_type_30m.tif", "forest_land_tif": f"{prefix}_forest_land_30m.tif",
                 "codebook_csv": f"{prefix}_cover_type_codebook.csv", "cover_type_acreage_csv": f"{prefix}_cover_type_acreage.csv",
                 "forest_land_acreage_csv": f"{prefix}_forest_land_acreage.csv", "methods_json": f"{prefix}_methods.json"}
        paths = {k: root / v for k, v in names.items()}
        existing = [v for k, v in names.items() if paths[k].exists() or Path(str(paths[k]) + ".part").exists()]
        if existing:
            raise MappingError(f"Output already exists and will not be overwritten: {existing}")
        parts = {k: Path(str(p) + ".part") for k, p in paths.items()}
        cell_area = info["cell_area_m2"]
        source_codes = {}
        for e in cw["entries"]:
            source_codes.setdefault(e["output_code"], []).append(e["evt_code"])
        tags = {"crosswalk_id": cw["crosswalk_id"], "crosswalk_version": cw["crosswalk_version"], "cover_scheme_id": cw["cover_scheme_id"],
                "job_id": job_id, "status": "preliminary_candidate_requires_review", "boundary_clipped": "true"}
        _write_and_verify_rasters({"cover_type_tif": parts["cover_type_tif"], "forest_land_tif": parts["forest_land_tif"]}, r["out"], r["fl"], info, tags)
        written += [parts["cover_type_tif"], parts["forest_land_tif"]]
        tri = {True: "true", False: "false", None: "null"}
        with parts["codebook_csv"].open("x", encoding="utf-8-sig", newline="") as stream:
            w = csv.writer(stream, lineterminator="\n")
            w.writerow(["output_code", "output_label", "candidate_forest_land", "description", "source_evt_codes"])
            for row in cw["output_code_table"]:
                w.writerow([row["output_code"], row["output_label"], tri[row.get("candidate_forest_land")], row.get("description", ""),
                            ";".join(str(c) for c in sorted(source_codes.get(row["output_code"], [])))])
        written.append(parts["codebook_csv"])
        with parts["cover_type_acreage_csv"].open("x", encoding="utf-8-sig", newline="") as stream:
            w = csv.writer(stream, lineterminator="\n")
            w.writerow(["output_code", "output_label", "candidate_forest_land", "cell_count", "square_meters", "acres", "fraction_of_valid"])
            for s in a["stats"]:
                w.writerow([s["output_code"], s["output_label"], tri[s["candidate_forest_land"]], s["cell_count"], s["square_meters"], s["acres"], s["fraction_of_valid"]])
            for label, n in (("outside_boundary_masked", r["outside_cells"]), ("evt_nodata_inside_boundary", r["evt_nodata_inside_cells"])):
                w.writerow([NODATA, label, "null", n, round(n * cell_area, 2), round(n * cell_area / ACRE_M2, 4), ""])
        written.append(parts["cover_type_acreage_csv"])
        with parts["forest_land_acreage_csv"].open("x", encoding="utf-8-sig", newline="") as stream:
            w = csv.writer(stream, lineterminator="\n")
            w.writerow(["forest_land_code", "meaning", "cell_count", "acres"])
            for s in a["forest"]:
                w.writerow([s["forest_land_code"], s["meaning"], s["cell_count"], s["acres"]])
        written.append(parts["forest_land_acreage_csv"])
        methods = {
            "document_type": "candidate_cover_type_methods_and_provenance", "mapping_status": "complete", "rasters_written": True,
            "write_errors": [], "created_at_utc": datetime.now(timezone.utc).isoformat(), "job_id": job_id,
            "crosswalk_filename": request.crosswalk_filename, "crosswalk_id": cw["crosswalk_id"], "crosswalk_version": cw["crosswalk_version"],
            "cover_scheme_id": cw["cover_scheme_id"], "cover_scheme_version": cw["cover_scheme_version"],
            "crosswalk_approval_note": cw["crosswalk_approval_note"], "crosswalk_sha256": a["crosswalk_hash"],
            "evt_add_url": cw.get("evt_add_url"), "evt_add_sha256": cw.get("evt_add_sha256"),
            "universal_review_flags": cw.get("universal_review_flags", []),
            "sentinels": {"classification_performed": True, "crosswalk_applied": True, "candidate_cover_types_produced": True,
                          "candidate_forest_land_produced": True, "boundary_clipping_performed": True, "field_inventory_performed": False,
                          "authoritative_forest_land_determination_performed": False, "candidate_polygons_produced": False},
            "boundary_filename": a["collection"]["boundary_filename"], "boundary_sha256": a["collection"]["boundary_sha256"],
            "source_geotiff_sha256": a["collection"]["extract"]["geotiff_sha256"], "preview_directory": request.preview_directory,
            "nodata_value": NODATA, "raster_shape": info["shape"], "raster_crs_epsg": info["epsg"], "raster_transform": info["transform"],
            "total_pixels": r["total_cells"], "valid_cell_count": r["valid_cells"], "nodata_cell_count": r["total_cells"] - r["valid_cells"],
            "outside_boundary_cells": r["outside_cells"], "evt_nodata_inside_boundary_cells": r["evt_nodata_inside_cells"],
            "cell_area_m2": cell_area, "valid_acres": round(r["valid_cells"] * cell_area / ACRE_M2, 4),
            "cover_type_stats": a["stats"], "forest_land_stats": a["forest"], "acreage_closure": a["closure"],
            "unmapped_evt_codes_seen": [{"evt_code": c, "cells": n} for c, n in r["unmapped_evt"]],
            "deliberately_unmapped_evt_codes": cw.get("deliberately_unmapped_evt_codes", []),
            "warnings": [f"EVT code {c} not in the approved crosswalk; assigned unmapped_evt." for c, _ in r["unmapped_evt"]],
            "artifacts": names,
            "limitations": ["Preliminary candidate assignments; not field inventory, Tribal approval, or management authority.",
                            "Species composition and crown-cover criteria are not directly measured by LANDFIRE EVT.",
                            "EVC/EVH not used for classification. Disturbance not evaluated.",
                            "Cells outside the selected reference boundary are masked as NoData and counted separately; a public reference boundary does not establish ownership, trust status or management authority."]}
        with parts["methods_json"].open("x", encoding="utf-8") as stream:
            json.dump(methods, stream, indent=2, allow_nan=False)
        written.append(parts["methods_json"])
        for key in names:
            parts[key].replace(paths[key])
            renamed.append(paths[key])
        return MappingResult(status="mapping_complete_review_required", stage="complete",
                             summary={"valid_acres": methods["valid_acres"], "classes": a["stats"], "forest_land": a["forest"],
                                      "outside_boundary_cells": r["outside_cells"], "patches_to_expect": a["patches"]["total_patches"],
                                      "next_step": "Review the maps in ArcGIS Pro, then agree new raw-patch limits before polygonizing."},
                             artifacts=names, warnings=methods["limitations"])
    except Exception as exc:
        for p in list(parts.values()) + renamed:
            if Path(p).exists():
                Path(p).unlink()
        return _fail("create", exc)


if __name__ == "__main__":
    import argparse
    import sys
    root = Path(__file__).resolve().parent / "outputs"
    parser = argparse.ArgumentParser(description="Boundary-clipped candidate mapping. 'preview' is a dry run that writes no rasters.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preview"); p.add_argument("acquisition_directory"); p.add_argument("--crosswalk", default="mescalero_v1_evt_crosswalk_v2.json")
    p.add_argument("--threshold-m2", type=float, default=10_000.0)
    p = sub.add_parser("create"); p.add_argument("acquisition_directory"); p.add_argument("preview_directory")
    p.add_argument("--crosswalk", default="mescalero_v1_evt_crosswalk_v2.json"); p.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if args.command == "preview":
        result = preview_boundary_mapping(root, MappingRequest(acquisition_directory=args.acquisition_directory, crosswalk_filename=args.crosswalk,
                                                               small_patch_threshold_m2=args.threshold_m2))
    else:
        if not args.confirm:
            print("Add --confirm to write the clipped rasters."); sys.exit(2)
        result = create_boundary_mapping(root, CreateMappingRequest(acquisition_directory=args.acquisition_directory,
                                                                    preview_directory=args.preview_directory, crosswalk_filename=args.crosswalk))
    print(result.model_dump_json(indent=2))
    raise SystemExit(0 if result.status != "failed" else 1)
