"""Read-only, run-bound draft review. No approval, writes, network, or mapping."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from pydantic import BaseModel, ConfigDict, Field

import boundary_mapping as bm
from source_configuration import build_source_configuration
from crosswalk_proposal import ProposalRequest, build_crosswalk_proposal
from crosswalk_review import build_crosswalk_review

REFERENCE_URL = "https://www.landfire.gov/sites/default/files/CSV/LF2025/LF2025_EVT.csv"
REFERENCE_SHA256 = "5ccc130b250dbe709340afb2cc02ecdb3c4c374e2dba19cec91e2c2713e4963d"
MAX_REVIEW_CODES = 200
MAX_RESULT_BYTES = 4_000_000


class SourceReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    acquisition_directory: str = Field(pattern=r"^bacq_[A-Za-z0-9_-]+$", max_length=120)
    proposal: ProposalRequest | None = None


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _reference(project_data_root):
    directory = (Path(project_data_root) / "reference_data" / "landfire" / "lf2025_pinned_5ccc130b").resolve()
    csv_path = bm._direct_file(directory, "LF2025_EVT.csv")
    provenance_path = bm._direct_file(directory, "LF2025_EVT.source.json")
    data = csv_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    _require(digest == REFERENCE_SHA256, "Pinned reference checksum mismatch.")
    provenance = bm._read_json(provenance_path)
    _require(provenance.get("source_url") == REFERENCE_URL,
             "Reference provenance URL mismatch.")
    _require(provenance.get("sha256") == digest,
             "Reference provenance checksum mismatch.")
    return data


def review_source_configuration(outputs_root, project_data_root, request: SourceReviewRequest):
    """Inspect an existing boundary collection and return a bounded draft review.

    The pinned LF2025 table is associated with the LF2025 CONUS raster profile;
    the entire table is NOT described as CONUS-only. Product identification is
    based on validated band descriptions, not independent XML authentication.
    Caller authorization and geographic/policy approval are not inferred.
    """
    try:
        request = SourceReviewRequest.model_validate(request)
        root = Path(outputs_root).resolve()
        _, collection, tif, boundary = bm._load_collection(
            root, request.acquisition_directory
        )
        with rasterio.open(tif) as src:
            _require(all(np.issubdtype(np.dtype(t), np.integer) for t in src.dtypes),
                     "Source bands must have integer data types.")
            _require(all(value == -9999 for value in src.nodatavals),
                     "Source bands must declare NoData=-9999.")
        evt, inside, grid = bm._read_inputs(tif, boundary)
        _require(math.isclose(grid["cell_area_m2"], 900.0, rel_tol=0, abs_tol=1e-6),
                 "Review requires 900 square meters per cell.")
        valid = inside & (evt != -9999)
        values, counts = np.unique(evt[valid], return_counts=True)
        _require(0 < len(values) <= MAX_REVIEW_CODES,
                 "Draft review supports 1 to 200 observed codes; no subset was substituted.")
        observed = [int(value) for value in values]
        csv_bytes = _reference(project_data_root)
        profile = {"product": "EVT", "version": "LF2025", "region": "CONUS"}
        source = build_source_configuration(
            csv_bytes, observed,
            raster_profile=profile,
            catalog_record={**profile, "source_url": REFERENCE_URL,
                            "sha256": REFERENCE_SHA256},
            code_column="VALUE", name_column="EVT_NAME",
        )
        if request.proposal is None:
            proposal_request = {
                "source_configuration_sha256": source["configuration_sha256"],
                "classes": [{
                    "output_code": entry["source_evt_code"],
                    "label": f"candidate_EVT_{entry['source_evt_code']}",
                    "rationale": "Preserve source EVT identity pending professional review.",
                } for entry in source["entries"]],
                "decisions": [{
                    "source_evt_code": entry["source_evt_code"],
                    "output_code": entry["source_evt_code"],
                    "proposed_forest_land": None,
                    "rationale": "No forest-land policy or local grouping has been assigned.",
                    "unresolved": ["Forest-land policy requires explicit review."] + (
                        ["Official label unavailable."]
                        if entry["label_status"] == "missing_label" else []
                    ),
                } for entry in source["entries"]],
            }
        else:
            proposal_request = request.proposal.model_dump()
        proposal = build_crosswalk_proposal(source, proposal_request)
        evidence = {
            "source_run_id": request.acquisition_directory,
            "boundary_sha256": collection["boundary_sha256"],
            "source_raster_sha256": collection["extract"]["geotiff_sha256"],
            "source_configuration_sha256": source["configuration_sha256"],
            "proposal_sha256": proposal["proposal_sha256"],
            "total_grid_cells": int(evt.size),
            "outside_boundary_cells": int((~inside).sum()),
            "evt_nodata_inside_boundary_cells": int((inside & (evt == -9999)).sum()),
            "evt_counts": [{"source_evt_code": int(value), "cell_count": int(count)}
                           for value, count in zip(values, counts)],
        }
        review = build_crosswalk_review(source, proposal, evidence)
        _require(bm._digest(tif) == evidence["source_raster_sha256"]
                 and bm._digest(boundary) == evidence["boundary_sha256"],
                 "Source artifacts changed during review.")
        result = {
            "status": "draft_review_complete_requires_human_review",
            "acquisition_directory": request.acquisition_directory,
            "source_configuration": source,
            "proposal": proposal,
            "review": review,
            "grid": grid,
            "compatibility_basis": {
                "raster_profile": "Existing loader validates LF2025 CONUS band descriptions.",
                "reference": "Pinned LF2025 CSV checksum; table includes multiple regions.",
                "independent_xml_version_verification_performed": False,
            },
            "approval_authenticated": False,
            "classification_performed": False,
            "files_written": False,
            "limitations": [
                "No approval, configuration save, classification, or geographic authorization occurred.",
                "Raster band names and pinned reference association are not independent source validation.",
                "Cell-center acreage does not establish exact vector-boundary acreage or full coverage.",
                "Forest-land values remain proposals; null is unknown, not nonforest.",
                "This is preliminary planning evidence, not field inventory or legal authority.",
            ],
        }
        encoded = json.dumps(result, allow_nan=False).encode("utf-8")
        _require(len(encoded) <= MAX_RESULT_BYTES,
                 "Draft response exceeds bounded result size; no truncated review returned.")
        return result
    except Exception as exc:
        return {
            "status": "failed", "stage": "source_configuration_review",
            "error_type": type(exc).__name__,
            "error": "Draft review failed validation; no configuration was saved or classification performed.",
            "files_written": False, "classification_performed": False,
            "approval_authenticated": False,
        }
