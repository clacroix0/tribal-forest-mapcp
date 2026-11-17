"""Local operator-reviewed configuration saving. Never register as an MCP tool."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from source_configuration_workflow import (
    SourceReviewRequest,
    review_source_configuration,
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _read(path):
    path = Path(path)
    _require(path.is_file() and path.stat().st_size <= 5_000_000,
             "Required JSON file missing or too large.")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    _require(isinstance(value, dict), "Expected a JSON object.")
    return value


def _build_documents(result, configuration_id, version):
    """Convert an already rebuilt review; does not authenticate or record approval."""
    _require(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,49}", configuration_id or ""),
        "Invalid configuration ID.",
    )
    _require(re.fullmatch(r"v[1-9][0-9]{0,3}", version or ""),
             "Version must be v1 through v9999.")
    _require(
        result.get("status") == "draft_review_complete_requires_human_review",
        "A successful rebuilt review is required.",
    )
    source = result["source_configuration"]
    proposal = result["proposal"]
    review = result["review"]
    classes = {item["output_code"]: item for item in proposal["classes"]}
    machine_labels = {}
    reserved_labels = {
        item["label"] for item in classes.values()
        if re.fullmatch(r"candidate_[A-Z0-9_]+", item["label"])
    }
    for code in sorted(classes):
        proposed_label = classes[code]["label"]
        if re.fullmatch(r"candidate_[A-Z0-9_]+", proposed_label):
            machine_labels[code] = proposed_label
        else:
            label = f"candidate_CFG_{code}"
            while label in reserved_labels or label in machine_labels.values():
                label += "_X"
            machine_labels[code] = label

    decisions = proposal["decisions"]
    source_entries = {
        item["source_evt_code"]: item for item in source["entries"]
    }
    forest = {}
    for item in decisions:
        code = item["output_code"]
        value = item["proposed_forest_land"]
        _require(value is None or type(value) is bool,
                 "Forest-land proposal must be true, false, or null.")
        if code in forest:
            _require(forest[code] is value, "Conflicting class forest status.")
        forest[code] = value
    _require(set(classes) == set(forest), "Class/decision mismatch.")

    used = set(classes)
    fallback = next((code for code in range(32767, -1, -1)
                     if code not in used), None)
    _require(fallback is not None, "No unused fallback code is available.")

    fallback_label = "unmapped_evt"
    nodata_label = "nodata"

    table = [{
        "output_code": code,
        "output_label": machine_labels[code],
        "candidate_forest_land": forest[code],
        "description": classes[code]["label"] + ": " + classes[code]["rationale"],
        "reviewed_label": classes[code]["label"],
    } for code in sorted(classes)]
    table += [
        {
            "output_code": fallback,
            "output_label": fallback_label,
            "candidate_forest_land": None,
            "description": "Unexpected source code; unknown, not nonforest.",
        },
        {
            "output_code": -9999,
            "output_label": nodata_label,
            "candidate_forest_land": None,
            "description": "NoData; not a vegetation or nonforest category.",
        },
    ]

    name = f"runbound_{configuration_id}_{version}.json"
    record_name = f"runbound_{configuration_id}_{version}.approval.json"
    binding = {
        "source_run_id": result["acquisition_directory"],
        "boundary_sha256": review["run_evidence"]["boundary_sha256"],
        "source_raster_sha256":
            review["run_evidence"]["source_raster_sha256"],
    }
    crosswalk = {
        "crosswalk_id": f"runbound_{configuration_id}",
        "crosswalk_version": version,
        "cover_scheme_id": f"runbound_{configuration_id}",
        "cover_scheme_version": version,
        "approved_by": "user",
        "crosswalk_approval_note":
            "Local operator accepted this exact run-bound proposal and its "
            "unresolved items. This record does not authenticate identity, "
            "Tribal approval, or geographic authority.",
        "entries": [{
            "evt_code": item["source_evt_code"],
            "output_code": item["output_code"],
            "output_label": machine_labels[item["output_code"]],
            "candidate_forest_land": item["proposed_forest_land"],
            "official_source_name":
                source_entries[item["source_evt_code"]]["official_name"],
            "source_attributes":
                source_entries[item["source_evt_code"]]["source_attributes"],
            "unresolved": list(item["unresolved"]),
            "rationale": item["rationale"],
        } for item in decisions],
        "output_code_table": table,
        "nodata_value": -9999,
        "unmapped_valid_output_code": fallback,
        "run_binding": binding,
        "source_configuration_sha256": source["configuration_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "review_sha256": review["review_sha256"],
        "evt_add_url": source["source"]["url"],
        "evt_add_sha256": source["source"]["sha256"],
        "unresolved_evt_codes": proposal["unresolved_evt_codes"],
        "universal_review_flags": [
            "professional_forestry_review_required",
            "source_based_not_local_management_class_unless_explicitly_reviewed",
            "species_composition_not_directly_measured",
            "crown_cover_percentage_not_directly_measured",
            "overstory_understory_not_modeled",
            "disturbance_not_evaluated",
        ],
        "evc_evh_policy":
            "No EVC/EVH classification thresholds applied.",
        "disturbance_policy":
            "Not evaluated; no previous type or nonstocked status inferred.",
        "approval_record_filename": record_name,
    }
    record = {
        "schema": "mapcp_local_configuration_approval_v1",
        "crosswalk_filename": name,
        "crosswalk_payload_sha256": _digest(crosswalk),
        "run_binding": binding,
        "source_configuration_sha256": source["configuration_sha256"],
        "proposal_sha256": proposal["proposal_sha256"],
        "review_sha256": review["review_sha256"],
        "operator_confirmation_recorded": True,
        "identity_authenticated": False,
        "approval_method": "local_operator_interactive_terminal",
        "unresolved_evt_codes_accepted": proposal["unresolved_evt_codes"],
        "accepted_at_utc": datetime.now(timezone.utc).isoformat(),
        "review": review,
        "limitations": result["limitations"],
    }
    crosswalk["approval_record_sha256"] = _digest(record)
    return name, crosswalk, record_name, record


def validate_run_binding(project_data_root, acquisition_directory,
                         collection, crosswalk):
    """Reject changed run inputs or approval records before classification."""
    binding = crosswalk.get("run_binding")
    _require(isinstance(binding, dict), "Run-bound crosswalk lacks binding.")
    expected = {
        "source_run_id": acquisition_directory,
        "boundary_sha256": collection["boundary_sha256"],
        "source_raster_sha256": collection["extract"]["geotiff_sha256"],
    }
    _require(binding == expected, "Configuration does not match this run/boundary/raster.")
    name = crosswalk.get("approval_record_filename", "")
    _require(
        re.fullmatch(r"runbound_[A-Za-z0-9_-]+_v[1-9][0-9]{0,3}\.approval\.json", name),
        "Invalid approval record filename.",
    )
    directory = (Path(project_data_root) / "approvals").resolve()
    path = (directory / name).resolve()
    _require(path.parent == directory, "Approval record escapes its directory.")
    record = _read(path)
    browser_approved = record.get("schema") == "mapcp_browser_configuration_approval_v1"
    if browser_approved:
        from configuration_browser import validate_browser_approval
        validate_browser_approval(project_data_root, crosswalk, record)
    _require(
        browser_approved or (
            record.get("schema") == "mapcp_local_configuration_approval_v1"
            and record.get("operator_confirmation_recorded") is True
        ),
        "Missing local operator confirmation record.",
    )
    _require(_digest(record) == crosswalk.get("approval_record_sha256"),
             "Approval record changed.")
    payload = dict(crosswalk)
    payload.pop("approval_record_sha256", None)
    _require(_digest(payload) == record.get("crosswalk_payload_sha256"),
             "Crosswalk changed after local acceptance.")
    _require(record.get("run_binding") == expected, "Approval run mismatch.")
    for key in ("source_configuration_sha256", "proposal_sha256", "review_sha256"):
        _require(record.get(key) == crosswalk.get(key), "Approval digest mismatch.")


def _write_documents(project_data_root, name, crosswalk, record_name, record):
    """Internal writer; caller must obtain real local operator confirmation first."""
    pdr = Path(project_data_root)
    directory = pdr / "run_crosswalks"
    approvals = pdr / "approvals"
    target = directory / name
    record_path = approvals / record_name
    _require(not target.exists() and not record_path.exists(),
             "Configuration or approval record already exists; no overwrite.")
    directory.mkdir(parents=True, exist_ok=True)
    approvals.mkdir(parents=True, exist_ok=True)
    with record_path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(crosswalk, stream, indent=2, allow_nan=False)
    return target


def main():
    parser = argparse.ArgumentParser(
        description="Local interactive save only. Never expose this CLI through MCP."
    )
    parser.add_argument("request_file",
                        help="Local JSON containing the reviewed SourceReviewRequest.")
    parser.add_argument("--id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--proposal-sha256", required=True)
    parser.add_argument("--review-sha256", required=True)
    args = parser.parse_args()
    _require(sys.stdin.isatty(),
             "Interactive operator terminal required; piped approval is refused.")
    root = Path(__file__).resolve().parent
    request = SourceReviewRequest.model_validate(_read(args.request_file))
    result = review_source_configuration(
        root / "outputs", root / "project_data", request
    )
    _require(result.get("status") ==
             "draft_review_complete_requires_human_review",
             "Fresh artifact review failed; nothing saved.")
    _require(
        result["source_configuration"]["configuration_sha256"] == args.source_sha256
        and result["proposal"]["proposal_sha256"] == args.proposal_sha256
        and result["review"]["review_sha256"] == args.review_sha256,
        "Fresh review differs from the reviewed digests; nothing saved.",
    )
    name, crosswalk, record_name, record = _build_documents(
        result, args.id, args.version
    )
    print(json.dumps({
        "target_filename": name,
        "output_code_table": crosswalk["output_code_table"],
        "binding": crosswalk["run_binding"],
        "review_sha256": args.review_sha256,
        "coverage": result["review"]["coverage"],
        "decisions": result["review"]["source_rows"],
        "limitations": result["limitations"],
    }, indent=2))
    phrase = "SAVE " + args.review_sha256
    answer = input(
        "\nAccept these exact decisions, unknowns, and limitations?\n"
        f"Type {phrase}\n> "
    )
    _require(answer == phrase, "Cancelled; nothing saved.")
    fresh = review_source_configuration(
        root / "outputs", root / "project_data", request
    )
    _require(fresh == result, "Inputs changed while awaiting confirmation.")
    target = _write_documents(
        root / "project_data", name, crosswalk, record_name, record
    )
    print(f"Saved local run-bound configuration: {target.name}")
    print("No mapping, deployment, or authenticated hosted approval occurred.")


if __name__ == "__main__":
    main()
