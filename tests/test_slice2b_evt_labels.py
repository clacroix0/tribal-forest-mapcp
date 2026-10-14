# tests/test_slice2b_evt_labels.py
#
# Slice 2b — LF2025 EVT Reference Join
#
# Tests for _load_lf2025_evt_labels() and the label-join logic inside
# _inspect_landfire_v2_inputs().
#
# All committed tests are synthetic and independent of Mescalero data.
# One conditional test (T-5) runs only when the local cached ADD CSV and
# a local LFPS v2 collection manifest are both present.
#
# No classification, crosswalk, candidate layers, or forest-land outputs.
# Run with:  pytest tests/test_slice2b_evt_labels.py -v

import csv
import io
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from server import (
    LF2025_EVT_ADD_URL,
    LF2025_EVT_ADD_CACHE_RELPATH,
    _load_lf2025_evt_labels,
    _inspect_landfire_v2_inputs,
    inspect_landfire_v2_cover_type_inputs,
    OUTPUT_FOLDER,
)
from mcp.server.mcpserver.exceptions import ToolError

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_SYNTH_EPSG = 5070
_SYNTH_TRANSFORM = from_origin(-885825.0, 1171005.0, 30.0, 30.0)
_SYNTH_JOB_ID_LBL = "cccccccc-dddd-eeee-ffff-000000000000"

# The 17 Mescalero EVT codes observed in the actual Mescalero LFPS v2 sample.
# Used only in the conditional T-5 test; never applied as a crosswalk.
_MESCALERO_EVT_CODES = [
    7010, 7024, 7026, 7043, 7052, 7053, 7063, 7069,
    7070, 7071, 7101, 7102, 7103, 7110, 7114, 7175, 7297,
]

# ---------------------------------------------------------------------------
# Synthetic raster and manifest builders (independent of test_server.py)
# ---------------------------------------------------------------------------

def _build_synthetic_tif(tmp_path: Path, evt_codes: list[int], nodata: int = -9999) -> Path:
    """SYNTHETIC: write a minimal 4x4 three-band GeoTIFF containing the given EVT codes."""
    n = len(evt_codes)
    # Fill a 4x4 grid with the supplied codes (cycle if fewer than 16)
    flat = [evt_codes[i % n] for i in range(15)] + [nodata]
    evt_data = np.array(flat, dtype=np.int32).reshape(4, 4)
    evc_data = np.full((4, 4), 111, dtype=np.int32)
    evh_data = np.full((4, 4), 105, dtype=np.int32)
    evc_data[3, 3] = nodata
    evh_data[3, 3] = nodata

    tif_path = tmp_path / "synth_lbl.tif"
    crs = CRS.from_epsg(_SYNTH_EPSG)
    with rasterio.open(
        str(tif_path), "w",
        driver="GTiff", height=4, width=4, count=3,
        dtype=np.int32, crs=crs, transform=_SYNTH_TRANSFORM, nodata=nodata,
    ) as dst:
        dst.write(evt_data, 1)
        dst.write(evc_data, 2)
        dst.write(evh_data, 3)
    with rasterio.open(str(tif_path), "r+") as dst:
        dst.descriptions = ("LF2025_EVT_CONUS", "LF2025_EVC_CONUS", "LF2025_EVH_CONUS")
    return tif_path


def _build_minimal_xml(tmp_path: Path, tag: str) -> Path:
    """SYNTHETIC: minimal XML for EVT, EVC, or EVH."""
    titles = {"EVT": "SYNTHETIC EVT LF 2025", "EVC": "SYNTHETIC EVC LF 2025", "EVH": "SYNTHETIC EVH LF 2025"}
    rdoms = {"EVT": (4401, 9994), "EVC": (11, 399), "EVH": (11, 310)}
    rmin, rmax = rdoms[tag]
    content = f"""<?xml version='1.0' encoding='UTF-8'?>
<metadata>
  <idinfo><citation><citeinfo>
    <title>{titles[tag]}</title><edition>LF 2025</edition>
    <pubdate>20260430</pubdate>
    <onlink>https://doi.org/10.5066/SYNTHETIC</onlink>
  </citeinfo></citation></idinfo>
  <eainfo><detailed><attr>
    <attrlabl>VALUE</attrlabl>
    <attrdef>Code.</attrdef>
    <attrdomv><edom><edomv>-9999</edomv><edomvd>Fill-NoData</edomvd></edom></attrdomv>
    <attrdomv><rdom><rdommin>{rmin}</rdommin><rdommax>{rmax}</rdommax></rdom></attrdomv>
  </attr>
  <attr><attrlabl>CLASSNAMES</attrlabl><attrdef>Name.</attrdef>
    <attrdomv><udom>See LF ADD CSV.</udom></attrdomv>
  </attr></detailed></eainfo>
</metadata>"""
    p = tmp_path / f"LF2025_{tag}_CONUS.xml"
    p.write_text(content, encoding="utf-8")
    return p


def _build_manifest(tmp_path, tif_path, evt_xml, evc_xml, evh_xml, job_id=_SYNTH_JOB_ID_LBL):
    """SYNTHETIC: build and write a minimal LFPS v2 collection manifest."""
    manifest = {
        "status": "bundle_collected_requires_gis_review",
        "api_version": "LFPS v2",
        "job_id": job_id,
        "geotiff_file": str(tif_path),
        "expected_metadata_xml_files": {
            "LF2025_EVT_CONUS.xml": str(evt_xml),
            "LF2025_EVC_CONUS.xml": str(evc_xml),
            "LF2025_EVH_CONUS.xml": str(evh_xml),
        },
    }
    folder = tmp_path / "outputs"
    folder.mkdir(exist_ok=True)
    fname = f"lfps_v2_collection_20260101T000000000000Z_{job_id}.json"
    p = folder / fname
    p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest, p, fname


def _build_add_csv_bytes(rows: list[dict]) -> bytes:
    """Return UTF-8-SIG-encoded bytes for a minimal ADD CSV with required columns."""
    buf = io.StringIO()
    cols = ["VALUE", "EVT_NAME", "EVT_LF", "EVT_PHYS", "EVT_GP_N", "SAF_SRM"]
    writer = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def _full_fixture(tmp_path, evt_codes=None):
    """Return (manifest_dict, manifest_path) for a full synthetic fixture."""
    if evt_codes is None:
        evt_codes = [7101, 7102]
    tif = _build_synthetic_tif(tmp_path, evt_codes)
    evt_xml = _build_minimal_xml(tmp_path, "EVT")
    evc_xml = _build_minimal_xml(tmp_path, "EVC")
    evh_xml = _build_minimal_xml(tmp_path, "EVH")
    return _build_manifest(tmp_path, tif, evt_xml, evc_xml, evh_xml)


# ---------------------------------------------------------------------------
# Helpers for patching _load_lf2025_evt_labels
# ---------------------------------------------------------------------------

def _make_label_map(codes: list[int], suffix: str = "") -> dict:
    """Return a synthetic label_map for the given codes."""
    return {
        c: {
            "evt_name": f"Synthetic Vegetation {c}{suffix}",
            "evt_lf": "Conifer",
            "evt_phys": "Woodland",
            "evt_gp_n": "Piñon-Juniper",
            "saf_srm": "239",
        }
        for c in codes
    }


def _make_provenance(source: str = "download") -> dict:
    return {
        "url": LF2025_EVT_ADD_URL,
        "source": source,
        "download_date": "2026-01-01T00:00:00Z",
        "sha256": "a" * 64,
        "row_count": 100,
        "cache_path": "/fake/path/LF2025_EVT.csv",
        "contact_email_supplied": False,
    }


# ===========================================================================
# T-1: Join success — all observed codes resolved
# ===========================================================================

class TestT1JoinSuccess:
    """T-1: All observed EVT codes present in ADD CSV → label_missing=false."""

    def test_t1_all_codes_resolved(self, tmp_path):
        """T-1: All synthetic codes found in ADD CSV → label_missing=False, labels populated."""
        codes = [7101, 7102]
        label_map = _make_label_map(codes)
        prov = _make_provenance()

        manifest, manifest_path, _ = _full_fixture(tmp_path, evt_codes=codes)

        with patch("server._load_lf2025_evt_labels", return_value=(label_map, prov, "")):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        assert result["inspection_status"] in ("success", "partial")
        observed = result["evt_band"]["evt_codes_observed"]
        assert len(observed) > 0

        for entry in observed:
            assert entry["label_missing"] is False, (
                f"Code {entry['evt_code']} should have label_missing=False"
            )
            assert entry["evt_name"] is not None, (
                f"Code {entry['evt_code']} should have evt_name"
            )
            assert entry["evt_name_source"] == "LF2025_EVT.csv", (
                f"Code {entry['evt_code']} should have evt_name_source='LF2025_EVT.csv'"
            )
            assert entry["evt_lf"] is not None
            assert entry["evt_phys"] is not None
            assert entry["evt_gp_n"] is not None
            assert entry["saf_srm"] is not None

    def test_t1_no_per_code_label_warning_when_all_resolved(self, tmp_path):
        """T-1: No label-missing warning when all codes are found."""
        codes = [7101, 7102]
        label_map = _make_label_map(codes)
        prov = _make_provenance()

        manifest, manifest_path, _ = _full_fixture(tmp_path, evt_codes=codes)

        with patch("server._load_lf2025_evt_labels", return_value=(label_map, prov, "")):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        warnings_text = " ".join(result.get("warnings", []))
        assert "label_missing=true" not in warnings_text, (
            "No per-code label-missing warning should appear when all codes are resolved"
        )

    def test_t1_evt_add_provenance_present(self, tmp_path):
        """T-1: evt_add_provenance block is present in evt_band."""
        codes = [7101]
        label_map = _make_label_map(codes)
        prov = _make_provenance(source="download")

        manifest, manifest_path, _ = _full_fixture(tmp_path, evt_codes=codes)

        with patch("server._load_lf2025_evt_labels", return_value=(label_map, prov, "")):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        assert "evt_add_provenance" in result["evt_band"]
        p = result["evt_band"]["evt_add_provenance"]
        assert p["url"] == LF2025_EVT_ADD_URL
        assert p["source"] == "download"

    def test_t1_labels_are_source_attributes_not_crosswalk(self, tmp_path):
        """T-1: Sentinel fields confirm no crosswalk or candidate mapping occurred."""
        codes = [7101, 7102]
        label_map = _make_label_map(codes)
        prov = _make_provenance()

        manifest, manifest_path, _ = _full_fixture(tmp_path, evt_codes=codes)

        with patch("server._load_lf2025_evt_labels", return_value=(label_map, prov, "")):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        assert result["crosswalk_applied"] is False
        assert result["candidate_cover_types_produced"] is False
        assert result["candidate_polygons_produced"] is False
        assert result["forest_land_determination_performed"] is False
        assert result["classification_performed"] is False


# ===========================================================================
# T-2: Unknown code — individual per-code warning
# ===========================================================================

class TestT2UnknownCode:
    """T-2: One observed EVT code absent from ADD CSV → warning naming that code."""

    def test_t2_missing_code_label_missing_true(self, tmp_path):
        """T-2: Code absent from ADD CSV → label_missing=True for that code."""
        codes = [7101, 7102]
        # Only provide label for 7101; 7102 is absent
        label_map = _make_label_map([7101])
        prov = _make_provenance()

        manifest, manifest_path, _ = _full_fixture(tmp_path, evt_codes=codes)

        with patch("server._load_lf2025_evt_labels", return_value=(label_map, prov, "")):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        observed = {e["evt_code"]: e for e in result["evt_band"]["evt_codes_observed"]}
        assert observed[7101]["label_missing"] is False, "7101 should be resolved"
        assert observed[7102]["label_missing"] is True, "7102 should be missing"

    def test_t2_warning_names_missing_code(self, tmp_path):
        """T-2: Warning message names the specific missing code."""
        codes = [7101, 7102]
        label_map = _make_label_map([7101])
        prov = _make_provenance()

        manifest, manifest_path, _ = _full_fixture(tmp_path, evt_codes=codes)

        with patch("server._load_lf2025_evt_labels", return_value=(label_map, prov, "")):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        warnings_text = " ".join(result.get("warnings", []))
        assert "7102" in warnings_text, (
            "Warning must name the specific code that could not be resolved"
        )
        assert "label_missing=true" in warnings_text

    def test_t2_found_code_has_no_warning(self, tmp_path):
        """T-2: Found code produces no per-code warning."""
        codes = [7101, 7102]
        label_map = _make_label_map([7101])
        prov = _make_provenance()

        manifest, manifest_path, _ = _full_fixture(tmp_path, evt_codes=codes)

        with patch("server._load_lf2025_evt_labels", return_value=(label_map, prov, "")):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        # The warning must name 7102 but not label-missing-warn 7101
        per_code_warnings = [
            w for w in result.get("warnings", [])
            if "label_missing=true" in w and "7101" in w
        ]
        assert len(per_code_warnings) == 0, (
            "No per-code label-missing warning should appear for found code 7101"
        )

    def test_t2_partial_status_when_any_missing(self, tmp_path):
        """T-2: inspection_status is partial when any code is unresolved."""
        codes = [7101, 7102]
        label_map = _make_label_map([7101])
        prov = _make_provenance()

        manifest, manifest_path, _ = _full_fixture(tmp_path, evt_codes=codes)

        with patch("server._load_lf2025_evt_labels", return_value=(label_map, prov, "")):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        assert result["inspection_status"] == "partial"


# ===========================================================================
# T-3: Download failure — graceful degradation
# ===========================================================================

class TestT3DownloadFailure:
    """T-3: Failed download → tool completes, status not failed, aggregate warning."""

    def test_t3_tool_does_not_crash(self, tmp_path):
        """T-3: Download failure does not raise an exception."""
        manifest, manifest_path, _ = _full_fixture(tmp_path)
        fail_prov = {
            "url": LF2025_EVT_ADD_URL,
            "source": None,
            "download_date": None,
            "sha256": None,
            "row_count": None,
            "cache_path": "/fake/path/LF2025_EVT.csv",
            "contact_email_supplied": False,
        }
        with patch(
            "server._load_lf2025_evt_labels",
            return_value=({}, fail_prov, "Connection refused: simulated failure"),
        ):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        assert result is not None
        assert "inspection_status" in result

    def test_t3_status_not_failed(self, tmp_path):
        """T-3: inspection_status is 'partial', never 'failed', on download error."""
        manifest, manifest_path, _ = _full_fixture(tmp_path)
        fail_prov = {"url": LF2025_EVT_ADD_URL, "source": None, "sha256": None,
                     "row_count": None, "download_date": None,
                     "cache_path": "/fake", "contact_email_supplied": False}

        with patch(
            "server._load_lf2025_evt_labels",
            return_value=({}, fail_prov, "SIMULATED_DOWNLOAD_FAILURE"),
        ):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        assert result["inspection_status"] != "failed", (
            "Download failure must not downgrade inspection_status to 'failed'"
        )
        assert result["inspection_status"] == "partial"

    def test_t3_label_missing_true_all_codes(self, tmp_path):
        """T-3: All observed codes have label_missing=True when download failed."""
        manifest, manifest_path, _ = _full_fixture(tmp_path, evt_codes=[7101, 7102])
        fail_prov = {"url": LF2025_EVT_ADD_URL, "source": None, "sha256": None,
                     "row_count": None, "download_date": None,
                     "cache_path": "/fake", "contact_email_supplied": False}

        with patch(
            "server._load_lf2025_evt_labels",
            return_value=({}, fail_prov, "SIMULATED_DOWNLOAD_FAILURE"),
        ):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        for entry in result["evt_band"]["evt_codes_observed"]:
            assert entry["label_missing"] is True, (
                f"Code {entry['evt_code']} should have label_missing=True after download failure"
            )
            assert entry["evt_name"] is None
            assert entry["evt_name_source"] is None

    def test_t3_aggregate_warning_present(self, tmp_path):
        """T-3: One aggregate reference-data warning is present on failure."""
        manifest, manifest_path, _ = _full_fixture(tmp_path)
        fail_prov = {"url": LF2025_EVT_ADD_URL, "source": None, "sha256": None,
                     "row_count": None, "download_date": None,
                     "cache_path": "/fake", "contact_email_supplied": False}

        with patch(
            "server._load_lf2025_evt_labels",
            return_value=({}, fail_prov, "SIMULATED_DOWNLOAD_FAILURE"),
        ):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        ref_warnings = [
            w for w in result.get("warnings", [])
            if "Reference-data warning" in w
        ]
        assert len(ref_warnings) == 1, (
            "Exactly one aggregate reference-data warning should be present"
        )
        assert LF2025_EVT_ADD_URL in ref_warnings[0], (
            "Aggregate warning must record the attempted URL"
        )

    def test_t3_no_labels_claimed(self, tmp_path):
        """T-3: No code has evt_name_source='LF2025_EVT.csv' after download failure."""
        manifest, manifest_path, _ = _full_fixture(tmp_path, evt_codes=[7101, 7102])
        fail_prov = {"url": LF2025_EVT_ADD_URL, "source": None, "sha256": None,
                     "row_count": None, "download_date": None,
                     "cache_path": "/fake", "contact_email_supplied": False}

        with patch(
            "server._load_lf2025_evt_labels",
            return_value=({}, fail_prov, "SIMULATED_DOWNLOAD_FAILURE"),
        ):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        for entry in result["evt_band"]["evt_codes_observed"]:
            assert entry.get("evt_name_source") != "LF2025_EVT.csv", (
                "Labels must not be claimed as resolved after download failure"
            )


# ===========================================================================
# T-4: Checksum recorded in provenance
# ===========================================================================

class TestT4ChecksumRecorded:
    """T-4: Download/cache path records SHA-256, row_count, url, download_date."""

    def test_t4_provenance_fields_present_on_success(self, tmp_path):
        """T-4: Provenance block has all required fields when labels are resolved."""
        codes = [7101, 7102]
        label_map = _make_label_map(codes)
        prov = {
            "url": LF2025_EVT_ADD_URL,
            "source": "download",
            "download_date": "2026-06-01T12:00:00Z",
            "sha256": "b" * 64,
            "row_count": 11234,
            "cache_path": "/fake/LF2025_EVT.csv",
            "contact_email_supplied": False,
        }

        manifest, manifest_path, _ = _full_fixture(tmp_path, evt_codes=codes)

        with patch("server._load_lf2025_evt_labels", return_value=(label_map, prov, "")):
            result = _inspect_landfire_v2_inputs(manifest, manifest_path)

        evt_prov = result["evt_band"]["evt_add_provenance"]
        assert evt_prov["sha256"] == "b" * 64, "sha256 must be recorded"
        assert evt_prov["row_count"] == 11234, "row_count must be recorded"
        assert evt_prov["url"] == LF2025_EVT_ADD_URL, "url must match allowlisted URL"
        assert evt_prov["download_date"] == "2026-06-01T12:00:00Z"
        assert evt_prov["contact_email_supplied"] is False

    def test_t4_load_function_returns_sha256_from_real_bytes(self, tmp_path):
        """T-4: _load_lf2025_evt_labels computes SHA-256 from actual bytes."""
        import hashlib

        rows = [
            {"VALUE": "7101", "EVT_NAME": "Piñon-Juniper", "EVT_LF": "Conifer",
             "EVT_PHYS": "Woodland", "EVT_GP_N": "PJ", "SAF_SRM": "239"},
        ]
        csv_bytes = _build_add_csv_bytes(rows)
        expected_sha = hashlib.sha256(csv_bytes).hexdigest()

        cache_dir = tmp_path / "project_data"
        cache_file = cache_dir / LF2025_EVT_ADD_CACHE_RELPATH
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(csv_bytes)

        label_map, provenance, error = _load_lf2025_evt_labels(cache_dir=cache_dir)

        assert error == "", f"Expected no error, got: {error}"
        assert provenance["sha256"] == expected_sha, (
            "SHA-256 must match the actual bytes"
        )
        assert provenance["source"] == "cache"
        assert provenance["row_count"] == 1
        assert 7101 in label_map
        assert label_map[7101]["evt_name"] == "Piñon-Juniper"

    def test_t4_fill_nodata_code_excluded_from_map(self, tmp_path):
        """T-4: VALUE=-9999 is treated as Fill-NoData and excluded from label_map."""
        rows = [
            {"VALUE": "-9999", "EVT_NAME": "Fill-NoData", "EVT_LF": "",
             "EVT_PHYS": "", "EVT_GP_N": "", "SAF_SRM": ""},
            {"VALUE": "7101", "EVT_NAME": "Piñon-Juniper", "EVT_LF": "Conifer",
             "EVT_PHYS": "Woodland", "EVT_GP_N": "PJ", "SAF_SRM": "239"},
        ]
        csv_bytes = _build_add_csv_bytes(rows)

        cache_dir = tmp_path / "project_data"
        cache_file = cache_dir / LF2025_EVT_ADD_CACHE_RELPATH
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(csv_bytes)

        label_map, provenance, error = _load_lf2025_evt_labels(cache_dir=cache_dir)

        assert error == ""
        assert -9999 not in label_map, "-9999 fill value must not appear in label_map"
        assert 7101 in label_map

    def test_t4_duplicate_non_nodata_rows_returns_error(self, tmp_path):
        """T-4: Duplicate non-NoData VALUE rows produce an error, not a silent choice."""
        rows = [
            {"VALUE": "7101", "EVT_NAME": "Name A", "EVT_LF": "Conifer",
             "EVT_PHYS": "Woodland", "EVT_GP_N": "PJ", "SAF_SRM": "239"},
            {"VALUE": "7101", "EVT_NAME": "Name B", "EVT_LF": "Conifer",
             "EVT_PHYS": "Woodland", "EVT_GP_N": "PJ", "SAF_SRM": "239"},
        ]
        csv_bytes = _build_add_csv_bytes(rows)

        cache_dir = tmp_path / "project_data"
        cache_file = cache_dir / LF2025_EVT_ADD_CACHE_RELPATH
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(csv_bytes)

        label_map, provenance, error = _load_lf2025_evt_labels(cache_dir=cache_dir)

        assert label_map == {}, "label_map must be empty on duplicate-row error"
        assert "duplicate" in error.lower(), (
            f"Error message must mention duplicates; got: {error}"
        )

    def test_t4_missing_required_column_returns_error(self, tmp_path):
        """T-4: CSV missing a required column returns an error."""
        # Build CSV without SAF_SRM
        buf = io.StringIO()
        cols = ["VALUE", "EVT_NAME", "EVT_LF", "EVT_PHYS", "EVT_GP_N"]  # SAF_SRM absent
        writer = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
        writer.writeheader()
        writer.writerow({"VALUE": "7101", "EVT_NAME": "X", "EVT_LF": "X",
                         "EVT_PHYS": "X", "EVT_GP_N": "X"})
        csv_bytes = ("\ufeff" + buf.getvalue()).encode("utf-8")

        cache_dir = tmp_path / "project_data"
        cache_file = cache_dir / LF2025_EVT_ADD_CACHE_RELPATH
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(csv_bytes)

        label_map, provenance, error = _load_lf2025_evt_labels(cache_dir=cache_dir)

        assert label_map == {}
        assert "SAF_SRM" in error or "missing" in error.lower()

    def test_t4_cache_used_before_download(self, tmp_path):
        """T-4: Cache is read first; no download attempted when cache exists."""
        rows = [
            {"VALUE": "7101", "EVT_NAME": "Cached Name", "EVT_LF": "Conifer",
             "EVT_PHYS": "Woodland", "EVT_GP_N": "PJ", "SAF_SRM": "239"},
        ]
        csv_bytes = _build_add_csv_bytes(rows)

        cache_dir = tmp_path / "project_data"
        cache_file = cache_dir / LF2025_EVT_ADD_CACHE_RELPATH
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(csv_bytes)

        # httpx should never be called
        with patch("server.httpx.Client") as mock_client:
            label_map, provenance, error = _load_lf2025_evt_labels(cache_dir=cache_dir)
            mock_client.assert_not_called()

        assert provenance["source"] == "cache"
        assert 7101 in label_map


# ===========================================================================
# T-5: Conditional local test — all 17 Mescalero codes resolve
# ===========================================================================

_REPO_ROOT = Path(__file__).parent.parent
_REAL_CACHE_PATH = _REPO_ROOT / "project_data" / LF2025_EVT_ADD_CACHE_RELPATH
_MESCALERO_OUTPUT_DIR = _REPO_ROOT / "outputs"

def _find_local_mescalero_inventory_csv() -> Path | None:
    """Find the local Mescalero EVT inventory CSV in outputs/."""
    for p in _MESCALERO_OUTPUT_DIR.glob("inspect_lf2025_*_evt_inventory.csv"):
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None

_LOCAL_CACHE_PRESENT = _REAL_CACHE_PATH.is_file()
_LOCAL_INVENTORY_CSV = _find_local_mescalero_inventory_csv()
_LOCAL_INVENTORY_PRESENT = _LOCAL_INVENTORY_CSV is not None

_T5_CONDITION = _LOCAL_CACHE_PRESENT and _LOCAL_INVENTORY_PRESENT


@pytest.mark.skipif(
    not _T5_CONDITION,
    reason=(
        "T-5 requires both the local LF2025 EVT ADD CSV cache at "
        f"project_data/reference_data/landfire/LF2025_EVT.csv "
        "and a local Mescalero EVT inventory CSV in outputs/. "
        "Skipped in automated pipelines and fresh clones."
    ),
)
class TestT5ConditionalMescaleroLabels:
    """T-5: All 17 observed Mescalero EVT codes resolve from the local cache."""

    def test_t5_all_17_mescalero_codes_resolve(self):
        """T-5: Every Mescalero observed code has label_missing=False from the local cache."""
        # Read observed codes from the actual inventory CSV (do not apply crosswalk)
        assert _LOCAL_INVENTORY_CSV is not None
        observed_codes = []
        with _LOCAL_INVENTORY_CSV.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    observed_codes.append(int(row["evt_code"]))
                except (KeyError, ValueError):
                    pass

        assert len(observed_codes) > 0, "Inventory CSV must contain at least one EVT code"

        # Load labels from the real local cache (no mock, no download)
        label_map, provenance, error = _load_lf2025_evt_labels(
            cache_dir=_REPO_ROOT / "project_data"
        )

        assert error == "", f"Label load failed: {error}"
        assert provenance["source"] == "cache", "Must use local cache for T-5"

        unresolved = [c for c in observed_codes if c not in label_map]

        assert unresolved == [], (
            f"The following observed Mescalero EVT codes were not found in "
            f"LF2025_EVT.csv: {unresolved}. "
            "All 17 codes must resolve."
        )

    def test_t5_no_crosswalk_performed(self):
        """T-5: Confirmed — label resolution is source attribution only, not a crosswalk."""
        # This test is a sentinel. Labels are LANDFIRE source attributes.
        # No Mescalero cover-type assignment, candidate class, or forest-land
        # determination is made here.
        assert _LOCAL_INVENTORY_CSV is not None
        with _LOCAL_INVENTORY_CSV.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = set(reader.fieldnames or [])

        # The inventory CSV must not contain crosswalk or candidate columns
        disallowed = {
            "candidate_class", "cover_type", "forest_land",
            "mescalero_code", "crosswalk",
        }
        found_disallowed = disallowed & fieldnames
        assert not found_disallowed, (
            f"EVT inventory CSV must not contain crosswalk columns: {found_disallowed}"
        )
