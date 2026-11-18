"""Synthetic proposal validation only. No live data, policy approval, or mapping."""
import copy
import hashlib

import pytest

from crosswalk_proposal import ProposalError, build_crosswalk_proposal
from source_configuration import build_source_configuration


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
    request = {
        "source_configuration_sha256": source["configuration_sha256"],
        "classes": [
            {"output_code": 1, "label": "Synthetic group", "rationale": "Test grouping"},
            {"output_code": 40, "label": "EVT 40 unresolved", "rationale": "Missing label"},
        ],
        "decisions": [
            {
                "source_evt_code": code, "output_code": 1,
                "proposed_forest_land": True, "rationale": "Synthetic proposal only",
                "unresolved": [],
            }
            for code in (10, 20)
        ] + [{
            "source_evt_code": 40, "output_code": 40,
            "proposed_forest_land": None, "rationale": "Retain source identity",
            "unresolved": ["Official label unavailable"],
        }],
    }
    return source, request


def test_valid_proposal_is_draft_not_approval():
    source, request = fixture()
    result = build_crosswalk_proposal(source, request)
    assert result["status"] == "draft_requires_human_review"
    assert result["forest_land_policy_approved"] is False
    assert result["classification_performed"] is False
    assert result["unresolved_evt_codes"] == [40]
    assert "approved_by" not in result
    assert len(result["proposal_sha256"]) == 64


def test_deterministic_order_and_no_input_changes():
    source, request = fixture()
    before = copy.deepcopy((source, request))
    first = build_crosswalk_proposal(source, request)
    assert (source, request) == before
    request["classes"].reverse()
    request["decisions"].reverse()
    assert build_crosswalk_proposal(source, request) == first


def test_changed_source_rejected():
    source, request = fixture()
    source["entries"][0]["official_name"] = "Changed"
    with pytest.raises(ProposalError, match="digest"):
        build_crosswalk_proposal(source, request)


def test_wrong_reference_rejected():
    source, request = fixture()
    request["source_configuration_sha256"] = "0" * 64
    with pytest.raises(ProposalError, match="digest"):
        build_crosswalk_proposal(source, request)


@pytest.mark.parametrize("mutation", [
    lambda r: r["decisions"].pop(),
    lambda r: r["decisions"].append(copy.deepcopy(r["decisions"][0])),
    lambda r: r["decisions"][0].update(source_evt_code=999),
    lambda r: r["decisions"][0].update(output_code=99),
    lambda r: r["classes"].append(copy.deepcopy(r["classes"][0])),
    lambda r: r["classes"].append({
        "output_code": 9, "label": "Unused", "rationale": "Test",
    }),
    lambda r: r["decisions"][1].update(proposed_forest_land=False),
    lambda r: r["decisions"][2].update(output_code=1),
    lambda r: r["decisions"][2].update(proposed_forest_land=False),
    lambda r: r["decisions"][2].update(unresolved=[]),
    lambda r: r.update(approved_by="user"),
    lambda r: r["decisions"][0].update(approved=True),
    lambda r: r["decisions"][0].update(proposed_forest_land=1),
    lambda r: r["decisions"][0].update(rationale=" "),
    lambda r: r["classes"][0].update(label=" "),
])
def test_invalid_or_approval_smuggling_requests_rejected(mutation):
    source, request = fixture()
    mutation(request)
    with pytest.raises(ProposalError):
        build_crosswalk_proposal(source, request)


def test_changed_proposal_changes_digest():
    source, request = fixture()
    first = build_crosswalk_proposal(source, request)
    request["decisions"][0]["rationale"] = "Different review rationale"
    second = build_crosswalk_proposal(source, request)
    assert first["proposal_sha256"] != second["proposal_sha256"]
