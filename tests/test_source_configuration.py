"""Synthetic CSV fixtures only. No network, government labels, or forest policy."""
import hashlib
import json

import pytest

from source_configuration import (
    SourceConfigurationError,
    build_source_configuration,
)

PROFILE = {"product": "EVT", "version": "synthetic-v1", "region": "CONUS"}
CSV = b"VALUE,NAME\n10,Synthetic type\n20,Synthetic type\n30,\n"


def build(data=CSV, codes=None, profile=None, **record_changes):
    record = {
        **PROFILE,
        "source_url": "https://www.landfire.gov/synthetic-test.csv",
        "sha256": hashlib.sha256(data).hexdigest(),
        **record_changes,
    }
    return build_source_configuration(
        data,
        [10, 20, 30, 40, 50, -9999] if codes is None else codes,
        raster_profile=PROFILE if profile is None else profile,
        catalog_record=record,
        code_column="VALUE",
        name_column="NAME",
    )


def test_identity_and_unknown_codes_are_preserved_separately():
    result = build()
    assert [e["output_code"] for e in result["entries"]] == [10, 20, 30, 40, 50]
    assert len({e["display_label"] for e in result["entries"]}) == 5
    assert [e["label_status"] for e in result["entries"]] == [
        "verified_table_match", "verified_table_match",
        "missing_label", "missing_label", "missing_label",
    ]


def test_no_forest_land_assignment_or_fabricated_approval():
    result = build()
    assert all(e["candidate_forest_land"] is None for e in result["entries"])
    assert result["forest_land_classification_performed"] is False
    assert result["forest_land_policy"] == "not_assigned"
    assert "approved_by" not in result
    assert result["status"] == "draft_requires_run_and_policy_review"


def test_deterministic_and_json_serializable():
    assert build(codes=[20, 10, 10]) == build(codes=[10, 20])
    json.dumps(build(), allow_nan=False)


@pytest.mark.parametrize("key", ["product", "version", "region"])
def test_profile_mismatch_rejected(key):
    with pytest.raises(SourceConfigurationError, match="mismatch"):
        build(**{key: "different"})


def test_checksum_mismatch_rejected():
    with pytest.raises(SourceConfigurationError, match="checksum"):
        build(sha256="0" * 64)


@pytest.mark.parametrize("data", [
    b"VALUE,NAME\n10,A\n10,B\n",
    b"VALUE,NAME\n10,A\n10,A\n",
])
def test_duplicate_codes_rejected_even_if_labels_agree(data):
    with pytest.raises(SourceConfigurationError, match="Duplicate"):
        build(data=data)


@pytest.mark.parametrize("codes", [
    [], [-9999], [True], ["10"], [-1], [32768],
])
def test_invalid_or_empty_observed_codes_rejected(codes):
    with pytest.raises(SourceConfigurationError):
        build(codes=codes)


@pytest.mark.parametrize("data", [
    b"WRONG,NAME\n10,A\n",
    b"VALUE,NAME,NAME\n10,A,B\n",
    b"VALUE,NAME\n10,A,extra\n",
    b"VALUE,NAME\n10\n",
    b"VALUE,NAME\nx,A\n",
    b"VALUE,NAME\n32768,A\n",
    b"VALUE,NAME\n",
    b"\xff",
    b"VALUE,NAME\n10,A\x00\n",
])
def test_malformed_catalog_rejected(data):
    with pytest.raises(SourceConfigurationError):
        build(data=data)


@pytest.mark.parametrize("url", [
    "http://www.landfire.gov/a.csv",
    "https://example.org/a.csv",
    "https://user:password@www.landfire.gov/a.csv",
    "https://www.landfire.gov/a.csv?token=secret",
])
def test_uncontrolled_source_reference_rejected(url):
    with pytest.raises(SourceConfigurationError):
        build(source_url=url)


def test_input_objects_are_not_modified():
    profile = dict(PROFILE)
    codes = [20, 10]
    build(profile=profile, codes=codes)
    assert profile == PROFILE
    assert codes == [20, 10]


def test_review_attributes_preserved_without_policy_assignment():
    data = (
        b"VALUE,NAME,EVT_LF,EVT_PHYS,EVT_GP_N,SAF_SRM,approved_by\n"
        b"10,Synthetic type,Tree,Riparian,Synthetic group,Synthetic reference,user\n"
    )
    result = build(data=data, codes=[10, 40])
    entry, unknown = result["entries"]
    assert entry["source_attributes"] == {
        "EVT_LF": "Tree",
        "EVT_PHYS": "Riparian",
        "EVT_GP_N": "Synthetic group",
        "SAF_SRM": "Synthetic reference",
    }
    assert entry["candidate_forest_land"] is None
    assert entry["output_code"] == 10
    assert "approved_by" not in entry["source_attributes"]
    assert "approved_by" not in result
    assert unknown["source_attributes"] == {}
    assert unknown["candidate_forest_land"] is None


def test_blank_review_attribute_is_missing_not_inferred():
    data = b"VALUE,NAME,EVT_LF\n10,Synthetic type,\n"
    entry = build(data=data, codes=[10])["entries"][0]
    assert entry["source_attributes"]["EVT_LF"] is None
    assert entry["candidate_forest_land"] is None


def test_long_review_attribute_rejected():
    data = b"VALUE,NAME,EVT_LF\n10,Synthetic type," + b"x" * 2001 + b"\n"
    with pytest.raises(SourceConfigurationError, match="attribute"):
        build(data=data, codes=[10])


def test_evidence_changes_configuration_digest():
    first = build(
        data=b"VALUE,NAME,EVT_LF\n10,Synthetic type,Tree\n",
        codes=[10],
    )
    second = build(
        data=b"VALUE,NAME,EVT_LF\n10,Synthetic type,Shrub\n",
        codes=[10],
    )
    assert first["configuration_sha256"] != second["configuration_sha256"]
