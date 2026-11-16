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
        pp.snapshot_raw_patches(tmp_path, tmp_path, RUN, rp.MAX_BYTES)
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
