"""Pure draft crosswalk validation. No writes, network, approval, or mapping."""
from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ProposalError(ValueError):
    pass


class OutputClass(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    output_code: int = Field(ge=0, le=32767)
    label: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=2000)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_evt_code: int = Field(ge=0, le=32767)
    output_code: int = Field(ge=0, le=32767)
    proposed_forest_land: bool | None
    rationale: str = Field(min_length=1, max_length=2000)
    unresolved: list[str] = Field(max_length=20)


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classes: list[OutputClass] = Field(min_length=1, max_length=10000)
    decisions: list[Decision] = Field(min_length=1, max_length=10000)


def _digest(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require(condition, message):
    if not condition:
        raise ProposalError(message)


def build_crosswalk_proposal(source_configuration: dict, request: dict) -> dict:
    """Validate a complete proposal against an unchanged source configuration.

    Returns proposed rules only. No approval or geographic applicability is
    authenticated. Source configuration must come from the controlled builder.
    Forest-land None means no assignment proposed, not nonforest.
    """
    try:
        parsed = ProposalRequest.model_validate(request)
    except ValidationError:
        raise ProposalError("Invalid proposal structure or unsupported fields.") from None

    _require(isinstance(source_configuration, dict), "Source must be an object.")
    source = dict(source_configuration)
    recorded = source.pop("configuration_sha256", None)
    _require(
        recorded == parsed.source_configuration_sha256 == _digest(source),
        "Source configuration digest mismatch.",
    )
    _require(
        source.get("schema") == "mapcp_source_configuration_v1"
        and source.get("mode") == "source_evt_identity"
        and source.get("forest_land_policy") == "not_assigned"
        and source.get("forest_land_classification_performed") is False,
        "Unsupported source configuration.",
    )
    entries = source.get("entries")
    _require(
        isinstance(entries, list) and 0 < len(entries) <= 10000,
        "Source entries missing or outside proposal limits.",
    )
    source_by_code = {}
    for entry in entries:
        _require(isinstance(entry, dict), "Malformed source entry.")
        code = entry.get("source_evt_code")
        _require(
            type(code) is int and 0 <= code <= 32767
            and code not in source_by_code
            and entry.get("output_code") == code
            and entry.get("candidate_forest_land") is None
            and entry.get("label_status") in ("verified_table_match", "missing_label"),
            "Invalid or duplicate source identity.",
        )
        source_by_code[code] = entry

    class_by_code = {}
    labels = set()
    for item in parsed.classes:
        label = item.label.strip()
        _require(label and item.rationale.strip(), "Blank class text.")
        _require(
            item.output_code not in class_by_code and label not in labels,
            "Duplicate output class code or label.",
        )
        class_by_code[item.output_code] = {
            **item.model_dump(), "label": label,
        }
        labels.add(label)

    decisions = {}
    members = {}
    forest_by_class = {}
    for item in parsed.decisions:
        code = item.source_evt_code
        _require(code in source_by_code, "Invented source EVT code.")
        _require(code not in decisions, "Duplicate source decision.")
        _require(item.output_code in class_by_code, "Undefined output class.")
        _require(item.rationale.strip(), "Blank decision rationale.")
        _require(
            all(isinstance(v, str) and v.strip() and len(v) <= 2000
                for v in item.unresolved),
            "Invalid unresolved item.",
        )
        if item.output_code in forest_by_class:
            _require(
                forest_by_class[item.output_code] is item.proposed_forest_land,
                "A shared output class has conflicting forest-land proposals.",
            )
        forest_by_class[item.output_code] = item.proposed_forest_land
        members.setdefault(item.output_code, []).append(code)
        decisions[code] = item.model_dump()

    _require(
        set(decisions) == set(source_by_code),
        "Every observed source EVT code needs exactly one decision.",
    )
    _require(
        set(members) == set(class_by_code),
        "Unused output classes are not permitted.",
    )

    for code, entry in source_by_code.items():
        decision = decisions[code]
        if entry["label_status"] == "missing_label":
            _require(
                decision["output_code"] == code
                and members[code] == [code]
                and decision["proposed_forest_land"] is None
                and bool(decision["unresolved"]),
                "Missing-label codes must retain identity, unknown forest status, "
                "and an unresolved review item.",
            )

    ordered = [decisions[c] for c in sorted(decisions)]
    result = {
        "schema": "mapcp_crosswalk_proposal_v1",
        "status": "draft_requires_human_review",
        "source_configuration_sha256": recorded,
        "classes": [class_by_code[c] for c in sorted(class_by_code)],
        "decisions": ordered,
        "unresolved_evt_codes": [
            d["source_evt_code"] for d in ordered
            if d["unresolved"] or d["proposed_forest_land"] is None
        ],
        "classification_performed": False,
        "forest_land_policy_approved": False,
        "limitations": [
            "A proposal digest binds content; it does not authenticate approval.",
            "No classification, configuration save, or geographic approval occurred.",
            "Forest-land values are proposals, not approved assignments.",
            "Acreage must be joined from verified run statistics; none is inferred here.",
        ],
    }
    result["proposal_sha256"] = _digest(result)
    return result
