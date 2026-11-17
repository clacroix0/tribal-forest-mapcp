"""DRAFT synthetic unit tests. Fake adapter is NOT production approval."""
from datetime import datetime, timedelta, timezone

import pytest

import hosted_configuration_store as store


@pytest.fixture
def setup_store(tmp_path, monkeypatch):
    result = {
        "status": "draft_review_complete_requires_human_review",
        "source_configuration": {"configuration_sha256": "a" * 64},
        "proposal": {"proposal_sha256": "b" * 64},
        "review": {"review_sha256": "c" * 64},
        "limitations": ["Synthetic fixture, not real forestry approval"],
    }
    monkeypatch.setattr(store, "review_source_configuration",
                        lambda *args: result)

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

    monkeypatch.setattr(store.local_save, "_build_documents", fake_documents)
    kwargs = dict(
        outputs_root=tmp_path / "outputs", project_data_root=tmp_path / "data",
        request={"acquisition_directory": "bacq_synthetic", "proposal": None},
        configuration_key="synthetic", version="v1",
        source_sha256="a" * 64, proposal_sha256="b" * 64,
        review_sha256="c" * 64,
    )
    return kwargs, result


class FakeVerifier:
    def verify(self, action):
        return store.ApprovalReceipt(
            action_sha256=store.local_save._digest(action),
            evidence_id="SYNTHETIC-NOT-AUTHENTICATED",
            issuer="synthetic-test-only",
            expires_at_utc=datetime.now(timezone.utc) + timedelta(minutes=5),
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
        store.save_configuration(**kwargs, enabled=True, verifier=FakeVerifier())
    assert not kwargs["project_data_root"].exists()


def test_wrong_action_no_write(setup_store):
    class WrongVerifier(FakeVerifier):
        def verify(self, action):
            receipt = super().verify(action)
            return store.ApprovalReceipt(
                "0" * 64, receipt.evidence_id, receipt.issuer,
                receipt.expires_at_utc)
    kwargs, _ = setup_store
    with pytest.raises(store.ConfigurationStoreError, match="exact action"):
        store.save_configuration(**kwargs, enabled=True, verifier=WrongVerifier())
    assert not kwargs["project_data_root"].exists()


def test_expired_approval_no_write(setup_store):
    class ExpiredVerifier(FakeVerifier):
        def verify(self, action):
            receipt = super().verify(action)
            return store.ApprovalReceipt(
                receipt.action_sha256, receipt.evidence_id, receipt.issuer,
                datetime.now(timezone.utc) - timedelta(seconds=1))
    kwargs, _ = setup_store
    with pytest.raises(store.ConfigurationStoreError, match="expired"):
        store.save_configuration(**kwargs, enabled=True, verifier=ExpiredVerifier())
    assert not kwargs["project_data_root"].exists()


def test_saved_ids_records_hashes_and_no_overwrite(setup_store):
    kwargs, _ = setup_store
    result = store.save_configuration(
        **kwargs, enabled=True, verifier=FakeVerifier())
    assert result["configuration_id"] == "cfg_synthetic_v1"
    assert result["mapping_compatible"] is False
    target, approval = store._paths(
        kwargs["project_data_root"], result["configuration_id"])
    cw = store.bm._read_json(target)
    record = store.bm._read_json(approval)
    assert cw["entries"][0]["candidate_forest_land"] is None
    assert record["schema"] == "mapcp_hosted_configuration_approval_v1"
    assert "operator_confirmation_recorded" not in record
    assert "identity_authenticated" not in record
    assert store.local_save._digest(record) == cw.pop("approval_record_sha256")
    assert store.local_save._digest(cw) == record["crosswalk_payload_sha256"]
    with pytest.raises(store.ConfigurationStoreError, match="no overwrite"):
        store.save_configuration(**kwargs, enabled=True, verifier=FakeVerifier())


def test_reject_path_like_id(tmp_path):
    with pytest.raises(store.ConfigurationStoreError):
        store._paths(tmp_path, "../../escape")
