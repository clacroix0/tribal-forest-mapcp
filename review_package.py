"""Bounded, raster-only MapCP review packaging. No network operations."""
import csv
import hashlib
import json
import math
import os
import re
import shutil
import stat
import threading
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 100 * 1024 * 1024
MAX_METHODS_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 4_000_000
ACRE_M2 = 4046.8564224
_BUILD_LOCK = threading.Lock()
METHODS_RE = re.compile(r"cmap_[0-9a-f]{8}_v[1-9][0-9]{0,3}_methods\.json")
SUFFIXES = {
    "cover_type_tif": "cover_type_30m.tif",
    "forest_land_tif": "forest_land_30m.tif",
    "cover_type_codebook_csv": "cover_type_codebook.csv",
    "cover_type_acreage_csv": "cover_type_acreage.csv",
    "forest_land_acreage_csv": "forest_land_acreage.csv",
    "methods_json": "methods.json",
}

class ExportError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

def require(condition, code, message):
    if not condition:
        raise ExportError(code, message)

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def _pairs(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, "invalid_json", "Duplicate JSON keys are not allowed.")
        result[k] = v
    return result

def read_json_bytes(raw):
    try:
        def invalid_number(_):
            raise ValueError("Nonfinite number")
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid_number)
    except (ValueError, UnicodeError):
        raise ExportError("invalid_json", "A required JSON document is invalid.") from None
    require(isinstance(value, dict), "invalid_json", "A required JSON document must be an object.")
    return value

def _copy_regular(source, target, limit):
    require(not source.is_symlink(), "unsafe_file", "Symbolic-link artifacts are not accepted.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(source, flags)
    except OSError:
        raise ExportError("missing_or_unreadable_file", "A required artifact is missing or unreadable.") from None
    total = 0
    with os.fdopen(fd, "rb") as src:
        info = os.fstat(src.fileno())
        require(stat.S_ISREG(info.st_mode), "unsafe_file", "Artifacts must be regular files.")
        require(0 < info.st_size <= limit, "size_limit", "An artifact is empty or exceeds the export limit.")
        with target.open("xb") as dst:
            while True:
                data = src.read(min(1024 * 1024, limit + 1 - total))
                if not data:
                    break
                total += len(data)
                require(total <= limit, "size_limit", "Export size limit exceeded.")
                dst.write(data)
        after = os.fstat(src.fileno())
        require(info.st_size == after.st_size == total and info.st_mtime_ns == after.st_mtime_ns,
                "source_changed", "An artifact changed while being copied; export was stopped.")
    return total

def _integer(value):
    require(type(value) is int and value >= 0, "invalid_metadata", "Counts must be nonnegative integers.")
    return value

def _close(a, b):
    return isinstance(a, (int, float)) and not isinstance(a, bool) and math.isfinite(a) and abs(a - b) <= 0.00015

def _rows(path):
    require(path.stat().st_size <= MAX_METHODS_BYTES, "size_limit", "CSV exceeds the metadata size limit.")
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            require(reader.fieldnames is not None and len(reader.fieldnames) == len(set(reader.fieldnames)),
                    "invalid_csv", "CSV headers are missing or duplicated.")
            rows = []
            for row in reader:
                require(len(rows) < 4096 and None not in row and all(v is not None for v in row.values()),
                        "invalid_csv", "CSV rows are malformed or exceed the row limit.")
                rows.append(row)
    except (UnicodeError, csv.Error):
        raise ExportError("invalid_csv", "A required CSV could not be parsed.") from None
    return rows

def _flag(value):
    require(value in ("true", "false", "null"), "invalid_codebook", "Invalid forest-land flag in codebook.")
    return {"true": True, "false": False, "null": None}[value]

def _codebook(path):
    result = {}
    for row in _rows(path):
        try:
            code = int(row["output_code"])
            label = row["output_label"]
            flag = _flag(row["candidate_forest_land"])
        except (ValueError, KeyError):
            raise ExportError("invalid_codebook", "Codebook fields are missing or invalid.") from None
        require(-32768 <= code <= 32767 and code not in result, "invalid_codebook", "Duplicate or invalid output code.")
        require(bool(re.fullmatch(r"candidate_[A-Z0-9_]+|unmapped_evt|nodata", label)),
                "invalid_codebook", "Unsupported codebook label.")
        result[code] = {"label": label, "flag": flag}
    require(-9999 in result and result[-9999]["label"] == "nodata" and result[-9999]["flag"] is None,
            "invalid_codebook", "Codebook must explicitly distinguish NoData.")
    return result

def _validate_methods(m, prefix):
    require(m.get("document_type") == "candidate_cover_type_methods_and_provenance",
            "invalid_metadata", "Unsupported methods document type.")
    require(m.get("mapping_status") == "complete" and m.get("rasters_written") is True,
            "incomplete_mapping", "Only completed mappings with both rasters written may be exported.")
    require(m.get("write_errors") == [], "incomplete_mapping", "Mapping write errors are present or unreported.")
    try:
        job = str(uuid.UUID(m["job_id"]))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ExportError("invalid_metadata", "Methods document has no valid full job ID.") from None
    version = m.get("crosswalk_version")
    require(isinstance(version, str) and re.fullmatch(r"v[1-9][0-9]{0,3}", version),
            "invalid_metadata", "Unsupported crosswalk version.")
    require(prefix == f"cmap_{job[:8]}_{version}", "identity_mismatch", "Filename and methods run identity disagree.")
    require(isinstance(m.get("crosswalk_id"), str) and isinstance(m.get("cover_scheme_id"), str),
            "invalid_metadata", "Configuration identifiers must be recorded.")
    sentinels = m.get("sentinels", {})
    for key in ("classification_performed", "crosswalk_applied", "candidate_cover_types_produced", "candidate_forest_land_produced"):
        require(sentinels.get(key) is True, "incomplete_mapping", "Required mapping sentinel is missing or false.")
    for key in ("field_inventory_performed", "authoritative_forest_land_determination_performed", "candidate_polygons_produced"):
        require(sentinels.get(key) is False, "unsupported_scope", "Only preliminary raster-only runs are supported by this exporter.")
    shape = m.get("raster_shape")
    require(isinstance(shape, list) and len(shape) == 2 and all(type(n) is int and n > 0 for n in shape),
            "invalid_metadata", "Raster dimensions are invalid.")
    total = shape[0] * shape[1]
    require(total <= MAX_PIXELS and _integer(m.get("total_pixels")) == total,
            "size_limit", "Raster dimensions exceed the export limit or disagree with the recorded count.")
    valid, nodata = _integer(m.get("valid_cell_count")), _integer(m.get("nodata_cell_count"))
    require(valid > 0, "empty_mapping", "A map with no valid cells cannot be exported.")
    require(valid + nodata == total, "closure_failed", "Valid and NoData counts do not close.")
    closure = m.get("acreage_closure", {})
    require(all(closure.get(k) is True for k in ("cover_type_valid_sum_matches", "forest_land_valid_sum_matches", "total_pixel_sum_matches")),
            "closure_failed", "Required mapping closure checks did not pass.")
    for k, expected in (("valid_cell_count", valid), ("cover_type_class_sum", valid), ("forest_land_class_sum", valid), ("nodata_count", nodata), ("total_pixels", total)):
        require(type(closure.get(k)) is int and closure[k] == expected, "closure_failed", "Closure counts disagree with methods.")
    require(m.get("raster_crs_epsg") == 5070 and m.get("nodata_value") == -9999,
            "unsupported_grid", "This initial exporter requires EPSG:5070 and NoData -9999.")
    transform = m.get("raster_transform")
    require(isinstance(transform, list) and len(transform) == 6 and all(type(n) in (int, float) and math.isfinite(n) for n in transform),
            "invalid_metadata", "Raster transform is invalid.")
    require(all(abs(a-b) < 1e-8 for a,b in zip([transform[0],transform[1],transform[3],transform[4]], [30,0,0,-30])),
            "unsupported_grid", "This initial exporter requires a north-up 30 m grid.")
    require(_close(m.get("valid_acres"), valid * 900 / ACRE_M2), "closure_failed", "Recorded valid acreage disagrees with the grid.")

def validate_rasters(folder, names, methods, codebook):
    """Actual raster checks, imported lazily so metadata tests stay portable."""
    try:
        import numpy as np
        import rasterio
    except ImportError:
        raise ExportError("gis_dependency_missing", "Raster validation dependencies are unavailable.") from None
    ct_counts, fl_counts = Counter(), Counter()
    try:
        with rasterio.open(folder / names["cover_type_tif"]) as ct, rasterio.open(folder / names["forest_land_tif"]) as fl:
            expected_transform = methods["raster_transform"]
            for ds in (ct, fl):
                require(ds.count == 1 and list(ds.shape) == methods["raster_shape"], "raster_mismatch", "Raster dimensions or band count disagree.")
                require(ds.crs is not None and ds.crs.to_epsg() == 5070 and ds.nodata == -9999,
                        "raster_mismatch", "Raster CRS or NoData disagrees.")
                require(np.issubdtype(np.dtype(ds.dtypes[0]), np.integer), "raster_mismatch", "Categorical rasters must contain integers.")
                require(all(abs(float(a)-b) < 1e-8 for a,b in zip(list(ds.transform)[:6], expected_transform)),
                        "raster_mismatch", "Raster grid differs from the recorded run.")
                tags = ds.tags()
                for tag in ("job_id", "crosswalk_id", "crosswalk_version", "cover_scheme_id"):
                    require(tags.get(tag) == methods[tag], "identity_mismatch", "Raster provenance tags disagree with the methods.")
            for _, window in ct.block_windows(1):
                a, b = ct.read(1, window=window), fl.read(1, window=window)
                vals, counts = np.unique(a, return_counts=True)
                ct_counts.update({int(v): int(n) for v,n in zip(vals, counts)})
                vals, counts = np.unique(b, return_counts=True)
                fl_counts.update({int(v): int(n) for v,n in zip(vals, counts)})
                expected = np.full(a.shape, 2, dtype=np.int16)
                for value in np.unique(a):
                    value = int(value)
                    require(value in codebook, "unknown_raster_code", "A raster code is absent from the codebook.")
                    flag = codebook[value]["flag"]
                    expected[a == value] = -9999 if value == -9999 else (1 if flag is True else (0 if flag is False else 2))
                require(np.array_equal(expected, b), "forest_land_mismatch", "Forest-land pixels disagree with the codebook and cover-type raster.")
    except ExportError:
        raise
    except Exception:
        raise ExportError("raster_unreadable", "A required raster could not be validated.") from None
    return dict(ct_counts), dict(fl_counts)

def _check_statistics(folder, names, m, codebook, ct_counts, fl_counts):
    def counts_check(rows, code_key, actual, is_cover, include_nodata, *, json_rows=False):
        seen = set()
        for row in rows:
            if json_rows:
                require(
                    isinstance(row, dict)
                    and type(row.get(code_key)) is int
                    and type(row.get("cell_count")) is int,
                    "invalid_statistics",
                    "Methods class codes and cell counts must be JSON integers."
                )
            try:
                code = int(row[code_key])
                n = int(row["cell_count"])
                acres = float(row["acres"])
            except (ValueError, KeyError, TypeError):
                raise ExportError("invalid_statistics", "Acreage fields are invalid.") from None
            require(code not in seen and n >= 0, "invalid_statistics", "Duplicate class or negative count.")
            seen.add(code)
            require(n == actual.get(code, 0) and _close(acres, n * 900 / ACRE_M2),
                    "statistics_mismatch", "Acreage or cell counts disagree with actual raster values.")
            if not is_cover:
                require(code in {-9999, 0, 1, 2}, "invalid_statistics", "Unsupported forest-land code.")
            if is_cover:
                require(code in codebook, "invalid_statistics", "Statistics reference an unknown class.")
                require(row.get("output_label") == codebook[code]["label"], "statistics_mismatch", "Class labels disagree with the codebook.")
                flag = row.get("candidate_forest_land")
                if isinstance(flag, str):
                    flag = _flag(flag)
                require(flag is codebook[code]["flag"], "statistics_mismatch", "Class forest-land flags disagree.")
        needed = {k for k,v in actual.items() if v and (include_nodata or k != -9999)}
        require(needed <= seen and (include_nodata or -9999 not in seen),
                "statistics_mismatch", "Statistics omit populated classes or mix NoData into valid classes.")
    counts_check(_rows(folder/names["cover_type_acreage_csv"]), "output_code", ct_counts, True, True)
    counts_check(_rows(folder/names["forest_land_acreage_csv"]), "forest_land_code", fl_counts, False, True)
    require(isinstance(m.get("cover_type_stats"), list) and isinstance(m.get("forest_land_stats"), list),
            "invalid_statistics", "Methods class statistics are missing.")
    counts_check(m["cover_type_stats"], "output_code", ct_counts, True, False, json_rows=True)
    counts_check(m["forest_land_stats"], "forest_land_code", fl_counts, False, True, json_rows=True)
    require(sum(ct_counts.values()) == m["total_pixels"] == sum(fl_counts.values()),
            "closure_failed", "Actual pixel counts do not close.")
    require(ct_counts.get(-9999, 0) == fl_counts.get(-9999, 0) == m["nodata_cell_count"],
            "closure_failed", "Actual NoData count disagrees with methods.")

GUIDE = """# Preliminary raster review package\n\nExtract this ZIP to a folder before opening its files.\n\n1. Open or create an ArcGIS Pro project. Use Add Data to add the two GeoTIFFs.\n2. Symbolize cover type with Unique Values and the included codebook CSV.\n3. Forest-land codes: 1 = candidate forest land, 0 = candidate nonforest,\n   2 = unknown; -9999 is NoData, not nonforest.\n4. Both rasters use a north-up 30 m EPSG:5070 grid.\n5. Review acreage CSVs, the original methods JSON, QC_AND_LIMITATIONS.json,\n   and PACKAGE_MANIFEST.json before interpretation.\n\nThis is a raster-only review package. No raw or generalized polygons,\nGeoPackage, candidate stands, or physical-accessibility layer is included.\nNo classification or generalization was rerun during export.\n\nThese are preliminary modeled candidate assignments, not field inventory,\nindependent accuracy validation, Tribal approval, Realty verification,\nmanagement authority, ownership, trust status, legal access, commercial\nstatus, or productivity determinations. Professional forestry review is\nrequired. Export does not certify that professional review occurred.\nSource paths inside the original methods document are server references,\nnot files included in this ZIP unless listed in PACKAGE_MANIFEST.json.\n\nThe manifest hashes every other package member; it does not hash itself.\nThe download response supplies a separate checksum for the complete ZIP.\n"""

def _build_review_package(outputs_dir, methods_filename, *, raster_validator=None):
    require(isinstance(methods_filename, str) and METHODS_RE.fullmatch(methods_filename),
            "invalid_input", "Supply a generated cmap_<8 hex>_vN_methods.json filename, not a path.")
    root = Path(outputs_dir)
    require(root.is_dir() and not root.is_symlink(), "unsafe_directory", "The controlled output directory is unavailable or symbolic.")
    root = root.resolve()
    export_root = root / "review_packages"
    require(not export_root.is_symlink(), "unsafe_directory", "Export directory must not be symbolic.")
    export_root.mkdir(exist_ok=True)
    require(sum(1 for _ in export_root.iterdir()) < 32, "local_cache_limit",
            "Local package-cache limit reached; administrator review is required before further exports.")
    package_id = str(uuid.uuid4())
    stage = export_root / package_id
    stage.mkdir(exist_ok=False)
    try:
        prefix = methods_filename[:-len("_methods.json")]
        names = {k: f"{prefix}_{v}" for k,v in SUFFIXES.items()}
        used = _copy_regular(root / methods_filename, stage / methods_filename, MAX_METHODS_BYTES)
        m = read_json_bytes((stage / methods_filename).read_bytes())
        _validate_methods(m, prefix)
        try:
            remaining_bytes = sum((root/n).lstat().st_size for k,n in names.items() if k != "methods_json")
        except OSError:
            raise ExportError("missing_or_unreadable_file", "A required artifact is missing or unreadable.") from None
        require(used + remaining_bytes <= MAX_BYTES, "size_limit", "Package source files exceed the export size limit.")
        require(shutil.disk_usage(root).free >= 2 * remaining_bytes + used + 2 * 1024 * 1024,
                "insufficient_space", "Insufficient temporary disk space for a safe snapshot and ZIP.")
        refs = m.get("artifacts")
        require(isinstance(refs, dict), "invalid_metadata", "Methods artifact references are missing.")
        for k, name in names.items():
            ref = refs.get(k)
            require(isinstance(ref, str) and "\\" not in ref and ".." not in ref.split("/") and ref.split("/")[-1] == name,
                    "identity_mismatch", "Methods artifact filenames disagree with the run.")
            if k != "methods_json":
                used += _copy_regular(root / name, stage / name, MAX_BYTES-used)
                require(used <= MAX_BYTES, "size_limit", "Package source files exceed the export size limit.")
        book = _codebook(stage / names["cover_type_codebook_csv"])
        validator = raster_validator or validate_rasters
        ct, fl = validator(stage, names, m, book)
        _check_statistics(stage, names, m, book, ct, fl)
        source_warnings = m.get("warnings", [])
        require(isinstance(source_warnings, list) and len(source_warnings) <= 32 and
                all(isinstance(w, str) and len(w) <= 500 for w in source_warnings),
                "invalid_metadata", "Source warnings exceed the bounded response limit.")
        warnings = [
            "Raster-only package; polygons and GeoPackage are not included.",
            "Automated consistency checks are not independent classification accuracy or professional review.",
            "Cover-scheme approval and source-dictionary lineage were not independently authenticated by export.",
        ] + source_warnings
        qc = {
            "package_scope": "preliminary_raster_review_only",
            "checks": {"files_present": True, "raster_grid_and_tags_match": True,
                       "forest_land_pixels_match_codebook": True, "csv_and_methods_match_rasters": True,
                       "actual_cell_count_closure": True},
            "professional_review_status": "not_verified_by_export_tool",
            "independent_accuracy_evaluated": False,
            "source_warnings": m.get("warnings", []),
            "source_limitations": m.get("limitations", []),
            "source_review_flags": m.get("universal_review_flags", []),
            "evc_evh_policy": m.get("evc_evh_policy"),
            "disturbance_policy": m.get("disturbance_policy"),
            "unmapped_evt_codes_seen": m.get("unmapped_evt_codes_seen", []),
            "warnings": warnings,
        }
        (stage/"OPEN_IN_ARCGIS_PRO.md").write_text(GUIDE, encoding="utf-8")
        (stage/"QC_AND_LIMITATIONS.json").write_text(json.dumps(qc, indent=2, allow_nan=False), encoding="utf-8")
        members = sorted(list(names.values()) + ["OPEN_IN_ARCGIS_PRO.md", "QC_AND_LIMITATIONS.json"])
        manifest = {
            "schema_version": "1", "package_id": package_id, "created_at_utc": utc_now(),
            "package_scope": "preliminary_raster_review_only", "job_id": m["job_id"],
            "crosswalk_id": m["crosswalk_id"], "crosswalk_version": m["crosswalk_version"],
            "cover_scheme_id": m["cover_scheme_id"], "cover_scheme_version": m.get("cover_scheme_version"),
            "source_methods_filename": methods_filename,
            "files": [{"name": n, "bytes": (stage/n).stat().st_size, "sha256": sha256_file(stage/n)} for n in members],
            "manifest_self_hash_excluded": True,
        }
        (stage/"PACKAGE_MANIFEST.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
        members.append("PACKAGE_MANIFEST.json")
        archive = stage / "mapcp_raster_review.zip"
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
            for name in members:
                z.write(stage/name, arcname=name)
        require(0 < archive.stat().st_size <= MAX_BYTES, "size_limit", "ZIP exceeds the export limit.")
        with zipfile.ZipFile(archive) as z:
            require(z.testzip() is None and sorted(z.namelist()) == sorted(members), "archive_failed", "ZIP integrity check failed.")
            for item in manifest["files"]:
                require(hashlib.sha256(z.read(item["name"])).hexdigest() == item["sha256"], "archive_failed", "ZIP content checksum failed.")
        return {"status": "package_created", "package_id": package_id, "archive_path": str(archive),
                "package_bytes": archive.stat().st_size, "package_sha256": sha256_file(archive),
                "package_scope": manifest["package_scope"], "job_id": m["job_id"],
                "crosswalk_version": m["crosswalk_version"], "files": members, "warnings": warnings,
                "classification_rerun": False, "storage_uploaded": False}
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def build_review_package(outputs_dir, methods_filename, *, raster_validator=None):
    require(_BUILD_LOCK.acquire(blocking=False), "export_busy", "Another package build is running; no second build was started.")
    try:
        return _build_review_package(outputs_dir, methods_filename, raster_validator=raster_validator)
    finally:
        _BUILD_LOCK.release()
