"""Synthetic geometry and file-adapter tests; not field validation or real-raster evaluation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from shapely.geometry import box, Polygon

# Supports both the intended repository layout and a flat downloaded-file layout.
ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "cover_type_generalization.py").is_file():
    ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cover_type_generalization as gen

UNIVERSAL = "disturbance_not_evaluated|overstory_understory_not_modeled|professional_forestry_review_required"
PROVENANCE = {
    "crosswalk_id": "synthetic",
    "crosswalk_version": "v1",
    "cover_scheme_id": "mescalero_v1",
    "cover_scheme_version": "v1",
}
CODES = {
    "candidate_P": 1,
    "candidate_PJ": 2,
    "candidate_G": 3,
    "candidate_RIP_WOODY": 4,
    "unmapped_evt": 5,
    "candidate_NT": 6,
    "candidate_NW": 7,
    "candidate_WA": 8,
    "candidate_RIP_NONFOREST": 9,
    "candidate_RIP_UNCERTAIN": 10,
}


def make_frame(items):
    rows = []
    for number, label, geometry, *extra in items:
        flags = extra[0] if extra else UNIVERSAL
        if label in {
            "candidate_G",
            "candidate_WA",
            "candidate_RIP_NONFOREST",
        }:
            status = "nonforest"
        elif label in {
            "unmapped_evt",
            "candidate_RIP_UNCERTAIN",
        }:
            status = "unknown"
        else:
            status = "forest_land"
        rows.append({"patch_id": f"CTP_{number:06d}", "output_code": CODES[label],
                     "output_label": label, "forest_land_status": status,
                     "area_m2": float(geometry.area), "area_acres": float(geometry.area / gen.ACRE_M2),
                     "review_flags": flags, "geometry_stage": "raw", **PROVENANCE, "geometry": geometry})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:5070")


def basic():
    return make_frame([(1, "candidate_P", box(0, 0, 100, 100)),
                       (2, "candidate_PJ", box(100, 0, 130, 30))])


def result(frame=None, **settings):
    return gen.generalize_frame(basic() if frame is None else frame, gen.GeneralizationSettings(**settings))


def test_basic_merge_and_composition():
    units, members, composition, qc = result()
    assert len(units) == 1 and qc["merged_patch_count"] == 1
    assert units.display_output_label.iloc[0] == "candidate_P"
    assert bool(units.contains_multiple_classes.iloc[0])
    assert members.set_index("patch_id").loc["CTP_000002", "anchor_patch_id"] == "CTP_000001"
    assert dict(zip(composition.original_output_label, composition.area_m2)) == {"candidate_P": 10000, "candidate_PJ": 900}
    assert np.isclose(composition.percent_of_unit.sum(), 100)
    assert qc["hard_boundaries_evaluated"] is False


def test_universal_limitations_do_not_block_merge():
    units, _, _, qc = result()
    assert qc["merged_patch_count"] == 1
    assert set(UNIVERSAL.split("|")) <= set(units.review_flags.iloc[0].split("|"))


def test_threshold_equality_source_is_not_small():
    frame = make_frame([(1, "candidate_P", box(0, 0, 200, 100)),
                        (2, "candidate_PJ", box(200, 0, 300, 100))])
    assert result(frame)[3]["merged_patch_count"] == 0
    assert set(result(frame)[1].reason) == {"at_or_above_threshold"}


def test_threshold_changes_from_same_baseline():
    frame = make_frame([(1, "candidate_P", box(0, 0, 200, 100)),
                        (2, "candidate_PJ", box(200, 0, 310, 100))])
    assert result(frame)[3]["merged_patch_count"] == 0
    assert result(frame, small_patch_threshold_m2=12000.0)[3]["merged_patch_count"] == 1
    assert len(frame) == 2 and frame.area_m2.tolist() == [20000, 11000]


def test_longest_boundary_before_largest_area():
    frame = make_frame([(1, "candidate_P", box(-100, 0, 0, 100)),
                        (2, "candidate_P", box(30, 10, 230, 110)),
                        (3, "candidate_PJ", box(0, 0, 30, 30))])
    members = result(frame)[1].set_index("patch_id")
    assert members.loc["CTP_000003", "anchor_patch_id"] == "CTP_000001"
    assert members.loc["CTP_000003", "shared_boundary_with_anchor_m"] == 30


def test_largest_original_area_breaks_boundary_tie():
    frame = make_frame([(1, "candidate_P", box(-100, 0, 0, 100)),
                        (2, "candidate_P", box(30, 0, 230, 100)),
                        (3, "candidate_PJ", box(0, 0, 30, 30))])
    assert result(frame)[1].set_index("patch_id").loc["CTP_000003", "anchor_patch_id"] == "CTP_000002"


def test_stable_id_breaks_full_tie():
    frame = make_frame([(1, "candidate_P", box(-100, 0, 0, 100)),
                        (2, "candidate_P", box(30, 0, 130, 100)),
                        (3, "candidate_PJ", box(0, 0, 30, 30))])
    assert result(frame)[1].set_index("patch_id").loc["CTP_000003", "anchor_patch_id"] == "CTP_000001"


def test_numerical_boundary_tie_tolerance():
    delta = gen.EDGE_TOLERANCE_M / 2
    frame = make_frame([(1, "candidate_P", box(-100, 0, 0, 100)),
                        (2, "candidate_P", box(30, -delta, 530, 30 - delta)),
                        (3, "candidate_PJ", box(0, 0, 30, 30))])
    # Right has a slightly shorter edge but a larger area, within the defined tie tolerance.
    assert result(frame)[1].set_index("patch_id").loc["CTP_000003", "anchor_patch_id"] == "CTP_000002"


def test_corner_contact_does_not_merge():
    frame = make_frame([(1, "candidate_P", box(0, 0, 100, 100)),
                        (2, "candidate_PJ", box(100, 100, 130, 130))])
    assert result(frame)[3]["merged_patch_count"] == 0
    assert "no_eligible_edge_sharing_anchor" in result(frame)[1].reason.tolist()


def test_small_only_group_remains_separate():
    frame = make_frame([(1, "candidate_P", box(0, 0, 30, 30)),
                        (2, "candidate_PJ", box(30, 0, 60, 30))])
    assert len(result(frame)[0]) == 2
    assert result(frame)[3]["merged_patch_count"] == 0


def test_no_cascading_through_first_inclusion():
    frame = make_frame([(1, "candidate_P", box(0, 0, 100, 100)),
                        (2, "candidate_PJ", box(100, 0, 130, 30)),
                        (3, "candidate_PJ", box(130, 0, 160, 30))])
    units, members, _, qc = result(frame)
    assert len(units) == 2 and qc["merged_patch_count"] == 1
    assert members.set_index("patch_id").loc["CTP_000003", "role"] == "standalone"


@pytest.mark.parametrize("which", [0, 1])
def test_explicit_exclusion_blocks_source_or_anchor(which):
    assert result(excluded_patch_ids=[f"CTP_{which + 1:06d}"])[3]["merged_patch_count"] == 0


@pytest.mark.parametrize("which", [0, 1])
def test_additional_protection_blocks_source_or_anchor(which):
    assert result(additional_protected_patch_ids=[f"CTP_{which + 1:06d}"])[3]["merged_patch_count"] == 0


@pytest.mark.parametrize("which", [0, 1])
def test_conflict_flag_blocks_source_or_anchor(which):
    frame = basic()
    frame.loc[which, "review_flags"] += "|evc_evh_structure_conflict"
    assert result(frame)[3]["merged_patch_count"] == 0


@pytest.mark.parametrize(
    "label",
    [
        "candidate_G",
        "candidate_RIP_WOODY",
        "unmapped_evt",
        "candidate_NT",
        "candidate_NW",
        "candidate_WA",
        "candidate_RIP_NONFOREST",
        "candidate_RIP_UNCERTAIN",
    ],
)
def test_incompatible_classes_never_merge(label):
    frame = make_frame([(1, "candidate_P", box(0, 0, 100, 100)),
                        (2, label, box(100, 0, 130, 30))])
    units, _, _, qc = result(frame)
    assert len(units) == 2 and qc["merged_patch_count"] == 0


def test_enclosed_protected_patch_is_preserved():
    hole = box(40, 40, 70, 70)
    shell = Polygon(box(0, 0, 120, 120).exterior.coords, [hole.exterior.coords])
    frame = make_frame([(1, "candidate_P", shell),
                        (2, "candidate_RIP_WOODY", hole, UNIVERSAL + "|riparian_feature_preserved")])
    units, _, _, qc = result(frame)
    anchor = units.set_index("anchor_patch_id").loc["CTP_000001", "geometry"]
    assert anchor.equals(shell) and len(anchor.interiors) == 1
    assert qc["merged_patch_count"] == 0


def test_nodata_hole_and_footprint_are_preserved():
    hole = box(40, 40, 70, 70)
    shell = Polygon(box(0, 0, 120, 120).exterior.coords, [hole.exterior.coords])
    frame = make_frame([(1, "candidate_P", shell),
                        (2, "candidate_PJ", box(120, 0, 150, 30))])
    units, _, _, qc = result(frame)
    assert len(units.geometry.iloc[0].interiors) == 1
    assert units.geometry.iloc[0].intersection(hole).area == 0
    assert qc["gap_m2"] == qc["extra_coverage_m2"] == qc["overlap_m2"] == 0


def test_anchor_label_can_differ_from_majority_composition():
    frame = make_frame([(1, "candidate_P", box(0, 0, 100, 100)),
                        (2, "candidate_PJ", box(100, 0, 190, 100)),
                        (3, "candidate_PJ", box(0, -90, 100, 0))])
    units, membership, composition, qc = result(frame)
    assert len(units) == 1 and qc["merged_patch_count"] == 2
    assert units.display_output_label.iloc[0] == "candidate_P"
    assert composition.set_index("original_output_label").loc["candidate_PJ", "area_m2"] == 18000
    assert set(membership.patch_id) == set(frame.patch_id)


def test_row_order_does_not_change_results():
    frame = make_frame([(1, "candidate_P", box(-100, 0, 0, 100)),
                        (2, "candidate_P", box(30, 0, 130, 100)),
                        (3, "candidate_PJ", box(0, 0, 30, 30))])
    first, members1, comp1, qc1 = result(frame)
    second, members2, comp2, qc2 = result(frame.sample(frac=1, random_state=41))
    pd.testing.assert_frame_equal(members1, members2)
    pd.testing.assert_frame_equal(comp1, comp2)
    assert all(a.equals(b) for a, b in zip(first.geometry, second.geometry))
    assert qc1 == qc2


def test_source_label_subset_is_respected():
    assert result(eligible_source_labels=["candidate_P"])[3]["merged_patch_count"] == 0


@pytest.mark.parametrize("threshold", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_threshold_rejected(threshold):
    with pytest.raises(ValidationError):
        gen.GeneralizationSettings(small_patch_threshold_m2=threshold)


def test_unknown_settings_and_barrier_requests_rejected():
    with pytest.raises(ValidationError):
        gen.GeneralizationSettings(hard_boundary_file="roads.gpkg")
    with pytest.raises(ValidationError):
        gen.GeneralizationSettings(eligible_source_labels=["candidate_G"])


@pytest.mark.parametrize("field", ["excluded_patch_ids", "additional_protected_patch_ids"])
def test_unknown_ids_rejected(field):
    with pytest.raises(gen.GeneralizationValidationError):
        result(**{field: ["CTP_999999"]})


def test_duplicate_eligible_labels_rejected():
    with pytest.raises(gen.GeneralizationValidationError):
        result(eligible_source_labels=["candidate_P", "candidate_P"])


def test_duplicate_patch_ids_rejected():
    frame = basic()
    frame.loc[1, "patch_id"] = frame.patch_id.iloc[0]
    with pytest.raises(gen.GeneralizationValidationError):
        result(frame)


def test_area_mismatch_rejected():
    frame = basic()
    frame.loc[1, "area_m2"] = 901
    with pytest.raises(gen.GeneralizationValidationError):
        result(frame)


def test_crs_mismatch_rejected():
    with pytest.raises(gen.GeneralizationValidationError):
        result(basic().set_crs("EPSG:3857", allow_override=True))


def test_overlap_rejected():
    frame = make_frame([(1, "candidate_P", box(0, 0, 100, 100)),
                        (2, "candidate_PJ", box(90, 0, 120, 30))])
    with pytest.raises(gen.GeneralizationValidationError):
        result(frame)


def test_invalid_geometry_rejected():
    frame = basic()
    frame.loc[1, "geometry"] = Polygon([(100, 0), (130, 30), (100, 30), (130, 0), (100, 0)])
    with pytest.raises(gen.GeneralizationValidationError):
        result(frame)


def test_bad_forest_status_rejected():
    frame = basic()
    frame.loc[1, "forest_land_status"] = "unknown"
    with pytest.raises(gen.GeneralizationValidationError):
        result(frame)


def test_comparison_limit_failure(monkeypatch):
    monkeypatch.setattr(gen, "MAX_COMPARISONS", 0)
    with pytest.raises(gen.GeneralizationValidationError):
        result()


def synthetic_raw_run(root):
    """Synthetic adapter fixture. Source files are hash fixtures, NOT actual mapped rasters."""
    root.mkdir(exist_ok=True)
    name = "rawpatch_synthetic_v1"
    raw = root / name
    raw.mkdir()
    frame = basic()
    frame.to_file(raw / "raw_cover_type_patches.gpkg", layer=gen.RAW_LAYER, driver="GPKG", engine="pyogrio", index=False)
    source_files = {"cover_type_tif": "cmap_12345678_v1_cover_type_30m.tif",
                    "codebook_csv": "cmap_12345678_v1_cover_type_codebook.csv",
                    "slice3_methods": "cmap_12345678_v1_methods.json"}
    hashes = {}
    for key, filename in source_files.items():
        path = root / filename
        path.write_bytes(b"SYNTHETIC HASH FIXTURE, NOT REAL SOURCE DATA")
        hashes[key] = gen._digest(path)
    per_class = [{"output_code": int(code), "output_label": subset.output_label.iloc[0],
                  "forest_land_status": subset.forest_land_status.iloc[0], "patch_count": len(subset),
                  "square_meters": float(subset.geometry.area.sum())} for code, subset in frame.groupby("output_code")]
    report = {
        "document_type": "candidate_cover_type_raw_patch_qc", "status": "complete_review_required",
        "candidate_polygons_produced": True, "candidate_stands_produced": False,
        "new_classification_performed": False, "connectivity": 4, "patch_count": len(frame),
        "source_raster_filename": source_files["cover_type_tif"],
        "source_methods_filename": source_files["slice3_methods"], "source_sha256": hashes,
        **PROVENANCE,
        "qc": {"geometry_valid": True, "raster_roundtrip_matches": True,
               "per_class_closure_matches": True, "geopackage_readback_passed": True,
               "input_files_unchanged": True, "valid_area_m2": float(frame.geometry.area.sum()),
               "nodata_cells": 2, "nodata_acres": 1800 / gen.ACRE_M2, "per_class": per_class},
    }
    (raw / "raw_patch_qc.json").write_text(json.dumps(report), encoding="utf-8")
    return name, raw


def test_adapter_writes_and_verifies_outputs(tmp_path):
    name, raw = synthetic_raw_run(tmp_path)
    before = {p: gen._digest(p) for p in raw.iterdir()}
    output = gen.create_generalized_cover_type_patches(tmp_path, gen.GeneralizationRequest(raw_run_directory=name))
    assert output.status == "complete_review_required", output.errors
    assert output.merged_patch_count == 1
    assert output.qc["csv_readback_passed"] and output.qc["geopackage_readback_passed"]
    assert output.qc["input_files_unchanged"]
    assert before == {p: gen._digest(p) for p in raw.iterdir()}
    report = json.loads(Path(output.artifacts["qc_json"]).read_text())
    assert report["human_approval_verified_by_module"] is False
    assert report["arcgis_pro_review_performed"] is False
    assert report["settings"]["small_patch_threshold_m2"] == 10000
    assert len(report["output_sha256"]) == 6


def test_repeated_adapter_run_never_overwrites(tmp_path):
    name, _ = synthetic_raw_run(tmp_path)
    req = gen.GeneralizationRequest(raw_run_directory=name)
    first = gen.create_generalized_cover_type_patches(tmp_path, req)
    second = gen.create_generalized_cover_type_patches(tmp_path, req)
    assert first.status == second.status == "complete_review_required"
    assert first.artifacts["geopackage"] != second.artifacts["geopackage"]
    assert Path(first.artifacts["geopackage"]).is_file()
    pd.testing.assert_frame_equal(pd.read_csv(first.artifacts["membership_csv"]), pd.read_csv(second.artifacts["membership_csv"]))


def test_failed_raw_run_rejected(tmp_path):
    name, raw = synthetic_raw_run(tmp_path)
    (raw / "FAILED_DO_NOT_USE.json").write_text("{}")
    output = gen.create_generalized_cover_type_patches(tmp_path, gen.GeneralizationRequest(raw_run_directory=name))
    assert output.status == "failed"
    assert not list(tmp_path.glob("genpatch_*"))


def test_tampered_original_source_rejected(tmp_path):
    name, _ = synthetic_raw_run(tmp_path)
    (tmp_path / "cmap_12345678_v1_cover_type_30m.tif").write_bytes(b"changed")
    output = gen.create_generalized_cover_type_patches(tmp_path, gen.GeneralizationRequest(raw_run_directory=name))
    assert output.status == "failed"
    assert "hash changed" in output.errors[0]
    assert not list(tmp_path.glob("genpatch_*"))


def test_missing_raw_run_is_structured_failure(tmp_path):
    output = gen.create_generalized_cover_type_patches(tmp_path, gen.GeneralizationRequest(raw_run_directory="rawpatch_missing"))
    assert output.status == "failed" and output.stage == "validate_raw_run"


@pytest.mark.parametrize("name", ["../rawpatch_bad", "rawpatch_a/b", "/rawpatch_a", "rawpatch_a\\b"])
def test_raw_directory_path_injection_rejected(name):
    with pytest.raises(ValidationError):
        gen.GeneralizationRequest(raw_run_directory=name)


def test_symlink_escape_rejected(tmp_path):
    root = tmp_path / "outputs"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "rawpatch_escape").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable")
    output = gen.create_generalized_cover_type_patches(root, gen.GeneralizationRequest(raw_run_directory="rawpatch_escape"))
    assert output.status == "failed"


def test_unapproved_extra_barrier_is_not_silently_ignored():
    with pytest.raises(ValidationError):
        gen.GeneralizationRequest(raw_run_directory="rawpatch_sample", barrier="road.gpkg")


def test_unknown_id_failure_writes_no_outputs(tmp_path):
    name, _ = synthetic_raw_run(tmp_path)
    req = gen.GeneralizationRequest(raw_run_directory=name,
        settings=gen.GeneralizationSettings(excluded_patch_ids=["CTP_999999"]))
    output = gen.create_generalized_cover_type_patches(tmp_path, req)
    assert output.status == "failed"
    assert not list(tmp_path.glob("genpatch_*"))


def test_post_write_failure_has_marker(tmp_path, monkeypatch):
    name, _ = synthetic_raw_run(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("SIMULATED CSV WRITE FAILURE")
    monkeypatch.setattr(gen, "_write_csv", fail)
    output = gen.create_generalized_cover_type_patches(tmp_path, gen.GeneralizationRequest(raw_run_directory=name))
    assert output.status == "failed"
    assert Path(output.artifacts["failure_report"]).is_file()
    marker = json.loads(Path(output.artifacts["failure_report"]).read_text())
    assert marker["accept_outputs"] is False
    assert "SIMULATED" in output.errors[0]


def test_raw_metadata_mismatch_rejected(tmp_path):
    name, raw = synthetic_raw_run(tmp_path)
    path = raw / "raw_patch_qc.json"
    report = json.loads(path.read_text())
    report["qc"]["per_class"][0]["square_meters"] = 1
    path.write_text(json.dumps(report))
    output = gen.create_generalized_cover_type_patches(tmp_path, gen.GeneralizationRequest(raw_run_directory=name))
    assert output.status == "failed"


def test_geopackage_readback_mismatch_rejected():
    units = result()[0]
    altered = units.copy()
    altered.loc[0, "display_output_label"] = "wrong"
    with pytest.raises(gen.GeneralizationValidationError):
        gen._readback(units, altered)

def test_selected_scheme_mismatch_rejected(tmp_path):
    name, _ = synthetic_raw_run(tmp_path)

    req = gen.GeneralizationRequest(
        raw_run_directory=name,
        expected_cover_scheme_id="different_scheme",
    )

    output = gen.create_generalized_cover_type_patches(tmp_path, req)

    assert output.status == "failed"
    assert "cover scheme" in output.errors[0]
    assert not list(tmp_path.glob("genpatch_*"))
