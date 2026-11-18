"""Explicit-selection safeguards. Synthetic inputs; no network or mapping."""
import inspect

import pytest
from pydantic import ValidationError

import boundary_mapping as bm
import server
from mcp.server.mcpserver.exceptions import ToolError


MANIFEST = (
    "lfps_v2_collection_20261116T000000000000Z_"
    "123e4567-e89b-42d3-a456-426614174000.json"
)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_sample_missing_crosswalk_blocks_before_loader(monkeypatch, value):
    def forbidden(*args, **kwargs):
        raise AssertionError("Crosswalk loader must not be reached")

    monkeypatch.setattr(server, "_load_crosswalk", forbidden)
    with pytest.raises(ToolError, match="Explicit crosswalk selection"):
        server.map_candidate_cover_types(MANIFEST, value)


def test_sample_omitted_crosswalk_has_no_pilot_default(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Crosswalk loader must not be reached")

    monkeypatch.setattr(server, "_load_crosswalk", forbidden)
    parameter = inspect.signature(
        server.map_candidate_cover_types
    ).parameters["crosswalk_filename"]
    assert parameter.default is None
    with pytest.raises(ToolError, match="Explicit crosswalk selection"):
        server.map_candidate_cover_types(MANIFEST)


@pytest.mark.parametrize(
    "model,kwargs",
    [
        (bm.MappingRequest, {"acquisition_directory": "bacq_synthetic"}),
        (
            bm.CreateMappingRequest,
            {
                "acquisition_directory": "bacq_synthetic",
                "preview_directory": "mapdry_synthetic",
            },
        ),
    ],
)
def test_boundary_crosswalk_is_required(model, kwargs):
    assert "crosswalk_filename" in model.model_json_schema()["required"]
    with pytest.raises(ValidationError) as error:
        model(**kwargs)
    assert any(
        item["loc"] == ("crosswalk_filename",) and item["type"] == "missing"
        for item in error.value.errors()
    )


@pytest.mark.parametrize(
    "model,kwargs",
    [
        (bm.MappingRequest, {"acquisition_directory": "bacq_synthetic"}),
        (
            bm.CreateMappingRequest,
            {
                "acquisition_directory": "bacq_synthetic",
                "preview_directory": "mapdry_synthetic",
            },
        ),
    ],
)
def test_explicit_filename_is_preserved_not_substituted(model, kwargs):
    request = model(crosswalk_filename="synthetic_crosswalk.json", **kwargs)
    assert request.crosswalk_filename == "synthetic_crosswalk.json"
