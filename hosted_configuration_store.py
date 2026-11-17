"""DRAFT: internal hosted configuration storage; no MCP registration.

No production approval adapter is supplied. Disabled unless explicitly enabled.
An adapter is trusted application code, never a model-provided callback or flag.
Existing terminal approval records and CLI are not modified.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import boundary_mapping as bm
import crosswalk_configuration_save as local_save
from source_configuration_workflow import SourceReviewRequest, review_source_configuration


class ConfigurationStoreError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ConfigurationStoreError(message)


@dataclass(frozen=True)
class ApprovalReceipt:
    action_sha256: str
    evidence_id: str
    issuer: str
    expires_at_utc: datetime


class ApprovalVerifier(Protocol):
    def verify(self, action: dict) -> ApprovalReceipt:
        """Authenticate real approval of the complete action or raise.

        Must validate provenance, exact-input binding, authorization, expiry,
        and replay policy using a trusted host/operator mechanism. A digest,
        bearer login, or model-authored approval flag alone is insufficient.
        """
        ...


def _paths(project_data_root, configuration_id):
    require(isinstance(configuration_id, str) and re.fullmatch(
        r"cfg_[A-Za-z0-9][A-Za-z0-9_-]{0,49}_v[1-9][0-9]{0,3}",
        configuration_id), "Invalid controlled configuration ID.")
    stem = "runbound_" + configuration_id[4:]
    root = Path(project_data_root).resolve()
    return (root / "run_crosswalks" / (stem + ".json"),
            root / "approvals" / (stem + ".approval.json"))


def _checked_receipt(verifier, action):
    require(verifier is not None, "No trusted approval verifier configured.")
    receipt = verifier.verify(action)
    require(type(receipt) is ApprovalReceipt, "Invalid approval receipt type.")
    require(receipt.action_sha256 == local_save._digest(action),
            "Approval does not match this exact action.")
    require(isinstance(receipt.evidence_id, str) and
            0 < len(receipt.evidence_id) <= 200, "Invalid approval evidence ID.")
    require(isinstance(receipt.issuer, str) and
            0 < len(receipt.issuer) <= 200, "Invalid approval issuer.")
    require(isinstance(receipt.expires_at_utc, datetime) and
            receipt.expires_at_utc.tzinfo is not None and
            receipt.expires_at_utc > datetime.now(timezone.utc),
            "Approval receipt expired or lacks a time zone.")
    return receipt


def save_configuration(outputs_root, project_data_root, request, *,
                       configuration_key, version,
                       source_sha256, proposal_sha256, review_sha256,
                       enabled=False, verifier=None):
    """Internal write. No network, mapping, deployment, or automatic approval.

    The trusted caller must present the full reviewed decisions/limitations to
    the human through its approval mechanism. No production verifier is here.
    Hosted records intentionally use a new schema: legacy mapping MUST reject
    them until a separate validator integration is reviewed and implemented.
    """
    require(enabled is True, "Hosted configuration saving is disabled.")
    require(verifier is not None, "No trusted approval verifier configured.")
    request = SourceReviewRequest.model_validate(request)
    result = review_source_configuration(outputs_root, project_data_root, request)
    require(result.get("status") == "draft_review_complete_requires_human_review",
            "Fresh review failed; nothing saved.")
    require(result["source_configuration"]["configuration_sha256"] == source_sha256
            and result["proposal"]["proposal_sha256"] == proposal_sha256
            and result["review"]["review_sha256"] == review_sha256,
            "Fresh review differs from the reviewed digests.")
    name, crosswalk, record_name, record = local_save._build_documents(
        result, configuration_key, version)
    configuration_id = f"cfg_{configuration_key}_{version}"
    target, record_target = _paths(project_data_root, configuration_id)
    require(target.name == name and record_target.name == record_name,
            "Configuration naming mismatch.")
    require(not target.exists() and not record_target.exists(),
            "Configuration or record already exists; no overwrite.")
    action = {
        "action": "save_run_bound_configuration",
        "configuration_id": configuration_id,
        "acquisition_directory": request.acquisition_directory,
        "source_configuration_sha256": source_sha256,
        "proposal_sha256": proposal_sha256,
        "review_sha256": review_sha256,
        "run_binding": crosswalk["run_binding"],
        "review": result["review"],
        "proposal": result["proposal"],
        "limitations": result["limitations"],
    }
    receipt = _checked_receipt(verifier, action)
    fresh = review_source_configuration(outputs_root, project_data_root, request)
    require(fresh == result, "Inputs changed during approval; nothing saved.")
    require(receipt.expires_at_utc > datetime.now(timezone.utc),
            "Approval expired during revalidation; nothing saved.")
    crosswalk["crosswalk_approval_note"] = (
        "Exact run-bound proposal, unknowns, and limitations accepted via "
        "the configured trusted approval adapter. Not Tribal or legal authority.")
    crosswalk.pop("approval_record_sha256", None)
    record["schema"] = "mapcp_hosted_configuration_approval_v1"
    record.pop("operator_confirmation_recorded", None)
    record.pop("identity_authenticated", None)
    record["approval_method"] = "trusted_adapter_verified_exact_action"
    record["approval_evidence"] = {
        "issuer": receipt.issuer,
        "evidence_id": receipt.evidence_id,
        "action_sha256": receipt.action_sha256,
        "expires_at_utc": receipt.expires_at_utc.isoformat(),
    }
    record["crosswalk_payload_sha256"] = local_save._digest(crosswalk)
    crosswalk["approval_record_sha256"] = local_save._digest(record)
    local_save._write_documents(
        project_data_root, name, crosswalk, record_name, record)
    require(bm._read_json(target) == crosswalk and
            bm._read_json(record_target) == record,
            "Saved-document read-back mismatch; operator review required.")
    return {
        "status": "configuration_saved_mapping_integration_required",
        "configuration_id": configuration_id,
        "acquisition_directory": request.acquisition_directory,
        "review_sha256": review_sha256,
        "classification_performed": False,
        "mapping_compatible": False,
        "warnings": [
            "No production approval adapter is supplied by this module.",
            "Legacy mapping rejects this hosted record schema by design.",
            "Storage persistence across deployment is not established.",
        ],
    }
