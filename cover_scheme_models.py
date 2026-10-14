"""
cover_scheme_models.py — Tribal Forest MapCP

Pydantic models for cover-scheme configurations, with field-level and
cross-record validation.  Save/load helpers write to project_data/.

These models are internal helpers only.  No public MCP tool is defined here.
No raster processing, network access, or GIS operations are performed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# CoverSchemeClass
# ---------------------------------------------------------------------------

class CoverSchemeClass(BaseModel):
    """One candidate cover-type class entry inside a CoverSchemeConfig."""

    model_config = ConfigDict(extra="forbid")

    candidate_code: str = Field(min_length=1, max_length=20)
    candidate_name: str = Field(min_length=1)
    first_pass_candidate_label: str = Field(min_length=1)
    candidate_forest_land: Optional[bool] = None
    structure_group: Literal[
        "timberland",
        "woodland",
        "nonforest",
        "nonstocked_timberland",
        "nonstocked_woodland",
        "riparian_woody_forest",
        "riparian_nonforest",
        "riparian_uncertain",
    ]
    local_definition_summary: str = Field(min_length=1)
    source_measurability: Literal[
        "not_directly_measurable",
        "approximate_via_evt",
        "approximate_via_evt_evc_evh",
    ]
    first_pass_assignment_status: Literal[
        "assignable",
        "consolidated_to_broader_class",
        "not_assignable",
    ]
    first_pass_output_code: Optional[str] = None
    review_flags_required: list[str] = Field(default_factory=list)
    protected_from_generalization_merge: bool
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _validate_first_pass_fields(self) -> "CoverSchemeClass":
        status = self.first_pass_assignment_status
        output_code = self.first_pass_output_code
        forest_land = self.candidate_forest_land
        flags = self.review_flags_required

        if status == "consolidated_to_broader_class":
            # Rule 4: output code must be present
            if output_code is None:
                raise ValueError(
                    f"Class '{self.candidate_code}': first_pass_output_code "
                    "must be non-null when first_pass_assignment_status is "
                    "'consolidated_to_broader_class'."
                )

        elif status == "assignable":
            # Rule 3: output code must be absent
            if output_code is not None:
                raise ValueError(
                    f"Class '{self.candidate_code}': first_pass_output_code "
                    "must be null when first_pass_assignment_status is "
                    "'assignable'."
                )

        elif status == "not_assignable":
            # Rule 5: output code must be absent
            if output_code is not None:
                raise ValueError(
                    f"Class '{self.candidate_code}': first_pass_output_code "
                    "must be null when first_pass_assignment_status is "
                    "'not_assignable'."
                )
            # Rule 6: candidate_forest_land must be null
            if forest_land is not None:
                raise ValueError(
                    f"Class '{self.candidate_code}': candidate_forest_land "
                    "must be null when first_pass_assignment_status is "
                    "'not_assignable'."
                )
            # Rule 7: review_flags_required must be non-empty
            if not flags:
                raise ValueError(
                    f"Class '{self.candidate_code}': review_flags_required "
                    "must contain at least one flag explaining why first-pass "
                    "assignment is unavailable when "
                    "first_pass_assignment_status is 'not_assignable'."
                )

        return self


# ---------------------------------------------------------------------------
# CoverSchemeConfig
# ---------------------------------------------------------------------------

class CoverSchemeConfig(BaseModel):
    """
    Approved versioned cover-scheme configuration.

    Stores all candidate class definitions, forest-land policy, and
    first-pass assignment rules for one approved project cover scheme.
    This is a controlled project input, not an output artifact.
    """

    model_config = ConfigDict(extra="forbid")

    schema_type: Literal["cover_scheme_configuration"]
    scheme_id: str = Field(min_length=1, max_length=80)
    scheme_version: str = Field(min_length=1, max_length=20)
    scheme_label: str = Field(min_length=1, max_length=200)
    source_authority: Literal[
        "local_approved",
        "public_starter_proposed",
        "plain_language_draft",
    ]
    source_document_reference: Optional[str] = None
    geographic_applicability: str = Field(min_length=1)
    approved_by: Optional[str] = None
    approved_at_utc: Optional[str] = None
    approval_record: Optional[str] = None
    woodland_is_forest_land: bool
    nonstocked_policy: str = Field(min_length=1)
    one_primary_class_only: bool
    forest_land_policy_notes: str = Field(min_length=1)
    classes: list[CoverSchemeClass] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    change_control: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_config(self) -> "CoverSchemeConfig":
        # Rule 2: local_approved requires approved_by
        if self.source_authority == "local_approved" and self.approved_by is None:
            raise ValueError(
                "source_authority 'local_approved' requires approved_by to "
                "be non-null."
            )

        # Build lookup for cross-record rules 8–11
        code_to_class: dict[str, CoverSchemeClass] = {
            cls.candidate_code: cls for cls in self.classes
        }

        for cls in self.classes:
            if cls.first_pass_assignment_status != "consolidated_to_broader_class":
                continue

            target_code = cls.first_pass_output_code  # non-null guaranteed by field validator
            assert target_code is not None  # for type narrowing

            # Rule 8: target must exist
            if target_code not in code_to_class:
                raise ValueError(
                    f"Class '{cls.candidate_code}': first_pass_output_code "
                    f"'{target_code}' does not match any candidate_code in "
                    "this cover scheme."
                )

            target = code_to_class[target_code]

            # Rule 9: target must be assignable (no chains or cycles)
            if target.first_pass_assignment_status != "assignable":
                raise ValueError(
                    f"Class '{cls.candidate_code}': first_pass_output_code "
                    f"'{target_code}' references a class whose "
                    f"first_pass_assignment_status is "
                    f"'{target.first_pass_assignment_status}', not "
                    "'assignable'. Consolidation chains and cycles are not "
                    "allowed."
                )

            # Rule 10: first_pass_candidate_label must match target's
            if cls.first_pass_candidate_label != target.first_pass_candidate_label:
                raise ValueError(
                    f"Class '{cls.candidate_code}': first_pass_candidate_label "
                    f"'{cls.first_pass_candidate_label}' does not match target "
                    f"'{target_code}' label "
                    f"'{target.first_pass_candidate_label}'."
                )

            # Rule 11: candidate_forest_land must match target's (null==null required)
            if cls.candidate_forest_land != target.candidate_forest_land:
                raise ValueError(
                    f"Class '{cls.candidate_code}': candidate_forest_land "
                    f"'{cls.candidate_forest_land}' does not match target "
                    f"'{target_code}' candidate_forest_land "
                    f"'{target.candidate_forest_land}'."
                )

        return self


# ---------------------------------------------------------------------------
# Save / load helpers
# ---------------------------------------------------------------------------

def save_cover_scheme_config(
    config: CoverSchemeConfig,
    project_data_root: Path,
) -> Path:
    """
    Write an approved CoverSchemeConfig to project_data/cover_schemes/.

    Raises FileExistsError if the versioned file already exists.
    Never overwrites an existing approved configuration.
    """
    target_dir = project_data_root / "cover_schemes"
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{config.scheme_id}_{config.scheme_version}_cover_scheme.json"
    target_path = target_dir / filename

    if target_path.exists():
        raise FileExistsError(
            f"Cover scheme file already exists and will not be overwritten: "
            f"{target_path}"
        )

    target_path.write_text(
        config.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return target_path


def load_cover_scheme_config(path: Path) -> CoverSchemeConfig:
    """
    Load and validate a CoverSchemeConfig from a JSON file.

    Raises ValidationError if the file does not match the schema.
    """
    return CoverSchemeConfig.model_validate_json(
        path.read_text(encoding="utf-8")
    )
