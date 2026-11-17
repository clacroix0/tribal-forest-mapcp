"""Synthetic run evidence only; no real geography, policy, or raster execution."""
import copy
import hashlib

import pytest

from source_configuration import build_source_configuration
from crosswalk_proposal import build_crosswalk_proposal
from crosswalk_review import ReviewError, build_crosswalk_review


def fixture():
    data = b"VALUE,NAME\n10,Synthetic A\n20,Synthetic B\n"
    profile = {"product": "EVT", "version": "synthetic", "region": "CONUS"}
    source = build_source_configuration(
        data, [10, 20, 40],
        raster_profile=profile,
        catalog_record={
            **profile,
            "source_url": "https://www.landfire.gov/synthetic.csv",
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        code_column="VALUE", name_column="NAME",
    )
    proposal = build_crosswalk_proposal(source, {
        "source_configuration_sha256": source["configuration_sha256"],
        "classes": [
            {"output_code": 1, "label": "Synthetic group", "rationale": "Test"},
            {"output_code": 40, "label": "EVT 40 unresolved", "rationale": "Test"},
        ],
        "decisions": [
            {
                "source_evt_code": code, "output_code": 1,
                "proposed_forest_land": True,
                "rationale": "Synthetic proposal",
                "unresolved": [],
            }
            for code in (10, 20)
        ] + [{
            "source_evt_code": 40, "output_code": 40,
            "proposed_forest_land": None,
            "rationale": "Preserve unresolved source",
            "unresolved": ["Missing official label", "Policy unresolved"],
        }],
    })
    run = {
        "source_run_id": "synthetic_run_1",
        "boundary_sha256": "a" * 64,
        "source_raster_sha256": "b" * 64,
        "source_configuration_sha256": source["configuration_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "total_grid_cells": 15,
        "outside_boundary_cells": 3,
        "evt_nodata_inside_boundary_cells": 2,
        "evt_counts": [
            {"source_evt_code": 10, "cell_count": 4},
            {"source_evt_code": 20, "cell_count": 5},
            {"source_evt_code": 40, "cell_count": 1},
        ],
    }
    return source, proposal, run


def test_counts_acreage_and_unresolved_are_separate():
    source, proposal, run = fixture()
    result = build_crosswalk_review(source, proposal, run)
    coverage = result["coverage"]
    assert coverage["valid_source_cells"]["cell_count"] == 10
    assert coverage["inside_boundary_cells"]["cell_count"] == 12
    assert coverage["outside_boundary_cells"]["cell_count"] == 3
    assert coverage["evt_nodata_inside_boundary"]["cell_count"] == 2
    assert coverage["unresolved_valid_cells"]["cell_count"] == 1
    assert coverage["valid_source_cells"]["square_meters"] == 9000
    assert coverage["valid_source_cells"]["acres"] == pytest.approx(
        9000 / 4046.8564224, abs=1e-6
    )
    assert [r["cell_count"] for r in result["proposed_class_rows"]] == [9, 1]
    assert all(result["checks"].values())
    assert result["classification_performed"] is False
    assert result["approval_authenticated"] is False


def test_deterministic_order_and_no_mutation():
    source, proposal, run = fixture()
    before = copy.deepcopy((source, proposal, run))
    first = build_crosswalk_review(source, proposal, run)
    assert (source, proposal, run) == before
    run["evt_counts"].reverse()
    assert build_crosswalk_review(source, proposal, run) == first


@pytest.mark.parametrize("field", [
    "boundary_sha256", "source_raster_sha256", "source_run_id",
])
def test_different_run_binding_changes_review_digest(field):
    source, proposal, run = fixture()
    first = build_crosswalk_review(source, proposal, run)
    run[field] = "different_run" if field == "source_run_id" else "c" * 64
    second = build_crosswalk_review(source, proposal, run)
    assert first["review_sha256"] != second["review_sha256"]


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(source_configuration_sha256="0" * 64),
    lambda r: r.update(proposal_sha256="0" * 64),
    lambda r: r.update(boundary_sha256="../boundary.geojson"),
    lambda r: r.update(source_run_id="../run"),
    lambda r: r.update(total_grid_cells=16),
    lambda r: r.update(outside_boundary_cells=-1),
    lambda r: r["evt_counts"].pop(),
    lambda r: r["evt_counts"].append(dict(r["evt_counts"][0])),
    lambda r: r["evt_counts"][0].update(source_evt_code=999),
    lambda r: r["evt_counts"][0].update(cell_count=True),
    lambda r: r["evt_counts"][0].update(cell_count=0),
    lambda r: r["evt_counts"][0].update(cell_count=4.5),
    lambda r: r.update(approved=True),
])
def test_invalid_run_evidence_rejected(mutation):
    source, proposal, run = fixture()
    mutation(run)
    with pytest.raises(ReviewError):
        build_crosswalk_review(source, proposal, run)


@pytest.mark.parametrize("target", ["source", "proposal"])
def test_tampered_source_or_proposal_rejected(target):
    source, proposal, run = fixture()
    if target == "source":
        source["entries"][0]["official_name"] = "Tampered"
    else:
        proposal["decisions"][0]["rationale"] = "Tampered"
    with pytest.raises(ReviewError):
        build_crosswalk_review(source, proposal, run)
