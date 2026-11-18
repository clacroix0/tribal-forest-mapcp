"""Bounded boundary snapshot and quick-look preview. No network operations."""
import csv
import re
import shutil
import struct
import zlib
from pathlib import Path

CONTEXT_SCOPE = "preliminary_raster_and_raw_polygon_context_review"
MAX_BOUNDARY_BYTES = 20 * 1024 * 1024
MAX_EDGE = 1200
GENERATED_RESERVE = 16 * 1024 * 1024
PALETTE = (
    (31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40),
    (148, 103, 189), (140, 86, 75), (227, 119, 194), (188, 189, 34),
    (23, 190, 207), (174, 199, 232), (255, 187, 120), (152, 223, 138),
)
NODATA_COLOR = (235, 235, 235)
UNKNOWN_COLOR = (120, 120, 120)


def encode_png(rgb):
    height, width, _ = rgb.shape

    def chunk(kind, data):
        body = kind + data
        return (
            struct.pack(">I", len(data)) + body
            + struct.pack(">I", zlib.crc32(body) & 0xffffffff)
        )

    raw = b"".join(b"\x00" + row.tobytes() for row in rgb)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def render_preview(stage, names, prefix, book, counts):
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from review_package import require

    with rasterio.open(stage / names["cover_type_tif"]) as ds:
        step = max(1, (max(ds.height, ds.width) + MAX_EDGE - 1) // MAX_EDGE)
        height = (ds.height + step - 1) // step
        width = (ds.width + step - 1) // step
        data = ds.read(
            1, out_shape=(height, width), resampling=Resampling.nearest
        )
    require(
        set(int(v) for v in np.unique(data)) <= set(book),
        "unknown_raster_code", "Preview encountered a code absent from the codebook."
    )
    colors = {}
    for index, code in enumerate(sorted(c for c in book if c != -9999)):
        colors[code] = (
            UNKNOWN_COLOR if book[code]["label"] == "unmapped_evt"
            else PALETTE[index % len(PALETTE)]
        )
    colors[-9999] = NODATA_COLOR
    rgb = np.empty(data.shape + (3,), dtype=np.uint8)
    for code, color in colors.items():
        rgb[data == code] = color

    png = prefix + "_preview.png"
    legend = prefix + "_preview_legend.csv"
    with (stage / png).open("xb") as stream:
        stream.write(encode_png(rgb))
    with (stage / legend).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow([
            "output_code", "output_label", "hex_color",
            "cell_count", "acres"
        ])
        for code in sorted(book):
            color = colors[code]
            n = int(counts.get(code, 0))
            writer.writerow([
                code, book[code]["label"], "#%02X%02X%02X" % color,
                n, round(n * 900 / 4046.8564224, 4),
            ])
    return [png, legend], {
        "width_pixels": width, "height_pixels": height,
        "resampling": "nearest",
        "source_raster": names["cover_type_tif"],
        "legend_counts_source": "full_validated_raster",
        "colors_may_repeat": len(book) - 1 > len(PALETTE),
        "small_patches_may_be_omitted": step > 1,
    }


def add_context(root, stage, methods, names, book, counts, used, has_polygons):
    import review_package as rp

    unavailable = {
        "included": False,
        "reason": "Legacy/intermediate package; boundary and preview are not included.",
        "final_package_completeness_established": False,
    }
    if not has_polygons:
        return [], unavailable, "", used
    sentinel = methods.get("sentinels", {}).get("boundary_clipping_performed")
    if sentinel is not True:
        return [], unavailable, "", used

    fields = ("boundary_filename", "boundary_sha256")
    if not any(field in methods for field in fields):
        return [], unavailable, "", used

    name, checksum = (methods.get(field) for field in fields)
    rp.require(
        isinstance(name, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", name)
        and Path(name).suffix.lower() in {".geojson", ".json", ".gpkg"},
        "invalid_metadata", "Boundary filename is missing, unsafe, or unsupported."
    )
    rp.require(
        isinstance(checksum, str)
        and re.fullmatch(r"[0-9a-f]{64}", checksum),
        "invalid_metadata", "Boundary checksum is missing or invalid."
    )
    source = root / name
    rp.require(not source.is_symlink(), "unsafe_file",
               "Symbolic-link boundaries are not accepted.")
    try:
        size = source.lstat().st_size
    except OSError:
        raise rp.ExportError(
            "missing_or_unreadable_file", "The recorded boundary is unavailable."
        ) from None
    rp.require(
        0 < size <= MAX_BOUNDARY_BYTES and used + size <= rp.MAX_SOURCE_BYTES,
        "size_limit", "Combined mapping, polygon, and boundary source files exceed the export limit."
    )
    rp.require(
        shutil.disk_usage(root).free
        >= used + 2 * size + 2 * GENERATED_RESERVE,
        "insufficient_space",
        "Insufficient space for the boundary, bounded preview, and archive."
    )
    prefix = names["methods_json"].removesuffix("_methods.json")
    member = prefix + "_boundary" + Path(name).suffix.lower()
    copied = rp._copy_regular(
        source, stage / member, min(MAX_BOUNDARY_BYTES, rp.MAX_SOURCE_BYTES - used)
    )
    rp.require(
        rp.sha256_file(stage / member) == checksum,
        "identity_mismatch", "Boundary differs from the mapping record."
    )
    try:
        preview_members, preview_qc = render_preview(
            stage, names, prefix, book, counts
        )
    except rp.ExportError:
        raise
    except ImportError:
        raise rp.ExportError(
            "gis_dependency_missing", "Preview dependencies are unavailable."
        ) from None
    except Exception:
        raise rp.ExportError(
            "preview_failed", "The required quick-look preview could not be generated."
        ) from None
    rp.require(
        sum((stage / n).stat().st_size for n in preview_members)
        <= GENERATED_RESERVE,
        "size_limit", "Generated preview artifacts exceed their bounded reserve."
    )
    qc = {
        "included": True,
        "boundary_member": member,
        "boundary_sha256": checksum,
        "boundary_matches_mapping_record": True,
        "boundary_geometry_revalidated_by_export": False,
        "approved_full_boundary_coverage_independently_verified": False,
        "preview": preview_qc,
        "final_package_completeness_established": False,
    }
    guide = (
        "\n## Boundary and quick-look preview\n"
        f"Add {member} in ArcGIS Pro to inspect the reference boundary used by "
        "the mapping run. Its bytes match the recorded checksum. This does not "
        "authenticate boundary approval or establish ownership, trust status, "
        "or management authority.\n\n"
        f"Open {preview_members[0]} with an ordinary image viewer and "
        f"{preview_members[1]} for its colors and full-raster acreage. "
        "The picture has no basemap, embedded legend, scale bar, or north arrow. "
        "It is a quick look, not a measurement product. Nearest-neighbor "
        "downsampling may omit small patches; colors may repeat for many classes. "
        "Light gray is NoData, including masked outside-boundary cells, not "
        "nonforest. Use the GIS layers for interpretation and measurement.\n"
    )
    return [member] + preview_members, qc, guide, used + copied
