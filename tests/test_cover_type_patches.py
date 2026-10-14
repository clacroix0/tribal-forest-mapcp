"""Synthetic Slice 4 tests. Raster-dependent tests require local Rasterio."""
import csv
import json
from collections import namedtuple
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from pydantic import ValidationError
from shapely.geometry import box

import cover_type_patches as p

Transform = namedtuple("Transform", "a b c d e f")
T = Transform(30.0, 0.0, 1000.0, 0.0, -30.0, 2000.0)
NAME = "cmap_12345678_v1_methods.json"


def document(data, book, transform=T, crs=5070):
    valid = data != -9999
    vals, counts = np.unique(data[valid], return_counts=True)
    stats = []
    for code, count in zip(vals, counts):
        row = book[int(code)]
        status = row["forest_land_status"]
        stats.append({"output_code": int(code), "output_label": row["output_label"],
                      "candidate_forest_land": True if status == "forest_land" else False if status == "nonforest" else None,
                      "cell_count": int(count), "square_meters": int(count)*900,
                      "acres": round(int(count)*900/p.ACRE_M2, 4)})
    return {"document_type": "candidate_cover_type_methods_and_provenance", "mapping_status": "complete",
            "rasters_written": True, "write_errors": [], "job_id": "12345678-1111-2222-3333-444444444444",
            "crosswalk_id": "synthetic_v1", "crosswalk_version": "v1", "cover_scheme_id": "example",
            "cover_scheme_version": "v1", "crosswalk_approval_note": "Synthetic test fixture, not field results.",
            "sentinels": {k: True for k in ["classification_performed", "crosswalk_applied", "candidate_cover_types_produced", "candidate_forest_land_produced"]},
            "acreage_closure": {k: True for k in ["cover_type_valid_sum_matches", "forest_land_valid_sum_matches", "total_pixel_sum_matches"]},
            "raster_shape": list(data.shape), "raster_crs_epsg": crs, "raster_transform": list(transform)[:6],
            "nodata_value": -9999, "valid_cell_count": int(valid.sum()), "total_pixels": data.size,
            "nodata_cell_count": int((~valid).sum()), "valid_acres": round(int(valid.sum())*900/p.ACRE_M2,4),
            "cover_type_stats": stats, "warnings": [], "universal_review_flags": []}


def book_values():
    return {c: {"output_label": label, "candidate_code": label.removeprefix("candidate_"),
                "candidate_name": "Synthetic " + label, "forest_land_status": status,
                "class_source_evt_codes": ""}
            for c, label, status in [(1,"candidate_P","forest_land"), (4,"candidate_BR","nonforest"),
                                     (7,"candidate_RIP_UNCERTAIN","unknown"), (8,"candidate_UNCERTAIN_PINE_OAK","unknown"),
                                     (255,"unmapped_evt","unknown"),(-9999,"nodata","unknown")]}


@pytest.mark.parametrize("bad", ["../cmap_12345678_v1_methods.json", "C:\\temp\\x.json", "x.txt"])
def test_request_rejects_paths_and_wrong_names(bad):
    with pytest.raises(ValidationError):
        p.RawPatchRequest(methods_filename=bad)


def test_request_forbids_extra_fields():
    with pytest.raises(ValidationError):
        p.RawPatchRequest(methods_filename=NAME, connectivity=8)


@pytest.mark.parametrize("raw,expected", [("TRUE","forest_land"),("false","nonforest"),("null","unknown"),("","unknown")])
def test_forest_status_preserves_unknown(raw,expected):
    assert p._forest_status(raw)==expected


def test_invalid_forest_status_rejected():
    with pytest.raises(p.PatchValidationError):
        p._forest_status("maybe")


def test_codebook_duplicate_rejected(tmp_path):
    f=tmp_path/"codes.csv"
    f.write_text("output_code,output_label,candidate_forest_land,description,source_evt_codes\n1,candidate_P,true,x,7054\n1,candidate_P,true,x,7054\n")
    with pytest.raises(p.PatchValidationError,match="Duplicate"):
        p._codebook(f)


def test_codebook_schema_rejected(tmp_path):
    f=tmp_path/"codes.csv"; f.write_text("value,name\n1,x\n")
    with pytest.raises(p.PatchValidationError):
        p._codebook(f)


def test_codebook_reads_bom_and_null(tmp_path):
    f=tmp_path/"codes.csv"
    f.write_text("output_code,output_label,candidate_forest_land,description,source_evt_codes\n7,candidate_RIP_UNCERTAIN,null,test,9329|9519\n",encoding="utf-8-sig")
    assert p._codebook(f)[7]["forest_land_status"]=="unknown"


def test_path_security(tmp_path):
    with pytest.raises(p.PatchValidationError):
        p._input_file(tmp_path,"../x.json",100)


def test_missing_input_structured_failure(tmp_path):
    result=p.create_raw_cover_type_patches(tmp_path,p.RawPatchRequest(methods_filename=NAME))
    assert result.status=="failed" and not result.candidate_polygons_produced
    assert list(tmp_path.iterdir())==[]


def test_cell_area_and_crs_rules():
    assert p._cell_area(T,5070)==900
    with pytest.raises(p.PatchValidationError):
        p._cell_area(T,4326)
    with pytest.raises(p.PatchValidationError):
        p._cell_area(T._replace(a=10),5070)
    with pytest.raises(p.PatchValidationError):
        p._cell_area(T._replace(b=1),5070)


def test_source_counts_validated():
    data=np.array([[1,4],[7,-9999]],dtype="int32"); book=book_values(); doc=document(data,book)
    assert p._check_source(data,data!=-9999,-9999,T,5070,doc,book)=={1:1,4:1,7:1}
    doc["cover_type_stats"][0]["cell_count"]=2
    with pytest.raises(p.PatchValidationError,match="counts"):
        p._check_source(data,data!=-9999,-9999,T,5070,doc,book)


def test_source_rejects_old_wrong_acreage():
    data=np.ones((2,2),dtype="int32"); book=book_values(); doc=document(data,book)
    doc["valid_acres"]=375.2
    with pytest.raises(p.PatchValidationError,match="acres"):
        p._check_source(data,data!=-9999,-9999,T,5070,doc,book)


def test_label_and_forest_status_consistency():
    data=np.ones((2,2),dtype="int32"); book=book_values(); doc=document(data,book)
    doc["cover_type_stats"][0]["output_label"]="wrong"
    with pytest.raises(p.PatchValidationError,match="label"):
        p._check_source(data,data!=-9999,-9999,T,5070,doc,book)
    doc=document(data,book); doc["cover_type_stats"][0]["candidate_forest_land"]=False
    with pytest.raises(p.PatchValidationError,match="forest-land"):
        p._check_source(data,data!=-9999,-9999,T,5070,doc,book)


def test_methods_requires_completed_mapping():
    data=np.ones((1,1),dtype="int32"); doc=document(data,book_values()); p._validate_methods(doc)
    doc["mapping_status"]="failed"
    with pytest.raises(p.PatchValidationError): p._validate_methods(doc)


def test_all_nodata_rejected():
    data=np.full((2,2),-9999,dtype="int32"); book=book_values(); doc=document(data,book)
    with pytest.raises(p.PatchValidationError,match="no valid"):
        p._check_source(data,data!=-9999,-9999,T,5070,doc,book)


def test_unrecognized_category_rejected():
    data=np.array([[42]],dtype="int32"); doc=document(np.array([[1]],dtype="int32"),book_values())
    with pytest.raises(p.PatchValidationError,match="absent"):
        p._check_source(data,data!=-9999,-9999,T,5070,doc,book_values())


def test_review_flags_are_explicitly_class_level():
    flags=p._flags("candidate_BR",{"universal_review_flags":[]})
    assert "oak_brush_vs_oak_woodland_review_required" in flags
    assert "professional_forestry_review_required" in flags


def test_geopackage_attribute_readback(tmp_path):
    f=gpd.GeoDataFrame({"patch_id":["CTP_000001"],"cell_count":[1],"area_m2":[900.0],
                        "forest_land_status":["unknown"],"review_flags":["needs_review"]},
                       geometry=[box(0,0,30,30)],crs=5070)
    target=tmp_path/"test.gpkg"
    f.to_file(target,layer=p.LAYER,driver="GPKG",engine="pyogrio",index=False)
    read=gpd.read_file(target,layer=p.LAYER,engine="pyogrio")
    p._readback(f,read,5070)
    read.loc[0,"forest_land_status"]="nonforest"
    with pytest.raises(p.PatchValidationError): p._readback(f,read,5070)


def raster_case(tmp_path,data,**options):
    rasterio=pytest.importorskip("rasterio",reason="Local Rasterio required for synthetic TIFF tests")
    from rasterio.transform import Affine
    data=np.array(data,dtype=options.get("dtype","int32"))
    transform=Affine(*T); crs=options.get("crs",5070)
    book=book_values(); doc=document(data,book,transform,crs)
    prefix=NAME.removesuffix("_methods.json")
    tif=tmp_path/(prefix+"_cover_type_30m.tif")
    count=options.get("bands",1)
    with rasterio.open(tif,"w",driver="GTiff",height=data.shape[0],width=data.shape[1],count=count,
                       dtype=str(data.dtype),crs=crs,transform=transform,nodata=-9999) as dst:
        for band in range(1,count+1): dst.write(data,band)
    codebook=tmp_path/(prefix+"_cover_type_codebook.csv")
    with codebook.open("w",encoding="utf-8-sig",newline="") as stream:
        w=csv.writer(stream); w.writerow(["output_code","output_label","candidate_forest_land","description","source_evt_codes"])
        for code,row in book.items():
            status=row["forest_land_status"]
            w.writerow([code,row["output_label"],"true" if status=="forest_land" else "false" if status=="nonforest" else "null",row["candidate_name"],row["class_source_evt_codes"]])
    methods=tmp_path/NAME; methods.write_text(json.dumps(doc),encoding="utf-8")
    return p.RawPatchRequest(methods_filename=NAME),[tif,codebook,methods]


def run_case(tmp_path,data,**options):
    req,files=raster_case(tmp_path,data,**options)
    before={f.name:p._digest(f) for f in files}
    result=p.create_raw_cover_type_patches(tmp_path,req)
    assert before=={f.name:p._digest(f) for f in files}
    return result


def test_edge_neighbors_merge(tmp_path):
    result=run_case(tmp_path,[[1,1],[1,1]])
    assert result.status=="complete_review_required",result.errors
    assert result.patch_count==1 and result.qc["total_valid_cells"]==4


def test_corner_neighbors_stay_separate(tmp_path):
    result=run_case(tmp_path,[[1,4],[4,1]])
    assert result.status=="complete_review_required",result.errors
    assert result.patch_count==4


def test_diagonal_cells_join_if_edge_path_exists(tmp_path):
    result=run_case(tmp_path,[[1,1],[4,1]])
    assert result.status=="complete_review_required",result.errors
    assert result.patch_count==2


def test_uncertain_unmapped_and_nodata_preserved(tmp_path):
    result=run_case(tmp_path,[[7,8],[255,-9999]])
    assert result.status=="complete_review_required",result.errors
    assert result.patch_count==3 and result.qc["nodata_cells"]==1
    frame=gpd.read_file(result.artifacts["geopackage"],layer=p.LAYER,engine="pyogrio")
    assert set(frame.output_code)=={7,8,255}
    assert set(frame.forest_land_status)=={"unknown"}
    assert set(frame.review_flag_scope)=={"conservative_class_level_not_patch_measured"}


def test_nodata_hole_not_filled(tmp_path):
    result=run_case(tmp_path,[[1,1,1],[1,-9999,1],[1,1,1]])
    assert result.status=="complete_review_required",result.errors
    frame=gpd.read_file(result.artifacts["geopackage"],layer=p.LAYER,engine="pyogrio")
    assert result.patch_count==1 and len(frame.geometry.iloc[0].interiors)==1
    assert frame.area_m2.sum()==7200


def test_artifacts_and_no_overwrite(tmp_path):
    req,files=raster_case(tmp_path,[[1,4],[7,8]])
    first=p.create_raw_cover_type_patches(tmp_path,req)
    assert first.status=="complete_review_required",first.errors
    before=p._digest(Path(first.artifacts["geopackage"]))
    second=p.create_raw_cover_type_patches(tmp_path,req)
    assert second.status=="complete_review_required",second.errors
    assert first.artifacts["geopackage"]!=second.artifacts["geopackage"]
    assert p._digest(Path(first.artifacts["geopackage"]))==before
    for key in ["geopackage","acreage_csv","qc_json","opening_instructions"]:
        assert Path(first.artifacts[key]).is_file()
    report=json.loads(Path(first.artifacts["qc_json"]).read_text())
    assert report["connectivity"]==4 and report["candidate_stands_produced"] is False
    assert report["arcgis_pro_review_performed"] is False
    assert report["qc"]["geopackage_readback_passed"] is True
    assert report["qc"]["raster_roundtrip_matches"] is True


@pytest.mark.parametrize("options",[{"bands":2},{"dtype":"float32"},{"crs":4326}])
def test_rejects_unsupported_raster(tmp_path,options):
    result=run_case(tmp_path,[[1,4]],**options)
    assert result.status=="failed" and not result.candidate_polygons_produced


def test_changed_raster_counts_fail(tmp_path):
    req,files=raster_case(tmp_path,[[1,1]])
    doc=json.loads(files[2].read_text()); doc["cover_type_stats"][0]["cell_count"]=1
    files[2].write_text(json.dumps(doc))
    result=p.create_raw_cover_type_patches(tmp_path,req)
    assert result.status=="failed" and result.stage=="validate_source_lineage"


def test_write_failure_leaves_explicit_failure_record(tmp_path,monkeypatch):
    req,files=raster_case(tmp_path,[[1]])
    def fail(*args,**kwargs): raise OSError("simulated write failure")
    monkeypatch.setattr(gpd.GeoDataFrame,"to_file",fail)
    result=p.create_raw_cover_type_patches(tmp_path,req)
    assert result.status=="failed" and not result.candidate_polygons_produced
    assert Path(result.artifacts["failure_report"]).is_file()


def test_pixel_limit_checked_before_polygonization(tmp_path,monkeypatch):
    req,files=raster_case(tmp_path,[[1,1]])
    monkeypatch.setattr(p,"MAX_PIXELS",1)
    result=p.create_raw_cover_type_patches(tmp_path,req)
    assert result.status=="failed" and "pixel limit" in result.errors[0]

def test_readback_handles_pandas_string_dtype():
    expected = gpd.GeoDataFrame(
        {
            "patch_id": ["CTP_000001"],
            "cell_count": [1],
            "area_m2": [900.0],
            "forest_land_status": ["unknown"],
            "review_flags": ["needs_review"],
        },
        geometry=[box(0, 0, 30, 30)],
        crs=5070,
    )

    for column in (
        "patch_id",
        "forest_land_status",
        "review_flags",
    ):
        expected[column] = expected[column].astype("string")

    actual = expected.copy()
    p._readback(expected, actual, 5070)

    actual.loc[0, "forest_land_status"] = "nonforest"

    with pytest.raises(p.PatchValidationError):
        p._readback(expected, actual, 5070)
