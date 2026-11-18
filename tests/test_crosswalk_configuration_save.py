"""Synthetic local-save checks; no real forestry approval or mapping."""
import copy

import pytest

import boundary_mapping as bm
import crosswalk_configuration_save as save
from source_configuration import build_source_configuration
from crosswalk_proposal import build_crosswalk_proposal
from crosswalk_review import build_crosswalk_review


@pytest.fixture
def documents():
    import hashlib
    data = b"VALUE,NAME\n10,Synthetic tree\n"
    profile = {"product": "EVT", "version": "synthetic", "region": "CONUS"}
    source = build_source_configuration(
        data, [10, 40], raster_profile=profile,
        catalog_record={
            **profile, "source_url": "https://www.landfire.gov/synthetic.csv",
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        code_column="VALUE", name_column="NAME",
    )
    proposal = build_crosswalk_proposal(source, {
        "source_configuration_sha256": source["configuration_sha256"],
        "classes": [
            {"output_code": 10, "label": "synthetic_tree",
             "rationale": "Synthetic test only"},
            {"output_code": 40, "label": "unknown_40",
             "rationale": "Preserve missing-label identity"},
        ],
        "decisions": [
            {"source_evt_code": 10, "output_code": 10,
             "proposed_forest_land": True,
             "rationale": "Synthetic test decision, not real policy",
             "unresolved": []},
            {"source_evt_code": 40, "output_code": 40,
             "proposed_forest_land": None,
             "rationale": "Missing label remains unknown",
             "unresolved": ["Missing official label"]},
        ],
    })
    evidence = {
        "source_run_id": "bacq_synthetic",
        "boundary_sha256": "a" * 64,
        "source_raster_sha256": "b" * 64,
        "source_configuration_sha256": source["configuration_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "total_grid_cells": 3, "outside_boundary_cells": 0,
        "evt_nodata_inside_boundary_cells": 1,
        "evt_counts": [
            {"source_evt_code": 10, "cell_count": 1},
            {"source_evt_code": 40, "cell_count": 1},
        ],
    }
    review = build_crosswalk_review(source, proposal, evidence)
    result = {
        "status": "draft_review_complete_requires_human_review",
        "acquisition_directory": "bacq_synthetic",
        "source_configuration": source, "proposal": proposal,
        "review": review, "limitations": ["Synthetic test only"],
    }
    return save._build_documents(result, "synthetic", "v1")


def collection():
    return {
        "boundary_sha256": "a" * 64,
        "extract": {"geotiff_sha256": "b" * 64},
    }


def test_saved_format_loads_and_unknown_is_preserved(tmp_path, documents):
    name, cw, record_name, record = documents
    save._write_documents(tmp_path, *documents)
    loaded, _ = bm.load_crosswalk(tmp_path, name)
    save.validate_run_binding(tmp_path, "bacq_synthetic", collection(), loaded)
    unknown = next(e for e in loaded["entries"] if e["evt_code"] == 40)
    assert unknown["output_code"] == 40
    assert unknown["candidate_forest_land"] is None
    assert loaded["unmapped_valid_output_code"] not in (10, 40, -9999)
    assert record["identity_authenticated"] is False


def test_changed_input_rejected(tmp_path, documents):
    save._write_documents(tmp_path, *documents)
    changed = collection()
    changed["boundary_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="does not match"):
        save.validate_run_binding(tmp_path, "bacq_synthetic", changed, documents[1])


def test_changed_crosswalk_rejected(tmp_path, documents):
    save._write_documents(tmp_path, *documents)
    changed = copy.deepcopy(documents[1])
    changed["entries"][0]["candidate_forest_land"] = False
    with pytest.raises(ValueError, match="Crosswalk changed"):
        save.validate_run_binding(tmp_path, "bacq_synthetic", collection(), changed)


def test_no_overwrite(tmp_path, documents):
    save._write_documents(tmp_path, *documents)
    with pytest.raises(ValueError, match="no overwrite"):
        save._write_documents(tmp_path, *documents)


def test_missing_approval_record_rejected(tmp_path, documents):
    with pytest.raises(ValueError):
        save.validate_run_binding(
            tmp_path, "bacq_synthetic", collection(), documents[1]
        )


def test_export_labels_preserve_reviewed_names_and_unknowns(documents):
    import re
    _, crosswalk, _, _ = documents
    table = {
        row["output_code"]: row
        for row in crosswalk["output_code_table"]
    }
    assert table[-9999]["output_label"] == "nodata"
    fallback = crosswalk["unmapped_valid_output_code"]
    assert table[fallback]["output_label"] == "unmapped_evt"
    assert table[fallback]["candidate_forest_land"] is None
    for code in (10, 40):
        assert re.fullmatch(
            r"candidate_[A-Z0-9_]+", table[code]["output_label"]
        )
    assert table[10]["reviewed_label"] == "synthetic_tree"
    assert table[10]["description"].startswith("synthetic_tree:")
    assert table[40]["reviewed_label"] == "unknown_40"
    assert table[40]["candidate_forest_land"] is None
    for entry in crosswalk["entries"]:
        assert entry["output_label"] == table[entry["output_code"]]["output_label"]
