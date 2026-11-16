"""Actual producer-to-exporter integration, using synthetic local inputs only."""
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
import review_package as rp


@pytest.mark.parametrize("outside", [False, True])
@pytest.mark.parametrize("interior_nodata", [False, True])
def test_actual_boundary_producer_to_polygon_export(
    tmp_path, outside, interior_nodata
):
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    import geopandas as gpd
    from rasterio.transform import Affine
    from shapely.geometry import box
    import boundary_mapping as bm
    import cover_type_patches as patches

    root = tmp_path / "outputs"
    root.mkdir()
    pdr = tmp_path / "project_data"
    crosswalks = pdr / "crosswalks"
    crosswalks.mkdir(parents=True)
    acquisition = root / "bacq_synthetic"
    extract = acquisition / "extract"
    extract.mkdir(parents=True)

    job = "12345678-1111-2222-3333-444444444444"
    transform = Affine(30, 0, 1000, 0, -30, 2000)
    evt = np.array([
        [1, 1, 7],
        [1, 7, 999],
        [7, 3, 999],
    ], dtype="int16")
    if interior_nodata:
        evt[1, 1] = -9999

    tif = extract / "synthetic.tif"
    with rasterio.open(
        tif, "w", driver="GTiff", width=3, height=3,
        count=3, dtype="int16", crs=5070,
        transform=transform, nodata=-9999
    ) as ds:
        ds.write(evt, 1)
        ds.write(np.zeros((3, 3), dtype="int16"), 2)
        ds.write(np.zeros((3, 3), dtype="int16"), 3)
        for index, name in enumerate(bm.EXPECTED_BANDS, 1):
            ds.set_band_description(index, name)

    boundary = root / "synthetic.geojson"
    left = 1030 if outside else 1000
    frame = gpd.GeoDataFrame(
        {"fixture": ["synthetic"]},
        geometry=[box(left, 1910, 1090, 2000)],
        crs=5070
    )
    frame.to_file(boundary, driver="GeoJSON", engine="pyogrio", index=False)

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    collection = {
        "document_type": "mapcp_boundary_collection_v1",
        "usable_for_mapping": True,
        "classification_performed": False,
        "job_id": job,
        "boundary_filename": boundary.name,
        "boundary_sha256": digest(boundary),
        "extract": {
            "geotiff_member": tif.name,
            "geotiff_sha256": digest(tif),
        },
    }
    (acquisition / "collection.json").write_text(json.dumps(collection))

    table = [
        {"output_code": 1, "output_label": "candidate_P",
         "candidate_forest_land": True, "description": "Synthetic forest"},
        {"output_code": 3, "output_label": "candidate_NF",
         "candidate_forest_land": False, "description": "Synthetic nonforest"},
        {"output_code": 7, "output_label": "candidate_RIP_UNCERTAIN",
         "candidate_forest_land": None, "description": "Synthetic uncertain"},
        {"output_code": 255, "output_label": "unmapped_evt",
         "candidate_forest_land": None, "description": "Synthetic unknown"},
        {"output_code": -9999, "output_label": "nodata",
         "candidate_forest_land": None, "description": "Synthetic NoData"},
    ]
    entries = [
        {"evt_code": row["output_code"],
         "output_code": row["output_code"],
         "output_label": row["output_label"],
         "candidate_forest_land": row["candidate_forest_land"]}
        for row in table if row["output_code"] in (1, 3, 7)
    ]
    crosswalk = {
        "crosswalk_id": "synthetic_integration",
        "crosswalk_version": "v1",
        "cover_scheme_id": "synthetic_scheme",
        "cover_scheme_version": "v1",
        "approved_by": "user",
        "crosswalk_approval_note":
            "Synthetic test marker only; not approval of forestry definitions.",
        "entries": entries,
        "output_code_table": table,
        "nodata_value": -9999,
        "unmapped_valid_output_code": 255,
        "universal_review_flags": ["synthetic_test_only"],
    }
    cw_name = "synthetic.json"
    (crosswalks / cw_name).write_text(json.dumps(crosswalk))

    preview = bm.preview_boundary_mapping(
        root,
        bm.MappingRequest(
            acquisition_directory=acquisition.name,
            crosswalk_filename=cw_name
        ),
        project_data_root=pdr
    )
    assert preview.status == "preview_complete_review_required", preview.errors

    mapped = bm.create_boundary_mapping(
        root,
        bm.CreateMappingRequest(
            acquisition_directory=acquisition.name,
            preview_directory=preview.artifacts["preview_directory"],
            crosswalk_filename=cw_name
        ),
        project_data_root=pdr
    )
    assert mapped.status == "mapping_complete_review_required", mapped.errors
    methods_name = mapped.artifacts["methods_json"]
    methods = json.loads((root / methods_name).read_text())

    expected_ct = evt.copy()
    expected_ct[expected_ct == 999] = 255
    if outside:
        expected_ct[:, 0] = -9999
    expected_fl = np.where(
        expected_ct == -9999, -9999,
        np.where(expected_ct == 1, 1,
                 np.where(expected_ct == 3, 0, 2))
    ).astype("int16")

    with rasterio.open(root / mapped.artifacts["cover_type_tif"]) as ds:
        assert np.array_equal(ds.read(1), expected_ct)
    with rasterio.open(root / mapped.artifacts["forest_land_tif"]) as ds:
        assert np.array_equal(ds.read(1), expected_fl)

    expected_outside = 3 if outside else 0
    expected_inside_nodata = 1 if interior_nodata else 0
    expected_nodata = expected_outside + expected_inside_nodata
    assert methods["outside_boundary_cells"] == expected_outside
    assert methods["evt_nodata_inside_boundary_cells"] == expected_inside_nodata
    assert methods["nodata_cell_count"] == expected_nodata
    assert methods["valid_cell_count"] == 9 - expected_nodata
    assert "codebook_csv" in methods["artifacts"]
    assert "cover_type_codebook_csv" not in methods["artifacts"]
    assert set(methods["acreage_closure"]) == {
        "cover_type_valid_sum_matches",
        "forest_land_valid_sum_matches",
        "total_pixel_sum_matches",
    }
    forest_counts = {
        row["forest_land_code"]: row["cell_count"]
        for row in methods["forest_land_stats"]
    }
    assert forest_counts == {
        code: int((expected_fl == code).sum()) for code in (0, 1, 2)
    }

    raw = patches.create_raw_cover_type_patches(
        root, patches.RawPatchRequest(methods_filename=methods_name)
    )
    assert raw.status == "complete_review_required", raw.errors
    run = Path(raw.artifacts["geopackage"]).parent.name

    before = {
        str(p.relative_to(root)): digest(p)
        for p in root.rglob("*") if p.is_file()
    }
    package = rp.build_review_package(
        root, methods_name, raw_run_directory=run
    )
    assert package["storage_uploaded"] is False
    assert package["schema_version"] == "2"

    with zipfile.ZipFile(package["archive_path"]) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
        assert len(archive.namelist()) == 12
        for item in manifest["files"]:
            assert hashlib.sha256(
                archive.read(item["name"])
            ).hexdigest() == item["sha256"]
        for name in mapped.artifacts.values():
            assert archive.read(name) == (root / name).read_bytes()
        qc = json.loads(archive.read("QC_AND_LIMITATIONS.json"))
        assert qc["cover_type_split_nodata"]["components"] == {
            "outside_boundary_masked": expected_outside,
            "evt_nodata_inside_boundary": expected_inside_nodata,
        }
        forest_qc = qc["forest_land_summary_validation"]
        assert forest_qc["csv_summary_mode"] == "valid_only"
        assert forest_qc["methods_summary_mode"] == "valid_only"
        assert forest_qc["nodata_cells"] == expected_nodata
        assert manifest["raw_polygon_validation"]["source_hashes_match"]
        assert manifest["raw_polygon_validation"]["nodata_cells"] == expected_nodata

    assert all(
        digest(root / name) == value for name, value in before.items()
    )
