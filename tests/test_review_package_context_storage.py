"""Descriptor compatibility and SIMULATED renewal; no cloud operations."""
import hashlib
import io
import json
import uuid

import pytest

import review_package as rp
import review_package_storage as storage

PREFIX = "cmap_12345678_v1"
CONTEXT_SCOPE = "preliminary_raster_and_raw_polygon_context_review"


def descriptor(schema, suffix=".geojson"):
    files = [
        PREFIX + "_" + value for value in rp.SUFFIXES.values()
    ] + [
        "OPEN_IN_ARCGIS_PRO.md",
        "QC_AND_LIMITATIONS.json",
        "PACKAGE_MANIFEST.json",
    ]
    scope = "preliminary_raster_review_only"
    if schema in ("2", "3"):
        files += [
            "raw_cover_type_patches.gpkg",
            "raw_patch_acreage.csv",
            "raw_patch_qc.json",
        ]
        scope = "preliminary_raster_and_raw_polygon_review"
    if schema == "3":
        files += [
            PREFIX + "_boundary" + suffix,
            PREFIX + "_preview.png",
            PREFIX + "_preview_legend.csv",
        ]
        scope = CONTEXT_SCOPE
    return {
        "schema_version": schema,
        "package_scope": scope,
        "files": files,
    }


@pytest.mark.parametrize("schema,count", [("1", 9), ("2", 12), ("3", 15)])
def test_descriptor_versions(schema, count):
    record = descriptor(schema)
    assert len(record["files"]) == count
    assert storage._descriptor_contract(record) == record["package_scope"]


@pytest.mark.parametrize("suffix", [".geojson", ".json", ".gpkg"])
def test_context_boundary_formats(suffix):
    record = descriptor("3", suffix)
    assert storage._descriptor_contract(record) == CONTEXT_SCOPE


@pytest.mark.parametrize("damage", [
    "missing", "extra", "duplicate", "wrong_run", "wrong_scope",
    "wrong_schema", "unsafe", "no_boundary", "two_boundaries",
])
def test_context_descriptor_damage_rejected(damage):
    record = descriptor("3")
    files = record["files"]
    if damage == "missing":
        files.pop()
    elif damage == "extra":
        files.append("unexpected.txt")
    elif damage == "duplicate":
        files[-1] = files[-2]
    elif damage == "wrong_run":
        files[-1] = "cmap_87654321_v1_preview_legend.csv"
    elif damage == "wrong_scope":
        record["package_scope"] = "preliminary_raster_and_raw_polygon_review"
    elif damage == "wrong_schema":
        record["schema_version"] = "2"
    elif damage == "unsafe":
        files[-1] = "../preview_legend.csv"
    elif damage == "no_boundary":
        files[-3] = PREFIX + "_boundary.txt"
    elif damage == "two_boundaries":
        files[-1] = PREFIX + "_boundary.gpkg"
    with pytest.raises(rp.ExportError) as caught:
        storage._descriptor_contract(record)
    assert caught.value.code == "storage_integrity_failed"


@pytest.mark.parametrize("schema", ["1", "2", "3"])
def test_simulated_renewal_preserves_versions_without_upload(schema):
    config = storage.StorageConfig(
        "synthetic-bucket",
        "https://s3.ca-tor.cloud-object-storage.appdomain.cloud",
        "ca-tor", "mapcp-review/", "SIMULATED", "SIMULATED",
    )
    package_id = str(uuid.uuid4())
    payload = b"SIMULATED archive bytes; descriptor/renewal test, not ZIP validation"
    checksum = hashlib.sha256(payload).hexdigest()
    record = {
        **descriptor(schema),
        "package_id": package_id,
        "package_bytes": len(payload),
        "package_sha256": checksum,
        "warnings": [],
    }
    zip_key = storage._key(config, package_id, "mapcp_raster_review.zip")
    record_key = storage._key(config, package_id, "package_record.json")
    objects = {
        zip_key: payload,
        record_key: json.dumps(record).encode("utf-8"),
    }

    class SimulatedCOS:
        def __init__(self):
            self.reads = []
            self.signs = 0

        def head_object(self, Bucket, Key):
            assert Bucket == config.bucket
            return {
                "ContentLength": len(objects[Key]),
                "Metadata": {"sha256": checksum},
            }

        def get_object(self, Bucket, Key):
            assert Bucket == config.bucket
            self.reads.append(Key)
            return {"Body": io.BytesIO(objects[Key])}

        def put_object(self, **kwargs):
            pytest.fail("Renewal must not upload objects")

        def generate_presigned_url(self, method, Params, ExpiresIn):
            assert method == "get_object"
            assert ExpiresIn == storage.LINK_SECONDS
            self.signs += 1
            return (
                config.endpoint + "/" + Params["Bucket"] + "/" + Params["Key"]
                + "?SIMULATED=not-a-real-link"
            )

    client = SimulatedCOS()
    result = storage.renew_package(client, config, package_id)
    assert result["package_scope"] == record["package_scope"]
    assert result["files"] == record["files"]
    assert result["link_renewed"] is True
    assert result["storage_uploaded"] is False
    assert record_key in client.reads and zip_key in client.reads
    assert client.signs == 1
    if schema in ("2", "3"):
        assert any("Raw polygons included" in w for w in result["warnings"])
        assert not any("This is a raster-only package" in w for w in result["warnings"])

    objects[zip_key] = b"X" + payload[1:]
    with pytest.raises(rp.ExportError) as caught:
        storage.renew_package(client, config, package_id)
    assert caught.value.code == "storage_integrity_failed"
    assert client.signs == 1
