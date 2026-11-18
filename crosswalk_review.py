"""Pure run-bound crosswalk review. No IO, approval, or classification."""
from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from crosswalk_proposal import ProposalError, build_crosswalk_proposal

ACRE_M2 = 4046.8564224


class ReviewError(ValueError):
    pass


class EVTCount(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_evt_code: int = Field(ge=0, le=32767)
    cell_count: int = Field(gt=0)


class RunEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_run_id: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$"
    )
    boundary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_raster_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    total_grid_cells: int = Field(gt=0, le=25_000_000)
    outside_boundary_cells: int = Field(ge=0)
    evt_nodata_inside_boundary_cells: int = Field(ge=0)
    evt_counts: list[EVTCount] = Field(min_length=1, max_length=10000)


def _require(condition, message):
    if not condition:
        raise ReviewError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def build_crosswalk_review(
    source_configuration: dict,
    proposal: dict,
    run_evidence: dict,
) -> dict:
    """Join proposed rules to validated-run evidence for a 30 m mapping profile.

    Evidence must be supplied internally from inspected artifacts. Hash fields
    bind supplied content; this function does not read or authenticate files.
    Boundary/raster hashes are not proof of geographic or human approval.
    """
    _require(isinstance(proposal, dict), "Proposal must be an object.")
    request = {
        key: proposal.get(key)
        for key in ("source_configuration_sha256", "classes", "decisions")
    }
    try:
        rebuilt = build_crosswalk_proposal(source_configuration, request)
    except (ProposalError, TypeError, ValueError):
        raise ReviewError("Proposal/source validation failed.") from None
    _require(proposal == rebuilt, "Proposal content or digest changed.")

    try:
        run = RunEvidence.model_validate(run_evidence)
    except ValidationError:
        raise ReviewError("Invalid run-evidence structure.") from None

    _require(
        run.source_configuration_sha256
        == rebuilt["source_configuration_sha256"],
        "Run/source configuration mismatch.",
    )
    _require(
        run.proposal_sha256 == rebuilt["proposal_sha256"],
        "Run/proposal mismatch.",
    )

    counts = {}
    for item in run.evt_counts:
        _require(
            item.source_evt_code not in counts,
            "Duplicate observed EVT count.",
        )
        counts[item.source_evt_code] = item.cell_count
    decisions = {
        item["source_evt_code"]: item for item in rebuilt["decisions"]
    }
    _require(
        set(counts) == set(decisions),
        "Observed EVT counts must match all and only the proposal's source codes.",
    )

    valid = sum(counts.values())
    outside = run.outside_boundary_cells
    nodata = run.evt_nodata_inside_boundary_cells
    _require(
        valid + outside + nodata == run.total_grid_cells,
        "Cell counts do not reconcile with the raster grid.",
    )

    def area(cells):
        return {
            "cell_count": cells,
            "square_meters": cells * 900,
            "acres": round(cells * 900 / ACRE_M2, 6),
        }

    sources = {
        item["source_evt_code"]: item
        for item in source_configuration["entries"]
    }
    by_class = {item["output_code"]: 0 for item in rebuilt["classes"]}
    rows = []
    unresolved_codes = set(rebuilt["unresolved_evt_codes"])
    unresolved_cells = 0

    for code in sorted(counts):
        decision = decisions[code]
        cells = counts[code]
        by_class[decision["output_code"]] += cells
        unresolved = code in unresolved_codes
        if unresolved:
            unresolved_cells += cells
        rows.append({
            "source_evt_code": code,
            "official_name": sources[code]["official_name"],
            "source_attributes": dict(sources[code]["source_attributes"]),
            "proposed_output_code": decision["output_code"],
            "proposed_forest_land": decision["proposed_forest_land"],
            "rationale": decision["rationale"],
            "unresolved": list(decision["unresolved"]),
            "requires_resolution": unresolved,
            **area(cells),
        })

    result = {
        "schema": "mapcp_crosswalk_review_v1",
        "status": "draft_requires_human_review",
        "source_configuration_sha256": run.source_configuration_sha256,
        "proposal_sha256": run.proposal_sha256,
        "run_evidence": {
            **run.model_dump(),
            "evt_counts": [
                {"source_evt_code": code, "cell_count": counts[code]}
                for code in sorted(counts)
            ],
        },
        "area_method": "30 m grid cell-center inclusion; 900 m2 per counted cell",
        "source_rows": rows,
        "proposed_class_rows": [
            {**item, **area(by_class[item["output_code"]])}
            for item in rebuilt["classes"]
        ],
        "coverage": {
            "valid_source_cells": area(valid),
            "outside_boundary_cells": area(outside),
            "evt_nodata_inside_boundary": area(nodata),
            "unresolved_valid_cells": area(unresolved_cells),
            "inside_boundary_cells": area(valid + nodata),
        },
        "checks": {
            "grid_cell_closure": True,
            "proposed_class_cell_closure":
                sum(by_class.values()) == valid,
        },
        "classification_performed": False,
        "approval_authenticated": False,
        "limitations": [
            "Counts and hashes require an internal verified-artifact adapter.",
            "Grid-cell acreage is not exact vector-boundary acreage.",
            "Source coverage is not independent classification accuracy.",
            "A review digest is not human approval or geographic suitability.",
            "Forest-land assignments remain proposals only.",
        ],
    }
    result["review_sha256"] = _digest(result)
    return result
