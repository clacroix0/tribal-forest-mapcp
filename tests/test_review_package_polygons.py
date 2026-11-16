"""Focused export tests. Storage/metadata simulations are explicitly labeled.
Real raster/polygon integration tests skip if Rasterio is unavailable.
"""
import ast
import csv
import hashlib
import io
import json
import uuid
import zipfile
from collections import Counter
from pathlib import Path

import pytest
import review_package as rp
import review_package_polygons as pp
import review_package_storage as storage

NAME = "cmap_12345678_v1_methods.json"
JOB = "12345678-1111-2222-3333-444444444444"
RUN = "rawpatch_12345678_v1_20261116T150000_abcdef"
DATA = [[1, 1, 7], [1, -9999, 255], [7, 255, 255]]
CT = Counter(v for row in DATA for v in row)
FLAGS = {1: True, 7: None, 255: None, -9999: None}
LABELS = {1: "candidate_P", 7: "candidate_RIP_UNCERTAIN", 255: "unmapped_evt", -9999: "nodata"}
FL = Counter({1: 3, 2: 5, -9999: 1})
TRANSFORM = [30., 0., 1000., 0., -30., 2000.]


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def raster_fixture(root, real=False):
    root.mkdir(parents=True, exist_ok=True)
    prefix = NAME.removesuffix("_methods.json")
    names = {k: prefix + "_" + suffix for k, suffix in rp.SUFFIXES.items()}
    stats = [{"output_code": code, "output_label": LABELS[code],
              "candidate_forest_land": FLAGS[code], "cell_count": n,
              "square_meters": n*900, "acres": n*900/rp.ACRE_M2}
             for code, n in sorted(CT.items()) if code != -9999]
    fl_stats = [{"forest_land_code": c, "cell_count": n, "acres": n*900/rp.ACRE_M2}
                for c, n in sorted(FL.items())]
    methods = {"document_type": "candidate_cover_type_methods_and_provenance",
               "mapping_status": "complete", "rasters_written": True, "write_errors": [],
               "job_id": JOB, "crosswalk_id": "synthetic", "crosswalk_version": "v1",
               "cover_scheme_id": "synthetic_scheme", "cover_scheme_version": "v1",
               "crosswalk_approval_note": "Synthetic fixture, not forestry approval.",
               "sentinels": {"classification_performed": True, "crosswalk_applied": True,
                             "candidate_cover_types_produced": True, "candidate_forest_land_produced": True,
                             "field_inventory_performed": False,
                             "authoritative_forest_land_determination_performed": False,
                             "candidate_polygons_produced": False},
               "raster_shape": [3, 3], "total_pixels": 9, "valid_cell_count": 8,
               "nodata_cell_count": 1, "valid_acres": 8*900/rp.ACRE_M2,
               "raster_crs_epsg": 5070, "nodata_value": -9999, "raster_transform": TRANSFORM,
               "acreage_closure": {"cover_type_valid_sum_matches": True,
                                   "forest_land_valid_sum_matches": True,
                                   "total_pixel_sum_matches": True, "valid_cell_count": 8,
                                   "cover_type_class_sum": 8, "forest_land_class_sum": 8,
                                   "nodata_count": 1, "total_pixels": 9},
               "cover_type_stats": stats, "forest_land_stats": fl_stats,
               "artifacts": {k: str(root / n) for k, n in names.items()}, "warnings": [],
               "universal_review_flags": []}
    book = [{"output_code": c, "output_label": LABELS[c],
             "candidate_forest_land": "true" if FLAGS[c] else "null",
             "description": "Synthetic " + LABELS[c], "source_evt_codes": ""} for c in LABELS]
    write_csv(root / names["cover_type_codebook_csv"], book)
    ct_csv = [dict(r, candidate_forest_land="true" if r["candidate_forest_land"] else "null") for r in stats]
    ct_csv.append({"output_code": -9999, "output_label": "nodata", "candidate_forest_land": "null",
                   "cell_count": 1, "square_meters": 900, "acres": 900/rp.ACRE_M2})
    write_csv(root / names["cover_type_acreage_csv"], ct_csv)
    write_csv(root / names["forest_land_acreage_csv"], fl_stats)
    (root / NAME).write_text(json.dumps(methods))
    if real:
        rasterio = pytest.importorskip("rasterio", reason="Actual GIS integration requires Rasterio")
        import numpy as np
        from rasterio.transform import Affine
        a = np.array(DATA, dtype="int16")
        b = np.where(a == -9999, -9999, np.where(a == 1, 1, 2)).astype("int16")
        for key, data in (("cover_type_tif", a), ("forest_land_tif", b)):
            with rasterio.open(root/names[key], "w", driver="GTiff", width=3, height=3,
                               count=1, dtype="int16", crs=5070, transform=Affine(*TRANSFORM), nodata=-9999) as ds:
                ds.write(data, 1)
                ds.update_tags(**{k: methods[k] for k in ("job_id", "crosswalk_id", "crosswalk_version", "cover_scheme_id")})
    else:
        for key in ("cover_type_tif", "forest_land_tif"):
            (root/names[key]).write_bytes(b"SIMULATED raster; not a GeoTIFF")
    return names, methods


def simulated_raster_validator(*args):
    return dict(CT), dict(FL)


def assert_archive(package):
    with zipfile.ZipFile(package["archive_path"]) as z:
        assert z.testzip() is None
        manifest = json.loads(z.read("PACKAGE_MANIFEST.json"))
        assert set(z.namelist()) == set(package["files"])
        for item in manifest["files"]:
            assert hashlib.sha256(z.read(item["name"])).hexdigest() == item["sha256"]
    return manifest


def test_simulated_legacy_raster_package(tmp_path):
    raster_fixture(tmp_path)
    package = rp.build_review_package(tmp_path, NAME, raster_validator=simulated_raster_validator)
    assert len(package["files"]) == 9
    assert assert_archive(package)["schema_version"] == "1"


def test_simulated_polygon_packaging_contract(tmp_path, monkeypatch):
    raster_fixture(tmp_path)
    folder = tmp_path/RUN
    folder.mkdir()
    for name in pp.POLYGON_NAMES:
        (folder/name).write_bytes(b"SIMULATED polygon artifact")
    monkeypatch.setattr(pp, "validate_raw_patches", lambda *args: {"patch_count": 3})
    package = rp.build_review_package(tmp_path, NAME, raw_run_directory=RUN,
                                      raster_validator=simulated_raster_validator)
    manifest = assert_archive(package)
    assert len(package["files"]) == 12 and manifest["schema_version"] == "2"
    assert set(pp.POLYGON_NAMES) <= set(package["files"])
    with zipfile.ZipFile(package["archive_path"]) as z:
        guide = z.read("OPEN_IN_ARCGIS_PRO.md").decode()
        assert "This is a raster-only review package" not in guide
        assert "raw_cover_type_patches.gpkg" in guide


@pytest.mark.parametrize("bad", ["../"+RUN, "/tmp/"+RUN, "", "anything", RUN+"/x"])
def test_unsafe_raw_reference_rejected(tmp_path, bad):
    with pytest.raises(rp.ExportError, match="folder name"):
        pp.snapshot_raw_patches(tmp_path, tmp_path, bad, 0)


def test_missing_polygon_artifact_rejected(tmp_path):
    (tmp_path/RUN).mkdir()
    with pytest.raises(rp.ExportError) as exc:
        pp.snapshot_raw_patches(tmp_path, tmp_path, RUN, 0)
    assert exc.value.code == "missing_polygon_artifact"


def test_failed_polygon_run_rejected(tmp_path):
    (tmp_path/RUN).mkdir()
    (tmp_path/RUN/"FAILED_DO_NOT_USE.json").write_text("{}")
    with pytest.raises(rp.ExportError) as exc:
        pp.snapshot_raw_patches(tmp_path, tmp_path, RUN, 0)
    assert exc.value.code == "incomplete_polygons"


def test_symlink_run_rejected(tmp_path):
    target = tmp_path/"real"
    target.mkdir()
    (tmp_path/RUN).symlink_to(target, target_is_directory=True)
    with pytest.raises(rp.ExportError):
        pp.snapshot_raw_patches(tmp_path, tmp_path, RUN, 0)


def test_combined_size_limit_enforced(tmp_path):
    folder = tmp_path/RUN
    folder.mkdir()
    for n in pp.POLYGON_NAMES:
        (folder/n).write_text("synthetic")
    with pytest.raises(rp.ExportError) as exc:
        pp.snapshot_raw_patches(tmp_path, tmp_path, RUN, pp.MAX_SOURCE_BYTES)
    assert exc.value.code == "size_limit"


def report_fixture(root):
    names, methods = raster_fixture(root)
    report = {"document_type": "candidate_cover_type_raw_patch_qc", "status": "complete_review_required",
              "candidate_polygons_produced": True, "candidate_stands_produced": False,
              "new_classification_performed": False, "smoothing": False,
              "small_patch_removal": False, "minimum_mapping_unit_applied": False, "connectivity": 4,
              **{k: methods[k] for k in ("job_id", "crosswalk_id", "crosswalk_version", "cover_scheme_id", "cover_scheme_version")},
              "source_methods_filename": NAME, "source_raster_filename": names["cover_type_tif"],
              "raster_shape": methods["raster_shape"], "raster_transform": TRANSFORM,
              "source_sha256": {"cover_type_tif": rp.sha256_file(root/names["cover_type_tif"]),
                                "codebook_csv": rp.sha256_file(root/names["cover_type_codebook_csv"]),
                                "slice3_methods": rp.sha256_file(root/NAME)}}
    return names, methods, report


@pytest.mark.parametrize("change,code", [("job_id", "polygon_identity_mismatch"),
                                         ("source_sha256", "polygon_source_changed"),
                                         ("status", "incomplete_polygons")])
def test_wrong_run_or_changed_source_rejected_before_gis(tmp_path, change, code):
    names, methods, report = report_fixture(tmp_path)
    report[change] = {} if change == "source_sha256" else "wrong"
    (tmp_path/"raw_patch_qc.json").write_text(json.dumps(report))
    with pytest.raises(rp.ExportError) as exc:
        pp.validate_raw_patches(tmp_path, names, methods, RUN)
    assert exc.value.code == code


class SimulatedCOS:
    def __init__(self):
        self.objects = {}
        self.puts = 0
    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            exc = RuntimeError("SIMULATED missing")
            exc.response = {"Error": {"Code": "NoSuchKey"}}
            raise exc
        raw, meta = self.objects[Key]
        return {"ContentLength": len(raw), "Metadata": meta}
    def put_object(self, Bucket, Key, Body, ContentType, Metadata):
        self.puts += 1
        self.objects[Key] = (Body.read(), Metadata)
    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key][0])}
    def generate_presigned_url(self, method, Params, ExpiresIn):
        return CONFIG.endpoint + "/" + Params["Bucket"] + "/" + Params["Key"] + "?SIMULATED=not-a-real-link"


CONFIG = storage.StorageConfig("synthetic-bucket", "https://s3.ca-tor.cloud-object-storage.appdomain.cloud",
                               "ca-tor", "mapcp-review/", "SIMULATED", "SIMULATED")


@pytest.mark.parametrize("polygons", [False, True])
def test_simulated_storage_and_renewal(tmp_path, monkeypatch, polygons):
    raster_fixture(tmp_path)
    if polygons:
        (tmp_path/RUN).mkdir()
        for n in pp.POLYGON_NAMES:
            (tmp_path/RUN/n).write_text("SIMULATED")
        monkeypatch.setattr(pp, "validate_raw_patches", lambda *args: {"patch_count": 1})
    package = rp.build_review_package(tmp_path, NAME, raster_validator=simulated_raster_validator,
                                      raw_run_directory=RUN if polygons else None)
    client = SimulatedCOS()
    result = storage.store_package(client, CONFIG, package)
    assert result["package_scope"] == package["package_scope"]
    puts = client.puts
    renewed = storage.renew_package(client, CONFIG, package["package_id"])
    assert renewed["link_renewed"] and not renewed["storage_uploaded"]
    assert client.puts == puts
    assert renewed["package_scope"] == package["package_scope"]
    key = storage._key(CONFIG, package["package_id"], "mapcp_raster_review.zip")
    raw, meta = client.objects[key]
    client.objects[key] = (b"X" + raw[1:], meta)
    with pytest.raises(rp.ExportError):
        storage.renew_package(client, CONFIG, package["package_id"])


def test_unknown_descriptor_scope_rejected():
    with pytest.raises(rp.ExportError):
        storage._descriptor_contract({"schema_version": "9", "package_scope": "anything", "files": []})


def test_polygon_descriptor_missing_member_rejected():
    with pytest.raises(rp.ExportError):
        storage._descriptor_contract({"schema_version": "2", "package_scope": pp.POLYGON_SCOPE,
                                      "files": ["file"+str(i) for i in range(12)]})


@pytest.mark.parametrize("payload", [
    {"action": "create", "methods_filename": NAME, "raw_run_directory": "../bad"},
    {"action": "renew", "package_id": str(uuid.uuid4()), "raw_run_directory": RUN}])
def test_invalid_request_does_not_configure_storage(tmp_path, payload):
    result = storage.deliver_review_package(tmp_path, payload, env={"MAPCP_REVIEW_EXPORT_ENABLED": "true"})
    assert result["status"] == "failed" and result["stage"] == "validate_request"


def test_server_export_schema_accepts_raw_name_only():
    from pydantic import BaseModel, ConfigDict, Field, ValidationError
    from typing import Literal
    root = Path(__file__).resolve().parent
    server = root/"server.py"
    if not server.is_file():
        server = root.parent/"server.py"
    tree = ast.parse(server.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ReviewPackageExportRequest")
    ns = dict(BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field, Literal=Literal)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(server), "exec"), ns)
    request_type = ns["ReviewPackageExportRequest"]
    assert request_type(action="create", methods_filename=NAME, raw_run_directory=RUN).raw_run_directory == RUN
    with pytest.raises(ValidationError):
        request_type(action="create", methods_filename=NAME, raw_run_directory="../"+RUN)


@pytest.fixture
def actual_run(tmp_path):
    pytest.importorskip("rasterio", reason="Actual GIS integration requires Rasterio")
    import cover_type_patches as patches
    raster_fixture(tmp_path, real=True)
    result = patches.create_raw_cover_type_patches(tmp_path, patches.RawPatchRequest(methods_filename=NAME))
    assert result.status == "complete_review_required", result.errors
    return tmp_path, Path(result.artifacts["geopackage"]).parent.name


def test_actual_polygon_export_and_checksums(actual_run):
    root, run = actual_run
    before = {str(p.relative_to(root)): rp.sha256_file(p) for p in root.rglob("*") if p.is_file()}
    package = rp.build_review_package(root, NAME, raw_run_directory=run)
    manifest = assert_archive(package)
    assert manifest["raw_polygon_validation"]["nodata_cells"] == 1
    assert manifest["raw_polygon_validation"]["source_hashes_match"]
    assert all(rp.sha256_file(root/p) == checksum for p, checksum in before.items())


@pytest.mark.parametrize("damage", ["geometry", "attribute", "acreage", "corrupt", "missing"])
def test_actual_polygon_damage_rejected(actual_run, damage):
    import geopandas as gpd
    import cover_type_patches as patches
    root, run = actual_run
    folder = root/run
    if damage in ("geometry", "attribute"):
        path = folder/"raw_cover_type_patches.gpkg"
        frame = gpd.read_file(path, layer=patches.LAYER, engine="pyogrio")
        if damage == "geometry":
            frame.loc[0, "geometry"] = frame.geometry.iloc[0].buffer(-1)
        else:
            frame.loc[0, "forest_land_status"] = "nonforest"
        path.unlink()
        frame.to_file(path, layer=patches.LAYER, driver="GPKG", engine="pyogrio", index=False)
    elif damage == "acreage":
        path = folder/"raw_patch_acreage.csv"
        rows = list(csv.DictReader(path.open()))
        rows[0]["acres"] = "9999"
        write_csv(path, rows)
    elif damage == "corrupt":
        (folder/"raw_cover_type_patches.gpkg").write_bytes(b"not a GeoPackage")
    else:
        (folder/"raw_cover_type_patches.gpkg").unlink()
    with pytest.raises(rp.ExportError):
        rp.build_review_package(root, NAME, raw_run_directory=run)



def test_simulated_create_forwards_raw_reference(tmp_path, monkeypatch):
    raster_fixture(tmp_path)
    (tmp_path/RUN).mkdir()
    for n in pp.POLYGON_NAMES:
        (tmp_path/RUN/n).write_text("SIMULATED")
    monkeypatch.setattr(pp, "validate_raw_patches", lambda *args: {"patch_count": 1})
    monkeypatch.setattr(storage.StorageConfig, "from_environment", classmethod(lambda cls, env: CONFIG))
    client = SimulatedCOS()
    def build(root, methods, *, raw_run_directory):
        assert raw_run_directory == RUN
        return rp.build_review_package(root, methods, raw_run_directory=raw_run_directory,
                                       raster_validator=simulated_raster_validator)
    result = storage.deliver_review_package(tmp_path,
        {"action": "create", "methods_filename": NAME, "raw_run_directory": RUN, "package_id": None},
        env={"MAPCP_REVIEW_EXPORT_ENABLED": "true"}, client_factory=lambda config: client, builder=build)
    assert result["status"] == "download_ready" and result["package_scope"] == pp.POLYGON_SCOPE


def test_failed_polygon_build_has_no_raster_fallback(tmp_path):
    raster_fixture(tmp_path)
    with pytest.raises(rp.ExportError):
        rp.build_review_package(tmp_path, NAME, raw_run_directory=RUN,
                                raster_validator=simulated_raster_validator)
    assert list((tmp_path/"review_packages").iterdir()) == []


@pytest.mark.parametrize("mode", ["alias_only", "canonical_only", "both_equal"])
def test_boundary_codebook_reference_resolution(tmp_path, mode):
    names, methods = raster_fixture(tmp_path)
    methods["sentinels"]["boundary_clipping_performed"] = True
    methods["outside_boundary_cells"] = 1
    methods["evt_nodata_inside_boundary_cells"] = 0
    refs = methods["artifacts"]
    canonical = refs["cover_type_codebook_csv"]
    if mode in ("alias_only", "both_equal"):
        refs["codebook_csv"] = canonical
    if mode == "alias_only":
        del refs["cover_type_codebook_csv"]
    before = dict(refs)
    assert rp._artifact_reference(
        refs, "cover_type_codebook_csv", methods
    ) == canonical
    assert refs == before


def test_simulated_boundary_codebook_alias_export(tmp_path):
    names, methods = raster_fixture(tmp_path)
    methods["sentinels"]["boundary_clipping_performed"] = True
    methods["outside_boundary_cells"] = 1
    methods["evt_nodata_inside_boundary_cells"] = 0
    refs = methods["artifacts"]
    refs["codebook_csv"] = refs.pop("cover_type_codebook_csv")
    (tmp_path / NAME).write_text(json.dumps(methods))
    before = {n: rp.sha256_file(tmp_path / n) for n in names.values()}
    package = rp.build_review_package(
        tmp_path, NAME, raster_validator=simulated_raster_validator
    )
    assert_archive(package)
    with zipfile.ZipFile(package["archive_path"]) as archive:
        for name in names.values():
            assert archive.read(name) == (tmp_path / name).read_bytes()
    assert all(rp.sha256_file(tmp_path / n) == h for n, h in before.items())


@pytest.mark.parametrize("damage", ["conflict", "wrong_filename", "missing"])
def test_simulated_boundary_bad_codebook_reference_rejected(tmp_path, damage):
    names, methods = raster_fixture(tmp_path)
    methods["sentinels"]["boundary_clipping_performed"] = True
    methods["outside_boundary_cells"] = 1
    methods["evt_nodata_inside_boundary_cells"] = 0
    refs = methods["artifacts"]
    if damage == "conflict":
        refs["codebook_csv"] = "wrong.csv"
    elif damage == "wrong_filename":
        del refs["cover_type_codebook_csv"]
        refs["codebook_csv"] = "wrong.csv"
    else:
        del refs["cover_type_codebook_csv"]
    (tmp_path / NAME).write_text(json.dumps(methods))
    with pytest.raises(rp.ExportError) as exc:
        rp.build_review_package(
            tmp_path, NAME, raster_validator=simulated_raster_validator
        )
    assert exc.value.code == "identity_mismatch"
    assert list((tmp_path / "review_packages").iterdir()) == []


@pytest.mark.parametrize("sentinel", [None, False, 1, "true"])
def test_simulated_legacy_codebook_alias_not_enabled(tmp_path, sentinel):
    names, methods = raster_fixture(tmp_path)
    if sentinel is not None:
        methods["sentinels"]["boundary_clipping_performed"] = sentinel
    refs = methods["artifacts"]
    refs["codebook_csv"] = refs.pop("cover_type_codebook_csv")
    (tmp_path / NAME).write_text(json.dumps(methods))
    with pytest.raises(rp.ExportError) as exc:
        rp.build_review_package(
            tmp_path, NAME, raster_validator=simulated_raster_validator
        )
    assert exc.value.code == "identity_mismatch"
    assert list((tmp_path / "review_packages").iterdir()) == []


def boundary_metadata_fixture(root, outside=1, inside=0):
    names, methods = raster_fixture(root)
    methods["sentinels"]["boundary_clipping_performed"] = True
    methods["outside_boundary_cells"] = outside
    methods["evt_nodata_inside_boundary_cells"] = inside
    methods["nodata_cell_count"] = outside + inside
    methods["valid_cell_count"] = 9 - outside - inside
    methods["valid_acres"] = methods["valid_cell_count"] * 900 / rp.ACRE_M2
    methods["acreage_closure"] = {
        "cover_type_valid_sum_matches": True,
        "forest_land_valid_sum_matches": True,
        "total_pixel_sum_matches": True,
    }
    return names, methods


@pytest.mark.parametrize("outside,inside", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_boundary_nodata_metadata_cases(tmp_path, outside, inside):
    # Methods-only test: these modified counts are not a raster fixture.
    names, methods = boundary_metadata_fixture(tmp_path, outside, inside)
    original = json.dumps(methods, sort_keys=True)
    rp._validate_methods(methods, NAME.removesuffix("_methods.json"))
    assert rp._boundary_nodata_counts(methods) == {
        "outside_boundary_cells": outside,
        "evt_nodata_inside_boundary_cells": inside,
        "nodata_cell_count": outside + inside,
    }
    assert json.dumps(methods, sort_keys=True) == original


@pytest.mark.parametrize("key", [
    "outside_boundary_cells", "evt_nodata_inside_boundary_cells"
])
@pytest.mark.parametrize("value", [True, 1.5, "1", -1, None])
def test_boundary_nodata_invalid_count_rejected(tmp_path, key, value):
    names, methods = boundary_metadata_fixture(tmp_path)
    methods[key] = value
    with pytest.raises(rp.ExportError) as exc:
        rp._validate_methods(methods, NAME.removesuffix("_methods.json"))
    assert exc.value.code == "invalid_metadata"


@pytest.mark.parametrize("key", [
    "outside_boundary_cells", "evt_nodata_inside_boundary_cells"
])
def test_boundary_nodata_missing_count_rejected(tmp_path, key):
    names, methods = boundary_metadata_fixture(tmp_path)
    del methods[key]
    with pytest.raises(rp.ExportError) as exc:
        rp._validate_methods(methods, NAME.removesuffix("_methods.json"))
    assert exc.value.code == "invalid_metadata"


def test_boundary_nodata_component_total_rejected(tmp_path):
    names, methods = boundary_metadata_fixture(tmp_path)
    methods["outside_boundary_cells"] = 2
    with pytest.raises(rp.ExportError) as exc:
        rp._validate_methods(methods, NAME.removesuffix("_methods.json"))
    assert exc.value.code == "closure_failed"


@pytest.mark.parametrize("key", [
    "valid_cell_count", "cover_type_class_sum", "forest_land_class_sum",
    "nodata_count", "total_pixels"
])
def test_boundary_present_wrong_closure_total_rejected(tmp_path, key):
    names, methods = boundary_metadata_fixture(tmp_path)
    methods["acreage_closure"][key] = 999
    with pytest.raises(rp.ExportError) as exc:
        rp._validate_methods(methods, NAME.removesuffix("_methods.json"))
    assert exc.value.code == "closure_failed"


def test_legacy_numeric_closure_still_required(tmp_path):
    names, methods = raster_fixture(tmp_path)
    del methods["acreage_closure"]["valid_cell_count"]
    with pytest.raises(rp.ExportError) as exc:
        rp._validate_methods(methods, NAME.removesuffix("_methods.json"))
    assert exc.value.code == "closure_failed"


def test_actual_rasters_boundary_boolean_closure(tmp_path):
    # Isolates methods compatibility; CSVs retain the legacy representation.
    names, methods = raster_fixture(tmp_path, real=True)
    methods["sentinels"]["boundary_clipping_performed"] = True
    methods["outside_boundary_cells"] = 1
    methods["evt_nodata_inside_boundary_cells"] = 0
    methods["acreage_closure"] = {
        key: True for key in (
            "cover_type_valid_sum_matches",
            "forest_land_valid_sum_matches",
            "total_pixel_sum_matches",
        )
    }
    (tmp_path / NAME).write_text(json.dumps(methods))
    before = {n: rp.sha256_file(tmp_path / n) for n in names.values()}
    package = rp.build_review_package(tmp_path, NAME)
    assert_archive(package)
    assert package["storage_uploaded"] is False
    with zipfile.ZipFile(package["archive_path"]) as archive:
        for name in names.values():
            assert archive.read(name) == (tmp_path / name).read_bytes()
    assert all(rp.sha256_file(tmp_path / n) == h for n, h in before.items())


def split_cover_fixture(root, *, real=False, inside=0):
    names, methods = raster_fixture(root, real=real)
    methods["sentinels"]["boundary_clipping_performed"] = True
    methods["outside_boundary_cells"] = 1 - inside
    methods["evt_nodata_inside_boundary_cells"] = inside
    path = root / names["cover_type_acreage_csv"]
    rows = [r for r in rp._rows(path) if r["output_code"] != "-9999"]
    for label, n in (
        ("outside_boundary_masked", 1 - inside),
        ("evt_nodata_inside_boundary", inside),
    ):
        rows.append({
            "output_code": "-9999", "output_label": label,
            "candidate_forest_land": "null", "cell_count": str(n),
            "square_meters": str(n * 900),
            "acres": str(round(n * 900 / rp.ACRE_M2, 4)),
        })
    write_csv(path, rows)
    (root / NAME).write_text(json.dumps(methods))
    return names, methods


@pytest.mark.parametrize("outside,inside", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_split_cover_component_normalization(tmp_path, outside, inside):
    # Helper-level cases; not proof of corresponding raster geography.
    names, methods = boundary_metadata_fixture(tmp_path, outside, inside)
    rows = [{
        "output_code": "-9999", "output_label": label,
        "candidate_forest_land": "null", "cell_count": str(n),
        "square_meters": str(n * 900),
        "acres": str(round(n * 900 / rp.ACRE_M2, 4)),
    } for label, n in (
        ("outside_boundary_masked", outside),
        ("evt_nodata_inside_boundary", inside),
    )]
    original = json.dumps(rows)
    normalized, qc = rp._cover_nodata_rows(rows, methods)
    assert len(normalized) == 1
    assert int(normalized[0]["cell_count"]) == outside + inside
    assert qc["total_nodata_cells"] == outside + inside
    assert json.dumps(rows) == original


@pytest.mark.parametrize("damage", [
    "duplicate", "missing", "mixed", "label", "code", "flag",
    "count", "fractional_count", "negative_count", "acres", "area",
    "nonfinite_acres", "nonfinite_area", "no_boundary",
])
def test_simulated_split_cover_damage_rejected(tmp_path, damage):
    names, methods = split_cover_fixture(tmp_path)
    path = tmp_path / names["cover_type_acreage_csv"]
    rows = rp._rows(path)
    if damage == "duplicate":
        rows.append(dict(rows[-1]))
    elif damage == "missing":
        rows.pop()
    elif damage == "mixed":
        row = dict(rows[-1])
        row["output_label"] = "nodata"
        rows.append(row)
    elif damage == "label":
        rows[-1]["output_label"] = "unexpected_nodata"
    elif damage == "code":
        rows[-1]["output_code"] = "1"
    elif damage == "flag":
        rows[-1]["candidate_forest_land"] = "false"
    elif damage == "count":
        rows[-1]["cell_count"] = "1"
    elif damage == "fractional_count":
        rows[-1]["cell_count"] = "0.5"
    elif damage == "negative_count":
        rows[-1]["cell_count"] = "-1"
    elif damage == "acres":
        rows[-1]["acres"] = "1"
    elif damage == "area":
        rows[-1]["square_meters"] = "1"
    elif damage == "nonfinite_acres":
        rows[-1]["acres"] = "nan"
    elif damage == "nonfinite_area":
        rows[-1]["square_meters"] = "inf"
    elif damage == "no_boundary":
        methods["sentinels"]["boundary_clipping_performed"] = False
    write_csv(path, rows)
    (tmp_path / NAME).write_text(json.dumps(methods))
    with pytest.raises(rp.ExportError):
        rp.build_review_package(
            tmp_path, NAME, raster_validator=simulated_raster_validator
        )
    assert list((tmp_path / "review_packages").iterdir()) == []


@pytest.mark.parametrize("inside", [0, 1])
def test_actual_split_cover_export_preserves_sources(tmp_path, inside):
    names, methods = split_cover_fixture(tmp_path, real=True, inside=inside)
    before = {n: rp.sha256_file(tmp_path / n) for n in names.values()}
    package = rp.build_review_package(tmp_path, NAME)
    assert_archive(package)
    with zipfile.ZipFile(package["archive_path"]) as archive:
        for name in names.values():
            assert archive.read(name) == (tmp_path / name).read_bytes()
        qc = json.loads(archive.read("QC_AND_LIMITATIONS.json"))
        split = qc["cover_type_split_nodata"]
        assert split["total_nodata_cells"] == 1
        assert split["source_csv_modified"] is False
        assert split["components"]["evt_nodata_inside_boundary"] == inside
        assert split["geographic_component_locations_independently_verified"] is False
    assert all(rp.sha256_file(tmp_path / n) == h for n, h in before.items())


def valid_only_forest_fixture(root, *, real=False):
    names, methods = split_cover_fixture(root, real=real)
    meanings = {
        0: "candidate_forest_land_false",
        1: "candidate_forest_land_true",
        2: "candidate_forest_land_unknown",
    }
    forest = [{
        "forest_land_code": code,
        "meaning": meanings[code],
        "cell_count": FL.get(code, 0),
        "acres": round(FL.get(code, 0) * 900 / rp.ACRE_M2, 4),
    } for code in (1, 0, 2)]
    methods["forest_land_stats"] = forest
    write_csv(root / names["forest_land_acreage_csv"], forest)
    methods["acreage_closure"] = {
        key: True for key in (
            "cover_type_valid_sum_matches",
            "forest_land_valid_sum_matches",
            "total_pixel_sum_matches",
        )
    }
    refs = methods["artifacts"]
    refs["codebook_csv"] = refs.pop("cover_type_codebook_csv")
    (root / NAME).write_text(json.dumps(methods))
    return names, methods


@pytest.mark.parametrize("summary", ["csv", "methods"])
@pytest.mark.parametrize("damage", [
    "missing_populated", "missing_zero", "duplicate", "unknown_code",
    "wrong_count", "fractional_count", "wrong_acres", "nonfinite_acres",
])
def test_simulated_valid_only_forest_damage_rejected(tmp_path, summary, damage):
    names, methods = valid_only_forest_fixture(tmp_path)
    path = tmp_path / names["forest_land_acreage_csv"]
    rows = (
        rp._rows(path) if summary == "csv"
        else methods["forest_land_stats"]
    )
    if damage == "missing_populated":
        rows[:] = [r for r in rows if int(r["forest_land_code"]) != 2]
    elif damage == "missing_zero":
        rows[:] = [r for r in rows if int(r["forest_land_code"]) != 0]
    elif damage == "duplicate":
        rows.append(dict(rows[0]))
    elif damage == "unknown_code":
        rows[0]["forest_land_code"] = "3" if summary == "csv" else 3
    elif damage == "wrong_count":
        rows[0]["cell_count"] = "99" if summary == "csv" else 99
    elif damage == "fractional_count":
        rows[0]["cell_count"] = "3.5" if summary == "csv" else 3.5
    elif damage == "wrong_acres":
        rows[0]["acres"] = "99" if summary == "csv" else 99
    elif damage == "nonfinite_acres":
        rows[0]["acres"] = "nan"
    if summary == "csv":
        write_csv(path, rows)
    (tmp_path / NAME).write_text(json.dumps(methods))
    with pytest.raises(rp.ExportError):
        rp.build_review_package(
            tmp_path, NAME, raster_validator=simulated_raster_validator
        )
    assert list((tmp_path / "review_packages").iterdir()) == []


def test_simulated_legacy_valid_only_forest_still_rejected(tmp_path):
    names, methods = raster_fixture(tmp_path)
    methods["forest_land_stats"] = [
        r for r in methods["forest_land_stats"]
        if r["forest_land_code"] != -9999
    ]
    (tmp_path / NAME).write_text(json.dumps(methods))
    with pytest.raises(rp.ExportError):
        rp.build_review_package(
            tmp_path, NAME, raster_validator=simulated_raster_validator
        )


@pytest.mark.parametrize("polygons", [False, True])
def test_actual_combined_boundary_format_export(tmp_path, polygons):
    names, methods = valid_only_forest_fixture(tmp_path, real=True)
    raw_run = None
    if polygons:
        import cover_type_patches as patches
        result = patches.create_raw_cover_type_patches(
            tmp_path, patches.RawPatchRequest(methods_filename=NAME)
        )
        assert result.status == "complete_review_required", result.errors
        raw_run = Path(result.artifacts["geopackage"]).parent.name
    before = {
        str(p.relative_to(tmp_path)): rp.sha256_file(p)
        for p in tmp_path.rglob("*") if p.is_file()
    }
    package = rp.build_review_package(
        tmp_path, NAME, raw_run_directory=raw_run
    )
    manifest = assert_archive(package)
    assert package["storage_uploaded"] is False
    with zipfile.ZipFile(package["archive_path"]) as archive:
        for name in names.values():
            assert archive.read(name) == (tmp_path / name).read_bytes()
        qc = json.loads(archive.read("QC_AND_LIMITATIONS.json"))
        forest = qc["forest_land_summary_validation"]
        assert forest["csv_summary_mode"] == "valid_only"
        assert forest["methods_summary_mode"] == "valid_only"
        assert forest["nodata_cells"] == 1
        assert forest["nodata_count_matches_methods_and_both_rasters"]
        assert forest["source_summaries_modified"] is False
        assert qc["cover_type_split_nodata"]["total_nodata_cells"] == 1
        saved = json.loads(archive.read(NAME))
        assert {
            r["forest_land_code"]: r["cell_count"]
            for r in saved["forest_land_stats"]
        } == {0: 0, 1: 3, 2: 5}
    if polygons:
        assert manifest["raw_polygon_validation"]["source_hashes_match"]
        assert manifest["schema_version"] == "2"
    else:
        assert manifest["schema_version"] == "1"
    assert all(
        rp.sha256_file(tmp_path / name) == digest
        for name, digest in before.items()
    )


def test_export_budget_production_constants():
    assert rp.MAX_SOURCE_BYTES == 192 * 1024 * 1024
    assert pp.MAX_SOURCE_BYTES == rp.MAX_SOURCE_BYTES
    assert rp.MAX_BYTES == 100 * 1024 * 1024


@pytest.mark.parametrize("over_by", [0, 1])
def test_simulated_raster_source_budget_boundary(tmp_path, monkeypatch, over_by):
    names, methods = raster_fixture(tmp_path)
    total = sum((tmp_path / n).stat().st_size for n in names.values())
    monkeypatch.setattr(rp, "MAX_SOURCE_BYTES", total - over_by)
    called = []

    def validator(*args):
        called.append(True)
        return simulated_raster_validator(*args)

    if over_by:
        with pytest.raises(rp.ExportError) as exc:
            rp.build_review_package(tmp_path, NAME, raster_validator=validator)
        assert exc.value.code == "size_limit"
        assert "source files" in str(exc.value)
        assert called == []
        assert list((tmp_path / "review_packages").iterdir()) == []
    else:
        package = rp.build_review_package(
            tmp_path, NAME, raster_validator=validator
        )
        assert called == [True]
        assert_archive(package)


def test_simulated_source_can_exceed_zip_budget(tmp_path, monkeypatch):
    names, methods = raster_fixture(tmp_path)
    # Deliberately compressible simulated raster bytes.
    (tmp_path / names["cover_type_tif"]).write_bytes(b"A" * 65536)
    total = sum((tmp_path / n).stat().st_size for n in names.values())
    zip_limit = 32768
    assert total > zip_limit
    monkeypatch.setattr(rp, "MAX_SOURCE_BYTES", total)
    monkeypatch.setattr(rp, "MAX_BYTES", zip_limit)

    package = rp.build_review_package(
        tmp_path, NAME, raster_validator=simulated_raster_validator
    )
    assert 0 < package["package_bytes"] <= zip_limit < total
    assert_archive(package)
    with zipfile.ZipFile(package["archive_path"]) as archive:
        assert archive.read(names["cover_type_tif"]) == b"A" * 65536


def test_simulated_zip_budget_rejects_after_source_acceptance(tmp_path, monkeypatch):
    import random

    names, methods = raster_fixture(tmp_path)
    # Deterministic, poorly compressible simulated raster bytes.
    payload = random.Random(12345).randbytes(65536)
    (tmp_path / names["cover_type_tif"]).write_bytes(payload)
    total = sum((tmp_path / n).stat().st_size for n in names.values())
    monkeypatch.setattr(rp, "MAX_SOURCE_BYTES", total)
    monkeypatch.setattr(rp, "MAX_BYTES", 32768)
    called = []

    def validator(*args):
        called.append(True)
        return simulated_raster_validator(*args)

    before = {n: rp.sha256_file(tmp_path / n) for n in names.values()}
    with pytest.raises(rp.ExportError) as exc:
        rp.build_review_package(tmp_path, NAME, raster_validator=validator)
    assert exc.value.code == "size_limit"
    assert str(exc.value) == "ZIP exceeds the export limit."
    assert called == [True]
    assert list((tmp_path / "review_packages").iterdir()) == []
    assert all(rp.sha256_file(tmp_path / n) == h for n, h in before.items())


@pytest.mark.parametrize("over_by", [0, 1])
def test_simulated_combined_raster_polygon_budget_boundary(
    tmp_path, monkeypatch, over_by
):
    names, methods = raster_fixture(tmp_path)
    folder = tmp_path / RUN
    folder.mkdir()
    for name in pp.POLYGON_NAMES:
        (folder / name).write_bytes(b"SIMULATED polygon source " * 100)
    raster_bytes = sum(
        (tmp_path / n).stat().st_size for n in names.values()
    )
    polygon_bytes = sum(
        (folder / n).stat().st_size for n in pp.POLYGON_NAMES
    )
    total = raster_bytes + polygon_bytes
    limit = total - over_by
    assert raster_bytes <= limit
    monkeypatch.setattr(rp, "MAX_SOURCE_BYTES", limit)
    # This module imports its own reference to the constant.
    monkeypatch.setattr(pp, "MAX_SOURCE_BYTES", limit)
    polygon_validation_calls = []

    def polygon_validator(*args):
        polygon_validation_calls.append(True)
        return {"patch_count": 1}

    monkeypatch.setattr(pp, "validate_raw_patches", polygon_validator)
    before = {
        str(p.relative_to(tmp_path)): rp.sha256_file(p)
        for p in tmp_path.rglob("*") if p.is_file()
    }
    if over_by:
        with pytest.raises(rp.ExportError) as exc:
            rp.build_review_package(
                tmp_path, NAME, raw_run_directory=RUN,
                raster_validator=simulated_raster_validator
            )
        assert exc.value.code == "size_limit"
        assert "Combined raster/polygon source size" in str(exc.value)
        assert polygon_validation_calls == []
        assert list((tmp_path / "review_packages").iterdir()) == []
    else:
        package = rp.build_review_package(
            tmp_path, NAME, raw_run_directory=RUN,
            raster_validator=simulated_raster_validator
        )
        assert polygon_validation_calls == [True]
        assert package["schema_version"] == "2"
        assert_archive(package)
        with zipfile.ZipFile(package["archive_path"]) as archive:
            for name in pp.POLYGON_NAMES:
                assert archive.read(name) == (folder / name).read_bytes()
    assert all(
        rp.sha256_file(tmp_path / n) == h for n, h in before.items()
    )
