"""Synthetic hosted-store tests; fake adapters are NOT production approval.

Exercises internal configuration saving only. No real forestry approval,
network requests, mapping execution, MCP registration, or deployment.
"""
from datetime import datetime, timedelta, timezone

import pytest

import hosted_configuration_store as store
from crosswalk_configuration_save import _build_documents as real_build_documents


@pytest.fixture
def setup_store(tmp_path, monkeypatch):
    result = {
        "status": "draft_review_complete_requires_human_review",
        "source_configuration": {"configuration_sha256": "a" * 64},
        "proposal": {"proposal_sha256": "b" * 64},
        "review": {"review_sha256": "c" * 64},
        "limitations": ["Synthetic fixture, not real forestry approval"],
    }
    monkeypatch.setattr(
        store, "review_source_configuration", lambda *args: result
    )

    def fake_documents(result, key, version):
        name = f"runbound_{key}_{version}.json"
        record_name = f"runbound_{key}_{version}.approval.json"
        crosswalk = {
            "run_binding": {"source_run_id": "bacq_synthetic"},
            "approval_record_filename": record_name,
            "approval_record_sha256": "old",
            "crosswalk_approval_note": "local fixture",
            "entries": [{"candidate_forest_land": None}],
        }
        record = {
            "schema": "mapcp_local_configuration_approval_v1",
            "operator_confirmation_recorded": True,
            "identity_authenticated": False,
            "approval_method": "local_operator_interactive_terminal",
        }
        return name, crosswalk, record_name, record

    monkeypatch.setattr(
        store.local_save, "_build_documents", fake_documents
    )
    kwargs = {
        "outputs_root": tmp_path / "outputs",
        "project_data_root": tmp_path / "data",
        "request": {
            "acquisition_directory": "bacq_synthetic",
            "proposal": None,
        },
        "configuration_key": "synthetic",
        "version": "v1",
        "source_sha256": "a" * 64,
        "proposal_sha256": "b" * 64,
        "review_sha256": "c" * 64,
    }
    return kwargs, result


class FakeVerifier:
    """Synthetic exact-action receipt; does not authenticate a human."""

    def verify(self, action):
        return store.ApprovalReceipt(
            action_sha256=store.local_save._digest(action),
            evidence_id="SYNTHETIC-NOT-AUTHENTICATED",
            issuer="synthetic-test-only",
            expires_at_utc=(
                datetime.now(timezone.utc) + timedelta(minutes=5)
            ),
        )


def test_disabled_by_default(setup_store):
    kwargs, _ = setup_store
    with pytest.raises(store.ConfigurationStoreError, match="disabled"):
        store.save_configuration(**kwargs)
    assert not kwargs["project_data_root"].exists()


def test_no_verifier_no_write(setup_store):
    kwargs, _ = setup_store
    with pytest.raises(store.ConfigurationStoreError, match="verifier"):
        store.save_configuration(**kwargs, enabled=True)
    assert not kwargs["project_data_root"].exists()


def test_changed_review_no_write(setup_store):
    kwargs, _ = setup_store
    kwargs["review_sha256"] = "d" * 64
    with pytest.raises(store.ConfigurationStoreError, match="differs"):
        store.save_configuration(
            **kwargs, enabled=True, verifier=FakeVerifier()
        )
    assert not kwargs["project_data_root"].exists()


def test_wrong_action_no_write(setup_store):
    class WrongVerifier(FakeVerifier):
        def verify(self, action):
            receipt = super().verify(action)
            return store.ApprovalReceipt(
                action_sha256="0" * 64,
                evidence_id=receipt.evidence_id,
                issuer=receipt.issuer,
                expires_at_utc=receipt.expires_at_utc,
            )

    kwargs, _ = setup_store
    with pytest.raises(
        store.ConfigurationStoreError, match="exact action"
    ):
        store.save_configuration(
            **kwargs, enabled=True, verifier=WrongVerifier()
        )
    assert not kwargs["project_data_root"].exists()


def test_expired_approval_no_write(setup_store):
    class ExpiredVerifier(FakeVerifier):
        def verify(self, action):
            receipt = super().verify(action)
            return store.ApprovalReceipt(
                action_sha256=receipt.action_sha256,
                evidence_id=receipt.evidence_id,
                issuer=receipt.issuer,
                expires_at_utc=(
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ),
            )

    kwargs, _ = setup_store
    with pytest.raises(store.ConfigurationStoreError, match="expired"):
        store.save_configuration(
            **kwargs, enabled=True, verifier=ExpiredVerifier()
        )
    assert not kwargs["project_data_root"].exists()


def test_saved_ids_records_hashes_and_no_overwrite(setup_store):
    kwargs, _ = setup_store
    result = store.save_configuration(
        **kwargs, enabled=True, verifier=FakeVerifier()
    )
    assert result["configuration_id"] == "cfg_synthetic_v1"
    assert result["mapping_compatible"] is False

    target, approval = store._paths(
        kwargs["project_data_root"], result["configuration_id"]
    )
    crosswalk = store.bm._read_json(target)
    record = store.bm._read_json(approval)

    assert crosswalk["entries"][0]["candidate_forest_land"] is None
    assert record["schema"] == "mapcp_hosted_configuration_approval_v1"
    assert "operator_confirmation_recorded" not in record
    assert "identity_authenticated" not in record
    assert (
        store.local_save._digest(record)
        == crosswalk.pop("approval_record_sha256")
    )
    assert (
        store.local_save._digest(crosswalk)
        == record["crosswalk_payload_sha256"]
    )

    with pytest.raises(
        store.ConfigurationStoreError, match="no overwrite"
    ):
        store.save_configuration(
            **kwargs, enabled=True, verifier=FakeVerifier()
        )


def test_reject_path_like_id(tmp_path):
    with pytest.raises(store.ConfigurationStoreError):
        store._paths(tmp_path, "../../escape")


@pytest.fixture
def real_document_store(setup_store, monkeypatch):
    """Use real builders with synthetic evidence, not a real raster review."""
    import hashlib

    from source_configuration import build_source_configuration
    from crosswalk_proposal import build_crosswalk_proposal
    from crosswalk_review import build_crosswalk_review

    kwargs, _ = setup_store
    data = b"VALUE,NAME\n10,Synthetic tree\n"
    profile = {
        "product": "EVT",
        "version": "synthetic",
        "region": "CONUS",
    }
    source = build_source_configuration(
        data,
        [10, 40],
        raster_profile=profile,
        catalog_record={
            **profile,
            "source_url": "https://www.landfire.gov/synthetic.csv",
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        code_column="VALUE",
        name_column="NAME",
    )
    proposal = build_crosswalk_proposal(source, {
        "source_configuration_sha256": source["configuration_sha256"],
        "classes": [
            {
                "output_code": 10,
                "label": "synthetic_tree",
                "rationale": "Synthetic test only",
            },
            {
                "output_code": 40,
                "label": "unknown_40",
                "rationale": "Preserve missing-label identity",
            },
        ],
        "decisions": [
            {
                "source_evt_code": 10,
                "output_code": 10,
                "proposed_forest_land": True,
                "rationale": "Synthetic test decision, not real policy",
                "unresolved": [],
            },
            {
                "source_evt_code": 40,
                "output_code": 40,
                "proposed_forest_land": None,
                "rationale": "Missing label remains unknown",
                "unresolved": ["Missing official label"],
            },
        ],
    })
    evidence = {
        "source_run_id": "bacq_synthetic",
        "boundary_sha256": "a" * 64,
        "source_raster_sha256": "b" * 64,
        "source_configuration_sha256": source["configuration_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "total_grid_cells": 3,
        "outside_boundary_cells": 0,
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
        "source_configuration": source,
        "proposal": proposal,
        "review": review,
        "limitations": ["Synthetic test only; not real forestry approval"],
    }
    kwargs.update(
        source_sha256=source["configuration_sha256"],
        proposal_sha256=proposal["proposal_sha256"],
        review_sha256=review["review_sha256"],
    )
    monkeypatch.setattr(
        store.local_save, "_build_documents", real_build_documents
    )
    monkeypatch.setattr(
        store, "review_source_configuration", lambda *args: result
    )
    return kwargs, result


def test_real_documents_load_preserve_unknown_and_reject_hosted_mapping(
    real_document_store,
):
    kwargs, _ = real_document_store
    result = store.save_configuration(
        **kwargs, enabled=True, verifier=FakeVerifier()
    )
    target, approval = store._paths(
        kwargs["project_data_root"], result["configuration_id"]
    )
    loaded, _ = store.bm.load_crosswalk(
        kwargs["project_data_root"], target.name
    )
    record = store.bm._read_json(approval)

    assert result["classification_performed"] is False
    assert result["mapping_compatible"] is False
    assert record["schema"] == "mapcp_hosted_configuration_approval_v1"
    assert "operator_confirmation_recorded" not in record
    assert "identity_authenticated" not in record

    unknown = next(
        row for row in loaded["entries"] if row["evt_code"] == 40
    )
    assert unknown["candidate_forest_land"] is None
    assert unknown["output_code"] == 40

    unknown_table_row = next(
        row for row in loaded["output_code_table"]
        if row["output_code"] == 40
    )
    assert unknown_table_row["candidate_forest_land"] is None

    payload = dict(loaded)
    record_digest = payload.pop("approval_record_sha256")
    assert store.local_save._digest(record) == record_digest
    assert (
        store.local_save._digest(payload)
        == record["crosswalk_payload_sha256"]
    )

    collection = {
        "boundary_sha256": "a" * 64,
        "extract": {"geotiff_sha256": "b" * 64},
    }
    with pytest.raises(
        ValueError, match="Missing local operator confirmation record"
    ):
        store.local_save.validate_run_binding(
            kwargs["project_data_root"],
            "bacq_synthetic",
            collection,
            loaded,
        )


def test_changed_second_review_real_documents_no_write(
    real_document_store, monkeypatch
):
    import copy

    kwargs, original = real_document_store
    changed = copy.deepcopy(original)
    changed["limitations"].append("Synthetic change during approval")
    reviews = iter([original, changed])
    monkeypatch.setattr(
        store, "review_source_configuration", lambda *args: next(reviews)
    )

    with pytest.raises(
        store.ConfigurationStoreError,
        match="Inputs changed during approval",
    ):
        store.save_configuration(
            **kwargs, enabled=True, verifier=FakeVerifier()
        )
    assert not kwargs["project_data_root"].exists()


def test_receipt_expires_during_revalidation_real_documents_no_write(
    real_document_store, monkeypatch
):
    kwargs, result = real_document_store
    class SyntheticClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    clock = {
        "now": SyntheticClock(2030, 1, 1, tzinfo=timezone.utc),
    }

    class ExpiringDuringReviewVerifier:
        def verify(self, action):
            return store.ApprovalReceipt(
                action_sha256=store.local_save._digest(action),
                evidence_id="SYNTHETIC-EXPIRY-TEST",
                issuer="synthetic-test-only",
                expires_at_utc=clock["now"] + timedelta(seconds=1),
            )

    calls = 0

    def review_with_clock_advance(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            clock["now"] += timedelta(seconds=2)
        return result

    monkeypatch.setattr(store, "datetime", SyntheticClock)
    monkeypatch.setattr(
        store, "review_source_configuration", review_with_clock_advance
    )

    with pytest.raises(
        store.ConfigurationStoreError,
        match="Approval expired during revalidation",
    ):
        store.save_configuration(
            **kwargs,
            enabled=True,
            verifier=ExpiringDuringReviewVerifier(),
        )
    assert calls == 2
    assert not kwargs["project_data_root"].exists()
