# tests/test_cover_scheme_models.py
#
# Tribal Forest MapCP — Slice 1: CoverSchemeConfig model tests
#
# 19 committed tests — must pass on a fresh clone with no project_data/.
# 8 conditional tests — skipped when the local Mescalero config is absent.
#
# All committed tests use either inline dicts or the committed public fixture:
#   tests/fixtures/example_southwest_cover_scheme_v1.json
#
# No Mescalero definitions are committed.  The local Mescalero config is at:
#   project_data/cover_schemes/mescalero_v1_cover_scheme_v1.json
# and is Git-ignored by default.
#
# Run: pytest tests/test_cover_scheme_models.py -v

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cover_scheme_models import (
    CoverSchemeClass,
    CoverSchemeConfig,
    load_cover_scheme_config,
    save_cover_scheme_config,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PUBLIC_FIXTURE = FIXTURES_DIR / "example_southwest_cover_scheme_v1.json"

MESCALERO_CONFIG = (
    Path(__file__).parent.parent
    / "project_data"
    / "cover_schemes"
    / "mescalero_v1_cover_scheme_v1.json"
)

MESCALERO_PRESENT = MESCALERO_CONFIG.is_file()


# ---------------------------------------------------------------------------
# Helper: build a minimal valid CoverSchemeClass dict
# ---------------------------------------------------------------------------

def _minimal_class(
    code: str = "XX",
    status: str = "assignable",
    output_code: str | None = None,
    forest_land: bool | None = True,
    label: str | None = None,
    flags: list[str] | None = None,
) -> dict:
    return {
        "candidate_code": code,
        "candidate_name": f"Test class {code}",
        "first_pass_candidate_label": label if label is not None else f"candidate_{code}",
        "candidate_forest_land": forest_land,
        "structure_group": "timberland",
        "local_definition_summary": "Test.",
        "source_measurability": "not_directly_measurable",
        "first_pass_assignment_status": status,
        "first_pass_output_code": output_code,
        "review_flags_required": flags if flags is not None else ["test_flag"],
        "protected_from_generalization_merge": False,
        "notes": None,
    }


def _minimal_config_dict(classes: list[dict] | None = None) -> dict:
    """Return a minimal valid CoverSchemeConfig dict with one assignable class."""
    if classes is None:
        classes = [_minimal_class()]
    return {
        "schema_type": "cover_scheme_configuration",
        "scheme_id": "test_v1",
        "scheme_version": "v1",
        "scheme_label": "Test Scheme v1",
        "source_authority": "public_starter_proposed",
        "source_document_reference": None,
        "geographic_applicability": "Test only",
        "approved_by": None,
        "approved_at_utc": None,
        "approval_record": None,
        "woodland_is_forest_land": True,
        "nonstocked_policy": "Nonstocked classes are preserved for review.",
        "one_primary_class_only": True,
        "forest_land_policy_notes": "Starter scheme; policy not yet approved.",
        "classes": classes,
        "limitations": ["Test limitation."],
        "change_control": "Do not modify without approval.",
    }


# ===========================================================================
# COMMITTED TESTS — 19 total, must pass on fresh clone
# ===========================================================================


# ---------------------------------------------------------------------------
# 1. Full serialize/deserialize identity
# ---------------------------------------------------------------------------

class TestValidRoundTrip:
    def test_cover_scheme_config_valid_round_trip(self, tmp_path):
        config = CoverSchemeConfig.model_validate(
            _minimal_config_dict()
        )
        saved = save_cover_scheme_config(config, tmp_path)
        loaded = load_cover_scheme_config(saved)
        assert loaded == config


# ---------------------------------------------------------------------------
# 2. extra = "forbid" — top-level config field and class field
# ---------------------------------------------------------------------------

class TestExtraFieldsForbidden:
    def test_cover_scheme_config_rejects_extra_fields(self):
        """Unknown top-level config field must be rejected."""
        data = _minimal_config_dict()
        data["unexpected_top_level_key"] = "oops"
        with pytest.raises(ValidationError):
            CoverSchemeConfig.model_validate(data)

    def test_cover_scheme_class_rejects_extra_fields(self):
        """Unknown field inside a class record must be rejected."""
        cls_dict = _minimal_class()
        cls_dict["unknown_class_field"] = "bad"
        with pytest.raises(ValidationError):
            CoverSchemeClass.model_validate(cls_dict)


# ---------------------------------------------------------------------------
# 3. local_approved + approved_by=None rejected (Rule 2)
# ---------------------------------------------------------------------------

class TestUnapprovedLocalScheme:
    def test_cover_scheme_config_rejects_unapproved_local_scheme(self):
        data = _minimal_config_dict()
        data["source_authority"] = "local_approved"
        data["approved_by"] = None
        with pytest.raises(ValidationError, match="approved_by"):
            CoverSchemeConfig.model_validate(data)


# ---------------------------------------------------------------------------
# 4–7. Field-level rules on CoverSchemeClass
# ---------------------------------------------------------------------------

class TestFieldLevelRules:
    def test_cover_scheme_class_rejects_null_output_code_when_consolidated(self):
        """Rule 4: output_code null when consolidated_to_broader_class."""
        cls_dict = _minimal_class(status="consolidated_to_broader_class", output_code=None)
        with pytest.raises(ValidationError, match="first_pass_output_code"):
            CoverSchemeClass.model_validate(cls_dict)

    def test_cover_scheme_class_rejects_nonnull_output_code_when_assignable(self):
        """Rule 3: output_code non-null when assignable."""
        cls_dict = _minimal_class(status="assignable", output_code="SOME_CODE")
        with pytest.raises(ValidationError, match="first_pass_output_code"):
            CoverSchemeClass.model_validate(cls_dict)

    def test_cover_scheme_class_rejects_nonnull_output_code_when_not_assignable(self):
        """Rule 5: output_code non-null when not_assignable."""
        cls_dict = _minimal_class(
            status="not_assignable",
            output_code="SOME_CODE",
            forest_land=None,
            flags=["reason_flag"],
        )
        with pytest.raises(ValidationError, match="first_pass_output_code"):
            CoverSchemeClass.model_validate(cls_dict)

    def test_cover_scheme_class_rejects_nonnull_forest_land_when_not_assignable(self):
        """Rule 6: candidate_forest_land non-null when not_assignable."""
        cls_dict = _minimal_class(
            status="not_assignable",
            output_code=None,
            forest_land=True,   # must be null
            flags=["reason_flag"],
        )
        with pytest.raises(ValidationError, match="candidate_forest_land"):
            CoverSchemeClass.model_validate(cls_dict)

    def test_cover_scheme_class_rejects_empty_flags_when_not_assignable(self):
        """Rule 7: review_flags_required empty when not_assignable."""
        cls_dict = _minimal_class(
            status="not_assignable",
            output_code=None,
            forest_land=None,
            flags=[],  # must be non-empty
        )
        with pytest.raises(ValidationError, match="review_flags_required"):
            CoverSchemeClass.model_validate(cls_dict)

    def test_cover_scheme_class_first_pass_candidate_label_used_not_prefix(self):
        """Field first_pass_candidate_label is present; candidate_label_prefix must not exist."""
        cls_dict = _minimal_class()
        validated = CoverSchemeClass.model_validate(cls_dict)
        assert hasattr(validated, "first_pass_candidate_label")
        assert not hasattr(validated, "candidate_label_prefix")
        assert validated.first_pass_candidate_label.startswith("candidate_")


# ---------------------------------------------------------------------------
# 8–11. Cross-record validation rules on CoverSchemeConfig
# ---------------------------------------------------------------------------

class TestCrossRecordValidation:
    def _config_with_consolidated(
        self,
        output_code: str,
        consolidated_label: str = "candidate_TARGET",
        consolidated_forest_land: bool | None = True,
        target_label: str = "candidate_TARGET",
        target_forest_land: bool | None = True,
        target_status: str = "assignable",
    ) -> dict:
        target = _minimal_class(
            code="TARGET",
            status=target_status,
            forest_land=target_forest_land,
            label=target_label,
        )
        consolidated = _minimal_class(
            code="SRC",
            status="consolidated_to_broader_class",
            output_code=output_code,
            forest_land=consolidated_forest_land,
            label=consolidated_label,
        )
        return _minimal_config_dict(classes=[target, consolidated])

    def test_config_rejects_consolidated_with_missing_target(self):
        """Rule 8: output_code references a non-existent candidate_code."""
        data = self._config_with_consolidated(output_code="DOES_NOT_EXIST")
        with pytest.raises(ValidationError, match="does not match any candidate_code"):
            CoverSchemeConfig.model_validate(data)

    def test_config_rejects_consolidated_targeting_non_assignable(self):
        """Rule 9: target is itself consolidated_to_broader_class (chain).

        TARGET → DUMMY must be a valid consolidation (satisfying Rules 8/10/11)
        so that the validator reaches SRC → TARGET and raises Rule 9.
        DUMMY must share TARGET's label and forest_land so Rules 10/11 pass for
        TARGET → DUMMY, leaving only Rule 9 to fire for SRC → TARGET.
        """
        # DUMMY: assignable; shares TARGET's label and forest_land
        dummy = _minimal_class(
            code="DUMMY",
            label="candidate_TARGET",   # must match TARGET's label for Rule 10
            forest_land=True,           # must match TARGET's forest_land for Rule 11
        )
        # TARGET: consolidated → DUMMY; valid consolidation (Rules 8/10/11 satisfied)
        second_target = _minimal_class(
            code="TARGET",
            status="consolidated_to_broader_class",
            output_code="DUMMY",
            forest_land=True,
            label="candidate_TARGET",
        )
        # SRC → TARGET: Rule 9 must fire because TARGET is not 'assignable'
        consolidated = _minimal_class(
            code="SRC",
            status="consolidated_to_broader_class",
            output_code="TARGET",
            forest_land=True,
            label="candidate_TARGET",
        )
        data = _minimal_config_dict(classes=[second_target, dummy, consolidated])
        with pytest.raises(ValidationError, match="not 'assignable'"):
            CoverSchemeConfig.model_validate(data)

    def test_config_rejects_consolidated_with_label_mismatch(self):
        """Rule 10: consolidated label differs from target label."""
        data = self._config_with_consolidated(
            output_code="TARGET",
            consolidated_label="candidate_WRONG_LABEL",
            target_label="candidate_TARGET",
        )
        with pytest.raises(ValidationError, match="first_pass_candidate_label"):
            CoverSchemeConfig.model_validate(data)

    def test_config_rejects_consolidated_with_forest_land_mismatch(self):
        """Rule 11: consolidated forest_land differs from target (true vs false)."""
        data = self._config_with_consolidated(
            output_code="TARGET",
            consolidated_forest_land=False,
            target_forest_land=True,
        )
        with pytest.raises(ValidationError, match="candidate_forest_land"):
            CoverSchemeConfig.model_validate(data)

    def test_config_rejects_consolidated_with_null_vs_true_forest_land_mismatch(self):
        """Rule 11: null does not match true."""
        data = self._config_with_consolidated(
            output_code="TARGET",
            consolidated_forest_land=None,
            target_forest_land=True,
        )
        with pytest.raises(ValidationError, match="candidate_forest_land"):
            CoverSchemeConfig.model_validate(data)


# ---------------------------------------------------------------------------
# 12–13. Save/load
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_save_creates_file_in_project_data(self, tmp_path):
        config = CoverSchemeConfig.model_validate(_minimal_config_dict())
        result = save_cover_scheme_config(config, tmp_path)
        assert result.is_file()
        assert result.parent.name == "cover_schemes"
        assert result.name == "test_v1_v1_cover_scheme.json"

    def test_save_does_not_overwrite_existing_version(self, tmp_path):
        config = CoverSchemeConfig.model_validate(_minimal_config_dict())
        save_cover_scheme_config(config, tmp_path)
        with pytest.raises(FileExistsError):
            save_cover_scheme_config(config, tmp_path)

    def test_load_returns_identical_model(self, tmp_path):
        config = CoverSchemeConfig.model_validate(_minimal_config_dict())
        path = save_cover_scheme_config(config, tmp_path)
        loaded = load_cover_scheme_config(path)
        assert loaded == config


# ---------------------------------------------------------------------------
# 14–15. Public fixture tests
# ---------------------------------------------------------------------------

class TestPublicFixture:
    def test_public_fixture_passes_full_validation(self):
        config = load_cover_scheme_config(PUBLIC_FIXTURE)
        assert config.schema_type == "cover_scheme_configuration"
        assert config.source_authority == "public_starter_proposed"
        assert config.approved_by is None

    def test_public_fixture_has_consolidated_entry_with_output_code(self):
        config = load_cover_scheme_config(PUBLIC_FIXTURE)
        consolidated = [
            c for c in config.classes
            if c.first_pass_assignment_status == "consolidated_to_broader_class"
        ]
        assert len(consolidated) >= 1
        for c in consolidated:
            assert c.first_pass_output_code is not None

    def test_public_fixture_has_not_assignable_entry_with_null_forest_land(self):
        config = load_cover_scheme_config(PUBLIC_FIXTURE)
        not_assignable = [
            c for c in config.classes
            if c.first_pass_assignment_status == "not_assignable"
        ]
        assert len(not_assignable) >= 1
        for c in not_assignable:
            assert c.candidate_forest_land is None
            assert c.first_pass_output_code is None
            assert len(c.review_flags_required) >= 1


# ===========================================================================
# CONDITIONAL TESTS — skip when local Mescalero config is absent
# ===========================================================================

skip_no_mescalero = pytest.mark.skipif(
    not MESCALERO_PRESENT,
    reason="Local Mescalero config not present — skipped on fresh clone. "
           "Create project_data/cover_schemes/mescalero_v1_cover_scheme_v1.json locally.",
)


@skip_no_mescalero
def test_mescalero_v1_fixture_passes_validation():
    """Local Mescalero config must pass full model and cross-record validation."""
    config = load_cover_scheme_config(MESCALERO_CONFIG)
    assert config.scheme_id == "mescalero_v1"
    assert config.scheme_version == "v1"


@skip_no_mescalero
def test_mescalero_v1_fixture_has_29_local_codes():
    """Local config must contain exactly 29 local Mescalero target codes."""
    config = load_cover_scheme_config(MESCALERO_CONFIG)
    local_codes = {
        "P", "PM", "MC", "DF", "WF", "A", "BS", "ES", "SF", "NT", "AT",
        "PJ", "W", "CO", "RO", "SC", "WI", "NW", "B", "IH", "OK",
        "G", "O", "NR", "R", "AG", "U", "BR", "WA",
    }
    present_codes = {c.candidate_code for c in config.classes}
    missing = local_codes - present_codes
    assert not missing, f"Missing local codes: {missing}"
    # Total entries: 29 local + 3 RIP_* = 32
    assert len(config.classes) == 32, (
        f"Expected 32 total entries (29 local + 3 RIP_*), got {len(config.classes)}"
    )


@skip_no_mescalero
def test_mescalero_v1_fixture_nt_nw_are_forest_land():
    """NT and NW must have candidate_forest_land = True."""
    config = load_cover_scheme_config(MESCALERO_CONFIG)
    by_code = {c.candidate_code: c for c in config.classes}
    assert by_code["NT"].candidate_forest_land is True
    assert by_code["NW"].candidate_forest_land is True


@skip_no_mescalero
def test_mescalero_v1_fixture_woodland_is_forest_land():
    """Top-level woodland_is_forest_land must be True."""
    config = load_cover_scheme_config(MESCALERO_CONFIG)
    assert config.woodland_is_forest_land is True


@skip_no_mescalero
def test_mescalero_v1_fixture_co_ro_sc_wi_b_consolidated_to_rip_woody():
    """CO, RO, SC, WI, B must consolidate to RIP_WOODY with matching forest-land."""
    config = load_cover_scheme_config(MESCALERO_CONFIG)
    by_code = {c.candidate_code: c for c in config.classes}
    rip_woody = by_code["RIP_WOODY"]
    for code in ("CO", "RO", "SC", "WI", "B"):
        cls = by_code[code]
        assert cls.first_pass_assignment_status == "consolidated_to_broader_class", (
            f"{code}: expected consolidated_to_broader_class"
        )
        assert cls.first_pass_output_code == "RIP_WOODY", (
            f"{code}: expected first_pass_output_code='RIP_WOODY'"
        )
        assert cls.first_pass_candidate_label == rip_woody.first_pass_candidate_label, (
            f"{code}: label mismatch with RIP_WOODY"
        )
        assert cls.candidate_forest_land == rip_woody.candidate_forest_land, (
            f"{code}: forest_land mismatch with RIP_WOODY"
        )
        assert cls.candidate_forest_land is True, (
            f"{code}: expected candidate_forest_land=True"
        )


@skip_no_mescalero
def test_mescalero_v1_fixture_r_consolidated_to_rip_nonforest():
    """R must consolidate to RIP_NONFOREST with candidate_forest_land=False."""
    config = load_cover_scheme_config(MESCALERO_CONFIG)
    by_code = {c.candidate_code: c for c in config.classes}
    r = by_code["R"]
    rip_nf = by_code["RIP_NONFOREST"]
    assert r.first_pass_assignment_status == "consolidated_to_broader_class"
    assert r.first_pass_output_code == "RIP_NONFOREST"
    assert r.first_pass_candidate_label == rip_nf.first_pass_candidate_label
    assert r.candidate_forest_land is False
    assert rip_nf.candidate_forest_land is False


@skip_no_mescalero
def test_mescalero_v1_fixture_rip_uncertain_has_null_forest_land():
    """RIP_UNCERTAIN must have candidate_forest_land = None (not False)."""
    config = load_cover_scheme_config(MESCALERO_CONFIG)
    by_code = {c.candidate_code: c for c in config.classes}
    rip_u = by_code["RIP_UNCERTAIN"]
    assert rip_u.candidate_forest_land is None, (
        "RIP_UNCERTAIN candidate_forest_land must be null, not False"
    )
    assert rip_u.first_pass_assignment_status == "assignable"
    assert rip_u.first_pass_output_code is None


@skip_no_mescalero
def test_mescalero_v1_fixture_required_review_flags_present():
    """
    Required review flags must be present on species-composition classes
    and on RIP_WOODY.
    """
    config = load_cover_scheme_config(MESCALERO_CONFIG)
    by_code = {c.candidate_code: c for c in config.classes}

    species_comp_classes = ("P", "PM", "MC", "DF", "WF", "A", "BS", "ES", "SF")
    for code in species_comp_classes:
        flags = by_code[code].review_flags_required
        assert "species_composition_not_directly_measured" in flags, (
            f"{code}: missing species_composition_not_directly_measured"
        )
        assert "crown_cover_percentage_not_directly_measured" in flags, (
            f"{code}: missing crown_cover_percentage_not_directly_measured"
        )

    rip_woody_flags = by_code["RIP_WOODY"].review_flags_required
    assert "riparian_subtype_not_resolved" in rip_woody_flags
    assert "species_review_required" in rip_woody_flags

    rip_uncertain_flags = by_code["RIP_UNCERTAIN"].review_flags_required
    assert len(rip_uncertain_flags) >= 1
