"""Actual synthetic context packaging and bounded failure cases."""
import json
import struct
import zipfile

import pytest

import review_package as rp
import review_package_context as context
import review_package_storage as storage
import test_review_package_polygons as fixtures


def prepare(root):
    names, methods = fixtures.raster_fixture(root, real=True)
    boundary = root / "synthetic.geojson"
    boundary.write_text(json.dumps({
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:5070"}},
        "features": [{
            "type": "Feature",
            "properties": {"test_only": True},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [1000, 1910], [1090, 1910], [1090, 2000],
                    [1000, 2000], [1000, 1910]
                ]],
            },
        }],
    }))
    methods["sentinels"]["boundary_clipping_performed"] = True
    methods["boundary_filename"] = boundary.name
    methods["boundary_sha256"] = rp.sha256_file(boundary)
    methods["outside_boundary_cells"] = 0
    methods["evt_nodata_inside_boundary_cells"] = 1
    (root / fixtures.NAME).write_text(json.dumps(methods))
    import cover_type_patches as patches
    result = patches.create_raw_cover_type_patches(
        root, patches.RawPatchRequest(methods_filename=fixtures.NAME)
    )
    assert result.status == "complete_review_required", result.errors
    run = fixtures.Path(result.artifacts["geopackage"]).parent.name
    return names, methods, boundary, run


def test_actual_context_package_and_simulated_renewal(tmp_path):
    names, methods, boundary, run = prepare(tmp_path)
    before = {
        str(p.relative_to(tmp_path)): rp.sha256_file(p)
        for p in tmp_path.rglob("*") if p.is_file()
    }
    package = rp.build_review_package(
        tmp_path, fixtures.NAME, raw_run_directory=run
    )
    assert package["schema_version"] == "3"
    assert package["package_scope"] == context.CONTEXT_SCOPE
    assert len(package["files"]) == 15
    fixtures.assert_archive(package)
    assert storage._descriptor_contract(package) == context.CONTEXT_SCOPE
    prefix = fixtures.NAME.removesuffix("_methods.json")
    with zipfile.ZipFile(package["archive_path"]) as archive:
        assert archive.read(prefix + "_boundary.geojson") == boundary.read_bytes()
        png = archive.read(prefix + "_preview.png")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", png[16:24]) == (3, 3)
        qc = json.loads(archive.read("QC_AND_LIMITATIONS.json"))
        assert qc["review_context"]["included"] is True
        assert qc["generalization_status"] == "not_included"
        assert not qc["full_approved_boundary_coverage_verified"]
    assert all(rp.sha256_file(tmp_path / n) == h for n, h in before.items())
    client = fixtures.SimulatedCOS()
    delivered = storage.store_package(client, fixtures.CONFIG, package)
    assert delivered["package_scope"] == context.CONTEXT_SCOPE
    puts = client.puts
    renewed = storage.renew_package(
        client, fixtures.CONFIG, package["package_id"]
    )
    assert renewed["link_renewed"] and client.puts == puts


@pytest.mark.parametrize("damage", ["changed", "missing", "symlink"])
def test_boundary_damage_rejected_and_stage_cleaned(tmp_path, damage):
    _, _, boundary, run = prepare(tmp_path)
    original = boundary.read_bytes()
    if damage == "changed":
        boundary.write_bytes(original + b" ")
    elif damage == "missing":
        boundary.unlink()
    else:
        target = tmp_path / "real_boundary.geojson"
        target.write_bytes(original)
        boundary.unlink()
        boundary.symlink_to(target)
    with pytest.raises(rp.ExportError):
        rp.build_review_package(
            tmp_path, fixtures.NAME, raw_run_directory=run
        )
    assert list((tmp_path / "review_packages").iterdir()) == []


def test_boundary_counts_toward_combined_source_budget(tmp_path, monkeypatch):
    names, _, _, run = prepare(tmp_path)
    source_bytes = sum((tmp_path / n).stat().st_size for n in names.values())
    source_bytes += sum(
        (tmp_path / run / n).stat().st_size for n in fixtures.pp.POLYGON_NAMES
    )
    monkeypatch.setattr(rp, "MAX_SOURCE_BYTES", source_bytes)
    with pytest.raises(rp.ExportError) as caught:
        rp.build_review_package(
            tmp_path, fixtures.NAME, raw_run_directory=run
        )
    assert caught.value.code == "size_limit"
    assert list((tmp_path / "review_packages").iterdir()) == []


def test_png_round_trip_and_crc():
    import zlib
    np = pytest.importorskip("numpy")
    rgb = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)
    encoded = context.encode_png(rgb)
    position, compressed = 8, []
    while position < len(encoded):
        size = struct.unpack(">I", encoded[position:position + 4])[0]
        body = encoded[position + 4:position + 8 + size]
        crc = struct.unpack(
            ">I", encoded[position + 8 + size:position + 12 + size]
        )[0]
        assert crc == zlib.crc32(body) & 0xffffffff
        if body[:4] == b"IDAT":
            compressed.append(body[4:])
        position += 12 + size
    raw = zlib.decompress(b"".join(compressed))
    assert raw == b"".join(b"\x00" + row.tobytes() for row in rgb)
