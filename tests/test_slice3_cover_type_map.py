# tests/test_slice3_cover_type_map.py
#
# Slice 3 — Candidate Cover-Type and Forest-Land Raster Mapping
#
# Tests for _apply_evt_crosswalk() and map_candidate_cover_types().
#
# All committed tests are synthetic and independent of Mescalero data.
# One conditional test (M-opt) runs only when the local LFPS v2 collection
# manifest is present in outputs/.
#
# No crosswalk or candidate layers produced in Slice 2 or 2b tests.
# Run with:  PYTHONPATH=. .venv\Scripts\pytest tests/test_slice3_cover_type_map.py -v

import csv
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from server import (
    _apply_evt_crosswalk,
    _load_crosswalk,
    map_candidate_cover_types,
    OUTPUT_FOLDER,
    _FL_TRUE, _FL_FALSE, _FL_UNKNOWN, _FL_NODATA,
    _UNMAPPED_CODE, _MAP_NODATA,
    _SLICE3_MAPPING_SENTINELS,
)
from mcp.server.mcpserver.exceptions import ToolError

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_SYNTH_EPSG = 5070
_SYNTH_TRANSFORM = from_origin(-885825.0, 1171005.0, 30.0, 30.0)
_SYNTH_JOB_ID = "11111111-2222-3333-4444-555555555555"

# Minimal crosswalk covering two EVT codes for synthetic tests
_SYNTH_CROSSWALK = {
    "crosswalk_id": "test_crosswalk_v1",
    "crosswalk_version": "v1",
    "cover_scheme_id": "test_scheme",
    "cover_scheme_version": "v1",
    "nodata_value": -9999,
    "unmapped_valid_output_code": 255,
    "output_code_table": [
        {"output_code": 1, "output_label": "candidate_P",  "candidate_forest_land": True,  "description": "Ponderosa Pine"},
        {"output_code": 4, "output_label": "candidate_BR", "candidate_forest_land": False, "description": "Brush"},
        {"output_code": 7, "output_label": "candidate_RIP_UNCERTAIN", "candidate_forest_land": None, "description": "Riparian Uncertain"},
        {"output_code": 8, "output_label": "candidate_UNCERTAIN_PINE_OAK", "candidate_forest_land": None, "description": "Uncertain pine-oak"},
        {"output_code": 255, "output_label": "unmapped_evt", "candidate_forest_land": None, "description": "Unmapped EVT code"},
        {"output_code": -9999, "output_label": "nodata", "candidate_forest_land": None, "description": "NoData"},
    ],
    "entries": [
        {"evt_code": 7054, "evt_name": "Southern Rocky Mountain Ponderosa Pine Woodland",
         "output_label": "candidate_P", "output_code": 1, "candidate_forest_land": True},
        {"evt_code": 7107, "evt_name": "Rocky Mountain Gambel Oak-Mixed Montane Shrubland",
         "output_label": "candidate_BR", "output_code": 4, "candidate_forest_land": False},
        {"evt_code": 9519, "evt_name": "Rocky Mountain Lower Montane-Foothill Riparian Shrubland",
         "output_label": "candidate_RIP_UNCERTAIN", "output_code": 7, "candidate_forest_land": None},
        {"evt_code": 7024, "evt_name": "Madrean Lower Montane Pine-Oak Forest and Woodland",
         "output_label": "candidate_UNCERTAIN_PINE_OAK", "output_code": 8, "candidate_forest_land": None},
    ],
    "evt_add_sha256": "abc123",
    "crosswalk_approval_note": "SYNTHETIC TEST CROSSWALK",
    "universal_review_flags": ["professional_forestry_review_required"],
    "evc_evh_policy": "No EVC/EVH thresholds.",
    "disturbance_policy": "not_evaluated",
}


def _build_tif(tmp_path: Path, evt_data: np.ndarray, nodata: int = -9999) -> Path:
    """SYNTHETIC: write a 3-band GeoTIFF with controlled EVT band values."""
    h, w = evt_data.shape
    crs = CRS.from_epsg(_SYNTH_EPSG)
    evc_data = np.full((h, w), 111, dtype=np.int16)
    evh_data = np.full((h, w), 105, dtype=np.int16)
    tif_path = tmp_path / "synth.tif"
    with rasterio.open(
        str(tif_path), "w", driver="GTiff",
        height=h, width=w, count=3, dtype=np.int16,
        crs=crs, transform=_SYNTH_TRANSFORM, nodata=nodata,
    ) as dst:
        dst.write(evt_data.astype(np.int16), 1)
        dst.write(evc_data, 2)
        dst.write(evh_data, 3)
    with rasterio.open(str(tif_path), "r+") as dst:
        dst.descriptions = ("LF2025_EVT_CONUS", "LF2025_EVC_CONUS", "LF2025_EVH_CONUS")
    return tif_path


def _build_manifest(tmp_path: Path, tif_path: Path,
                    job_id: str = _SYNTH_JOB_ID) -> tuple:
    """SYNTHETIC: write a minimal LFPS v2 collection manifest."""
    manifest = {
        "api_version": "LFPS v2",
        "job_id": job_id,
        "geotiff_file": str(tif_path),
        "expected_metadata_xml_files": {},
    }
    folder = tmp_path / "outputs"
    folder.mkdir(exist_ok=True)
    fname = f"lfps_v2_collection_20260101T000000000000Z_{job_id}.json"
    p = folder / fname
    p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest, p, fname


# ---------------------------------------------------------------------------
# Helper: run _apply_evt_crosswalk with a simple 4x4 raster
# ---------------------------------------------------------------------------

def _simple_fixture(tmp_path: Path):
    """4x4 raster: mostly 7054 (P), one 7107 (BR), one nodata."""
    evt_data = np.array([
        [7054, 7054, 7054, 7054],
        [7054, 7054, 7107, 7054],
        [7054, 7054, 7054, -9999],
        [7054, 7054, 7054, 7054],
    ], dtype=np.int16)
    tif = _build_tif(tmp_path, evt_data)
    manifest, _, _ = _build_manifest(tmp_path, tif)
    return manifest, tif


# ===========================================================================
# M-1: Output arrays have same shape as input EVT band
# ===========================================================================

class TestM1OutputShape:
    def test_m1_output_shape_matches_input(self, tmp_path):
        """M-1: Output rasters are the same shape as the source EVT band."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["mapping_status"] == "complete"
        assert report["raster_shape"] == [4, 4]
        assert report["total_pixels"] == 16


# ===========================================================================
# M-2: Known mapped EVT code → correct integer output code
# ===========================================================================

class TestM2KnownCodeMapping:
    def test_m2_mapped_evt_gets_correct_output_code(self, tmp_path):
        """M-2: EVT 7054 → output_code 1 (candidate_P)."""
        evt_data = np.full((4, 4), 7054, dtype=np.int16)
        evt_data[0, 0] = -9999
        tif = _build_tif(tmp_path, evt_data)
        manifest, _, _ = _build_manifest(tmp_path, tif)

        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["mapping_status"] == "complete"
        stats = {r["output_code"]: r for r in report["cover_type_stats"]}
        assert 1 in stats, "Output code 1 (candidate_P) should be present"
        assert stats[1]["cell_count"] == 15  # 16 - 1 nodata

    def test_m2_br_code_assigned(self, tmp_path):
        """M-2: EVT 7107 → output_code 4 (candidate_BR)."""
        evt_data = np.array([[7107, 7107], [7107, -9999]], dtype=np.int16)
        tif = _build_tif(tmp_path, evt_data)
        manifest, _, _ = _build_manifest(tmp_path, tif)

        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        stats = {r["output_code"]: r for r in report["cover_type_stats"]}
        assert stats[4]["cell_count"] == 3

    def test_m2_null_forest_land_code_assigned_correctly(self, tmp_path):
        """M-2: EVT 9519 → output_code 7 (RIP_UNCERTAIN, forest_land=null)."""
        evt_data = np.full((2, 2), 9519, dtype=np.int16)
        tif = _build_tif(tmp_path, evt_data)
        manifest, _, _ = _build_manifest(tmp_path, tif)

        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        stats = {r["output_code"]: r for r in report["cover_type_stats"]}
        assert 7 in stats
        assert stats[7]["candidate_forest_land"] is None


# ===========================================================================
# M-3: Unknown EVT code → integer 255, unmapped_evt flag
# ===========================================================================

class TestM3UnmappedCode:
    def test_m3_unmapped_code_gets_255(self, tmp_path):
        """M-3: An EVT code not in the crosswalk maps to 255 (unmapped_evt)."""
        evt_data = np.array([[9999, 9999], [9999, -9999]], dtype=np.int16)
        tif = _build_tif(tmp_path, evt_data)
        manifest, _, _ = _build_manifest(tmp_path, tif)

        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert 9999 in report["unmapped_evt_codes_seen"]
        stats = {r["output_code"]: r for r in report["cover_type_stats"]}
        assert _UNMAPPED_CODE in stats
        assert stats[_UNMAPPED_CODE]["cell_count"] == 3

    def test_m3_unmapped_code_warning_names_code(self, tmp_path):
        """M-3: Warning message names the specific unmapped EVT code."""
        evt_data = np.full((2, 2), 8888, dtype=np.int16)
        tif = _build_tif(tmp_path, evt_data)
        manifest, _, _ = _build_manifest(tmp_path, tif)

        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        warnings_text = " ".join(report.get("warnings", []))
        assert "8888" in warnings_text


# ===========================================================================
# M-4: NoData pixels preserved as -9999 in both rasters
# ===========================================================================

class TestM4NoDataPreserved:
    def test_m4_nodata_not_reassigned(self, tmp_path):
        """M-4: NoData cells are -9999 in both output rasters."""
        evt_data = np.array([[-9999, 7054], [-9999, 7054]], dtype=np.int16)
        tif = _build_tif(tmp_path, evt_data)
        manifest, _, _ = _build_manifest(tmp_path, tif)

        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["nodata_cell_count"] == 2
        assert report["valid_cell_count"] == 2

    def test_m4_nodata_count_in_stats(self, tmp_path):
        """M-4: nodata_cell_count matches the number of -9999 input pixels."""
        evt_data = np.full((4, 4), 7054, dtype=np.int16)
        evt_data[:, 3] = -9999  # 4 nodata pixels
        tif = _build_tif(tmp_path, evt_data)
        manifest, _, _ = _build_manifest(tmp_path, tif)

        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["nodata_cell_count"] == 4
        assert report["valid_cell_count"] == 12


# ===========================================================================
# M-5: Forest-land raster codes
# ===========================================================================

class TestM5ForestLandCodes:
    def test_m5_forest_true_pixels(self, tmp_path):
        """M-5: EVT 7054 (forest_land=true) → FL raster code 1."""
        evt_data = np.full((2, 2), 7054, dtype=np.int16)
        tif = _build_tif(tmp_path, evt_data)
        manifest, _, _ = _build_manifest(tmp_path, tif)

        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        fl_stats = {r["forest_land_code"]: r for r in report["forest_land_stats"]}
        assert fl_stats[_FL_TRUE]["cell_count"] == 4

    def test_m5_forest_false_pixels(self, tmp_path):
        """M-5: EVT 7107 (forest_land=false) → FL raster code 0."""
        evt_data = np.full((2, 2), 7107, dtype=np.int16)
        tif = _build_tif(tmp_path, evt_data)
        manifest, _, _ = _build_manifest(tmp_path, tif)

        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        fl_stats = {r["forest_land_code"]: r for r in report["forest_land_stats"]}
        assert fl_stats[_FL_FALSE]["cell_count"] == 4

    def test_m5_forest_unknown_pixels(self, tmp_path):
        """M-5: EVT 9519 (forest_land=null) → FL raster code 2."""
        evt_data = np.full((2, 2), 9519, dtype=np.int16)
        tif = _build_tif(tmp_path, evt_data)
        manifest, _, _ = _build_manifest(tmp_path, tif)

        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        fl_stats = {r["forest_land_code"]: r for r in report["forest_land_stats"]}
        assert fl_stats[_FL_UNKNOWN]["cell_count"] == 4

    def test_m5_nodata_pixels_get_fl_nodata(self, tmp_path):
        """M-5: NoData pixels → FL raster code -9999."""
        evt_data = np.array([[-9999, 7054], [-9999, 7054]], dtype=np.int16)
        tif = _build_tif(tmp_path, evt_data)
        manifest, _, _ = _build_manifest(tmp_path, tif)

        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        fl_stats = {r["forest_land_code"]: r for r in report["forest_land_stats"]}
        assert fl_stats[_FL_NODATA]["cell_count"] == 2


# ===========================================================================
# M-6: Acreage closure
# ===========================================================================

class TestM6AcreageClosure:
    def test_m6_cover_type_valid_sum_matches(self, tmp_path):
        """M-6: Sum of cover-type class cells == valid_cell_count."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        closure = report["acreage_closure"]
        assert closure["cover_type_valid_sum_matches"] is True, (
            f"Closure failed: {closure}"
        )

    def test_m6_forest_land_valid_sum_matches(self, tmp_path):
        """M-6: Sum of forest-land class cells (excl. nodata) == valid_cell_count."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        closure = report["acreage_closure"]
        assert closure["forest_land_valid_sum_matches"] is True, (
            f"FL closure failed: {closure}"
        )

    def test_m6_total_pixel_closure(self, tmp_path):
        """M-6: valid_cells + nodata_cells == total_pixels."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        closure = report["acreage_closure"]
        assert closure["total_pixel_sum_matches"] is True, (
            f"Total closure failed: {closure}"
        )


# ===========================================================================
# M-7: Output grid identical to source
# ===========================================================================

class TestM7GridIdentity:
    def test_m7_shape_matches_source(self, tmp_path):
        """M-7: Output raster shape matches source EVT band."""
        evt_data = np.full((5, 7), 7054, dtype=np.int16)
        tif = _build_tif(tmp_path, evt_data)
        manifest, _, _ = _build_manifest(tmp_path, tif)

        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["raster_shape"] == [5, 7]
        assert report["total_pixels"] == 35

    def test_m7_crs_preserved(self, tmp_path):
        """M-7: Output CRS EPSG matches source."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["raster_crs_epsg"] == 5070

    def test_m7_nodata_value_preserved(self, tmp_path):
        """M-7: Output nodata value matches crosswalk nodata_value."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["nodata_value"] == _MAP_NODATA


# ===========================================================================
# M-8: Codebook CSV complete
# ===========================================================================

class TestM8CodebookCSV:
    def test_m8_codebook_written_with_correct_columns(self, tmp_path):
        """M-8: Codebook CSV contains required columns."""
        manifest, tif = _simple_fixture(tmp_path)
        folder = tmp_path / "outputs"
        folder.mkdir(exist_ok=True)
        fname = f"lfps_v2_collection_20260101T000000000000Z_{_SYNTH_JOB_ID}.json"
        (folder / fname).write_text(json.dumps(manifest), encoding="utf-8")

        with (
            patch("server.OUTPUT_FOLDER", folder),
            patch("server._load_crosswalk", return_value=(_SYNTH_CROSSWALK, "")),
        ):
            result = map_candidate_cover_types(fname, "test_crosswalk_v1.json")

        cb_path = Path(result["artifacts"]["cover_type_codebook_csv"])
        assert cb_path.exists()
        with cb_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            cols = set(reader.fieldnames or [])
        assert {"output_code", "output_label", "candidate_forest_land",
                "description", "source_evt_codes"}.issubset(cols)

    def test_m8_codebook_contains_nodata_and_unmapped_rows(self, tmp_path):
        """M-8: Codebook includes nodata and unmapped_evt rows."""
        manifest, tif = _simple_fixture(tmp_path)
        folder = tmp_path / "outputs"
        folder.mkdir(exist_ok=True)
        fname = f"lfps_v2_collection_20260101T000000000000Z_{_SYNTH_JOB_ID}.json"
        (folder / fname).write_text(json.dumps(manifest), encoding="utf-8")

        with (
            patch("server.OUTPUT_FOLDER", folder),
            patch("server._load_crosswalk", return_value=(_SYNTH_CROSSWALK, "")),
        ):
            result = map_candidate_cover_types(fname, "test_crosswalk_v1.json")

        cb_path = Path(result["artifacts"]["cover_type_codebook_csv"])
        with cb_path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        codes = [int(r["output_code"]) for r in rows]
        assert -9999 in codes, "Nodata row missing from codebook"
        assert 255 in codes, "unmapped_evt row missing from codebook"


# ===========================================================================
# M-9: Sentinel fields
# ===========================================================================

class TestM9Sentinels:
    def test_m9_classification_performed_true(self, tmp_path):
        """M-9: classification_performed is True in mapping output."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["classification_performed"] is True

    def test_m9_crosswalk_applied_true(self, tmp_path):
        """M-9: crosswalk_applied is True."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["crosswalk_applied"] is True

    def test_m9_candidate_cover_types_produced_true(self, tmp_path):
        """M-9: candidate_cover_types_produced is True."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["candidate_cover_types_produced"] is True

    def test_m9_candidate_forest_land_produced_true(self, tmp_path):
        """M-9: candidate_forest_land_produced is True."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["candidate_forest_land_produced"] is True

    def test_m9_field_inventory_performed_false(self, tmp_path):
        """M-9: field_inventory_performed is always False."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["field_inventory_performed"] is False

    def test_m9_authoritative_fl_determination_false(self, tmp_path):
        """M-9: authoritative_forest_land_determination_performed is False."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["authoritative_forest_land_determination_performed"] is False

    def test_m9_candidate_polygons_false(self, tmp_path):
        """M-9: candidate_polygons_produced is False."""
        manifest, tif = _simple_fixture(tmp_path)
        report = _apply_evt_crosswalk(manifest, _SYNTH_CROSSWALK)
        assert report["candidate_polygons_produced"] is False


# ===========================================================================
# M-10: Methods JSON provenance
# ===========================================================================

class TestM10MethodsJSON:
    def test_m10_methods_json_provenance_fields(self, tmp_path):
        """M-10: Methods JSON contains required provenance fields."""
        manifest, tif = _simple_fixture(tmp_path)
        folder = tmp_path / "outputs"
        folder.mkdir(exist_ok=True)
        fname = f"lfps_v2_collection_20260101T000000000000Z_{_SYNTH_JOB_ID}.json"
        (folder / fname).write_text(json.dumps(manifest), encoding="utf-8")

        with (
            patch("server.OUTPUT_FOLDER", folder),
            patch("server._load_crosswalk", return_value=(_SYNTH_CROSSWALK, "")),
        ):
            result = map_candidate_cover_types(fname, "test_crosswalk_v1.json")

        methods_path = Path(result["artifacts"]["methods_json"])
        assert methods_path.exists()
        doc = json.loads(methods_path.read_text(encoding="utf-8"))

        assert doc["crosswalk_version"] == "v1"
        assert doc["cover_scheme_id"] == "test_scheme"
        assert doc["evt_add_sha256"] == "abc123"
        assert "crosswalk_approval_note" in doc
        assert "acreage_closure" in doc
        assert doc["sentinels"]["classification_performed"] is True
        assert doc["sentinels"]["field_inventory_performed"] is False

    def test_m10_methods_json_has_arcgis_instructions(self, tmp_path):
        """M-10: Methods JSON contains ArcGIS Pro opening instructions."""
        manifest, tif = _simple_fixture(tmp_path)
        folder = tmp_path / "outputs"
        folder.mkdir(exist_ok=True)
        fname = f"lfps_v2_collection_20260101T000000000000Z_{_SYNTH_JOB_ID}.json"
        (folder / fname).write_text(json.dumps(manifest), encoding="utf-8")

        with (
            patch("server.OUTPUT_FOLDER", folder),
            patch("server._load_crosswalk", return_value=(_SYNTH_CROSSWALK, "")),
        ):
            result = map_candidate_cover_types(fname, "test_crosswalk_v1.json")

        doc = json.loads(
            Path(result["artifacts"]["methods_json"]).read_text(encoding="utf-8")
        )
        assert "arcgis_pro_opening_instructions" in doc
        assert "ArcGIS Pro" in doc["arcgis_pro_opening_instructions"]


# ===========================================================================
# M-extra: No-overwrite behavior
# ===========================================================================

class TestNoOverwrite:
    def test_no_overwrite_raises_tool_error(self, tmp_path):
        """Tool raises ToolError when artifacts already exist."""
        manifest, tif = _simple_fixture(tmp_path)
        folder = tmp_path / "outputs"
        folder.mkdir(exist_ok=True)
        fname = f"lfps_v2_collection_20260101T000000000000Z_{_SYNTH_JOB_ID}.json"
        (folder / fname).write_text(json.dumps(manifest), encoding="utf-8")

        with (
            patch("server.OUTPUT_FOLDER", folder),
            patch("server._load_crosswalk", return_value=(_SYNTH_CROSSWALK, "")),
        ):
            map_candidate_cover_types(fname, "test_crosswalk_v1.json")
            with pytest.raises(ToolError, match="already exists"):
                map_candidate_cover_types(fname, "test_crosswalk_v1.json")


class TestBadManifestRejected:
    def test_bad_filename_raises_tool_error(self):
        """Bad manifest filename pattern raises ToolError."""
        with pytest.raises(ToolError):
            map_candidate_cover_types("not_a_real_manifest.json")

    def test_path_traversal_rejected(self):
        """Path traversal in manifest filename raises ToolError."""
        with pytest.raises(ToolError):
            map_candidate_cover_types("../evil.json")


# ===========================================================================
# M-opt: Conditional local Mescalero test
# ===========================================================================

_REPO_ROOT = Path(__file__).parent.parent
_LOCAL_MANIFEST_DIR = _REPO_ROOT / "outputs"
_CROSSWALK_PATH = _REPO_ROOT / "project_data" / "crosswalks" / "mescalero_v1_evt_crosswalk_v1.json"

def _find_local_manifest() -> Path | None:
    for p in _LOCAL_MANIFEST_DIR.glob("lfps_v2_collection_*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("api_version") == "LFPS v2" and data.get("geotiff_file"):
                return p
        except Exception:
            pass
    return None

_LOCAL_MANIFEST_PATH = _find_local_manifest()
_LOCAL_MANIFEST_PRESENT = _LOCAL_MANIFEST_PATH is not None
_CROSSWALK_PRESENT = _CROSSWALK_PATH.is_file()

_MOPT_CONDITION = _LOCAL_MANIFEST_PRESENT and _CROSSWALK_PRESENT

# Expected 17 Mescalero observed codes from inventory
_MESCALERO_EXPECTED_EVT_CODES = {
    7024, 7025, 7054, 7086, 7104, 7107, 7121,
    7146, 7256, 9017, 9035, 9329, 9519, 9535,
    9810, 9828, 9829,
}

@pytest.mark.skipif(
    not _MOPT_CONDITION,
    reason=(
        "M-opt requires the local Mescalero LFPS v2 manifest in outputs/ and "
        "project_data/crosswalks/mescalero_v1_evt_crosswalk_v1.json. "
        "Skipped in automated pipelines and fresh clones."
    ),
)
class TestMOptMescalero:
    """M-opt: Applies actual crosswalk to real Mescalero GeoTIFF sample."""

    def test_mopt_all_17_codes_accounted_for(self):
        """M-opt: All 17 observed Mescalero EVT codes are mapped (no unmapped)."""
        assert _LOCAL_MANIFEST_PATH is not None
        manifest = json.loads(_LOCAL_MANIFEST_PATH.read_text(encoding="utf-8"))
        crosswalk, err = _load_crosswalk("mescalero_v1_evt_crosswalk_v1.json")
        assert err == "", f"Crosswalk load error: {err}"

        report = _apply_evt_crosswalk(manifest, crosswalk)
        assert report["mapping_status"] == "complete", (
            f"Mapping failed with warnings: {report.get('warnings')}"
        )
        assert report["unmapped_evt_codes_seen"] == [], (
            f"Unexpected unmapped EVT codes: {report['unmapped_evt_codes_seen']}"
        )

    def test_mopt_acreage_closure(self):
        """M-opt: Actual raster closure passes for both rasters."""
        assert _LOCAL_MANIFEST_PATH is not None
        manifest = json.loads(_LOCAL_MANIFEST_PATH.read_text(encoding="utf-8"))
        crosswalk, err = _load_crosswalk("mescalero_v1_evt_crosswalk_v1.json")
        assert err == ""

        report = _apply_evt_crosswalk(manifest, crosswalk)
        closure = report["acreage_closure"]
        assert closure["cover_type_valid_sum_matches"] is True, str(closure)
        assert closure["forest_land_valid_sum_matches"] is True, str(closure)
        assert closure["total_pixel_sum_matches"] is True, str(closure)

    def test_mopt_correct_total_valid_cells(self):
        """M-opt: Total valid cells match expected 1,681 from inventory."""
        assert _LOCAL_MANIFEST_PATH is not None
        manifest = json.loads(_LOCAL_MANIFEST_PATH.read_text(encoding="utf-8"))
        crosswalk, err = _load_crosswalk("mescalero_v1_evt_crosswalk_v1.json")
        assert err == ""

        report = _apply_evt_crosswalk(manifest, crosswalk)
        assert report["valid_cell_count"] == 1681, (
            f"Expected 1681 valid cells, got {report['valid_cell_count']}"
        )

    def test_mopt_sentinels_correct(self):
        """M-opt: All mapping sentinels have correct values."""
        assert _LOCAL_MANIFEST_PATH is not None
        manifest = json.loads(_LOCAL_MANIFEST_PATH.read_text(encoding="utf-8"))
        crosswalk, err = _load_crosswalk("mescalero_v1_evt_crosswalk_v1.json")
        assert err == ""

        report = _apply_evt_crosswalk(manifest, crosswalk)
        assert report["classification_performed"] is True
        assert report["crosswalk_applied"] is True
        assert report["candidate_cover_types_produced"] is True
        assert report["candidate_forest_land_produced"] is True
        assert report["field_inventory_performed"] is False
        assert report["authoritative_forest_land_determination_performed"] is False
        assert report["candidate_polygons_produced"] is False
