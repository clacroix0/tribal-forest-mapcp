import csv
import json
import math
import re
import time
import xml.etree.ElementTree as _ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from io import BytesIO, StringIO
from pyproj import Transformer
import zipfile
from urllib.parse import urlparse
from rasterio.warp import transform_bounds

import rasterio
import geopandas as gpd
import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import box
from shapely.validation import explain_validity


mcp = MCPServer("Tribal Forest MapCP")


class MappingRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    project_name: str = Field(
        min_length=1,
        max_length=120,
        description="A short name for the preliminary mapping project.",
    )

    boundary_source: str = Field(
        min_length=1,
        max_length=300,
        description=(
            "A public boundary source, URL, file reference, or other "
            "description of the proposed analysis boundary."
        ),
    )

    mapping_objective: Literal[
        "inventory_planning",
        "forest_management_plan_development",
    ] = Field(
        description="The planning purpose for the preliminary map."
    )

    requested_cover_scheme: Literal[
        "broad_candidate_cover_types_v1"
    ] = Field(
        description=(
            "The approved broad cover-type scheme to use for the "
            "preliminary mapping workflow."
        ),
    )


# Legacy/developer-only: retained but not exposed through MCP.
# @mcp.tool()
def inspect_mapping_request(request: MappingRequest) -> dict:
    """
    Validate a preliminary Tribal Forest MapCP request before GIS processing.

    This first version validates request information only. It does not inspect
    a boundary file, retrieve public data, calculate acreage, or create maps.
    """
    review_flags = [
        "Boundary has not yet been geometrically validated.",
        "No public data coverage has been inspected yet.",
        "Candidate cover types must remain preliminary and reviewable.",
        "Professional forestry and GIS review is required before use.",
    ]

    next_steps = [
        "Validate the boundary geometry, CRS, and units.",
        "Inspect coverage and dates for approved public mapping inputs.",
        "Confirm the cover-class crosswalk and minimum mapping unit.",
        "Create candidate forest/nonforest and cover-type layers.",
        "Calculate acreage summaries and export an ArcGIS Pro review package.",
    ]

    return {
        "status": "request_accepted_for_input_inspection",
        "project_name": request.project_name,
        "mapping_objective": request.mapping_objective,
        "requested_cover_scheme": request.requested_cover_scheme,
        "boundary_source_received": request.boundary_source,
        "review_flags": review_flags,
        "next_steps": next_steps,
        "limitations": [
            "This tool validates request structure only.",
            "It does not establish ownership, trust status, management responsibility, or legal access.",
            "It does not validate a boundary against public records.",
            "It does not create a forest/nonforest or cover-type map.",
        ],
    }

BIA_BOUNDARY_LAYER = (
    "https://geopub.epa.gov/ArcGIS/rest/services/"
    "EMEF/BIA_Tribal/MapServer/2"
)

# Census Federal American Indian Reservations (AIANNH) – TIGERweb/AIANNHA layer 2.
# Verified live 2026-10-xx: HTTP 200, BASENAME field present, Acoma query returns
# BASENAME='Acoma' / NAME='Acoma Pueblo'. Layer 2 is the current-vintage Federal
# American Indian Reservations layer within the AIANNHA service.
CENSUS_BOUNDARY_LAYER = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/"
    "TIGERweb/AIANNHA/MapServer/2"
)

OUTPUT_FOLDER = Path(__file__).resolve().parent / "outputs"
MAX_RESPONSE_BYTES = 5_000_000


def _read_bia_response(params: dict) -> dict:
    """
    Query the allowlisted BIA National Land Area Representation layer.

    Uses bounded retries, a request timeout, no redirects, and a maximum
    response size. This helper does not accept arbitrary URLs.
    """
    for attempt in range(2):
        try:
            with httpx.Client(
                timeout=20.0,
                follow_redirects=False,
            ) as client:
                with client.stream(
                    "GET",
                    f"{BIA_BOUNDARY_LAYER}/query",
                    params=params,
                ) as response:
                    response.raise_for_status()

                    if response.is_redirect:
                        raise ToolError(
                            "Source redirected; refusing to follow an "
                            "unreviewed URL."
                        )

                    body = bytearray()

                    for chunk in response.iter_bytes():
                        body.extend(chunk)

                        if len(body) > MAX_RESPONSE_BYTES:
                            raise ToolError(
                                "Boundary response exceeded the 5 MB test "
                                "limit."
                            )

            return json.loads(body)

        except httpx.TransportError:
            if attempt == 1:
                raise
            time.sleep(1)

    raise ToolError("BIA boundary request did not complete.")


def _read_census_response(params: dict) -> dict:
    """
    Query the allowlisted Census AIANNH TIGERweb layer.

    Uses bounded retries, a request timeout, no redirects, and a maximum
    response size. This helper does not accept arbitrary URLs.
    """
    for attempt in range(2):
        try:
            with httpx.Client(
                timeout=20.0,
                follow_redirects=False,
            ) as client:
                with client.stream(
                    "GET",
                    f"{CENSUS_BOUNDARY_LAYER}/query",
                    params=params,
                ) as response:
                    response.raise_for_status()

                    if response.is_redirect:
                        raise ToolError(
                            "Census source redirected; refusing to follow an "
                            "unreviewed URL."
                        )

                    body = bytearray()

                    for chunk in response.iter_bytes():
                        body.extend(chunk)

                        if len(body) > MAX_RESPONSE_BYTES:
                            raise ToolError(
                                "Census boundary response exceeded the 5 MB "
                                "test limit."
                            )

            return json.loads(body)

        except httpx.TransportError:
            if attempt == 1:
                raise
            time.sleep(1)

    raise ToolError("Census boundary request did not complete.")


@mcp.tool()
def find_bia_land_area_candidates(search_name: str) -> dict:
    """
    Search BIA National Land Area Representation records by name.

    This searches the allowlisted BIA land-area layer and returns up to 10
    candidate records without downloading or selecting a geometry. Review the
    candidate records before retrieving any one boundary.

    A BIA public land-area representation does not establish ownership, trust
    status, jurisdiction, forestry management responsibility, legal access,
    or the appropriate analysis boundary.
    """
    name = search_name.strip()

    if not re.fullmatch(r"[A-Za-z][A-Za-z '-]{0,79}", name):
        raise ToolError(
            "Enter a search name of 1–80 characters using letters, spaces, "
            "apostrophes, or hyphens."
        )

    escaped_name = name.replace("'", "''")

    params = {
        "where": f"UPPER(LARName) LIKE UPPER('%{escaped_name}%')",
        "outFields": "OBJECTID,LARID,LARName,GISAcres",
        "returnGeometry": "false",
        "resultRecordCount": "10",
        "orderByFields": "LARName ASC",
        "f": "json",
    }

    try:
        data = _read_bia_response(params)
    except (httpx.HTTPError, ToolError, ValueError) as error:
        return {
            "status": "source_failed",
            "source": BIA_BOUNDARY_LAYER,
            "error": str(error),
            "candidate_count": 0,
        }

    if "error" in data:
        return {
            "status": "source_failed",
            "source": BIA_BOUNDARY_LAYER,
            "error": data["error"],
            "candidate_count": 0,
        }

    features = data.get("features", [])

    candidates = [
        {
            "object_id": feature["attributes"].get("OBJECTID"),
            "lar_id": feature["attributes"].get("LARID"),
            "lar_name": feature["attributes"].get("LARName"),
            "source_gis_acres": feature["attributes"].get("GISAcres"),
        }
        for feature in features
    ]

    if not candidates:
        return {
            "status": "not_found",
            "searched_name": name,
            "source": BIA_BOUNDARY_LAYER,
            "candidate_count": 0,
            "message": (
                "No BIA land-area representation matched this search text. "
                "Try a shorter or alternate public name."
            ),
        }

    return {
        "status": "candidates_found_review_required",
        "searched_name": name,
        "source_agency": "Bureau of Indian Affairs",
        "source_layer": BIA_BOUNDARY_LAYER,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "review_flags": [
            "Candidate records have not been downloaded or geometry-validated.",
            "Do not assume a public land-area representation is the forestry project boundary.",
            "Do not infer ownership, jurisdiction, trust status, management responsibility, or legal access.",
        ],
    }


@mcp.tool()
def download_bia_land_area(object_id: int) -> dict:
    """
    Download one specifically selected BIA National Land Area Representation.

    Call only after reviewing candidates returned by
    find_bia_land_area_candidates. The downloaded GeoJSON must still pass
    geometry, CRS, and acreage checks before use in preliminary mapping.
    """
    if object_id <= 0:
        raise ToolError("object_id must be a positive integer.")

    params = {
        "where": f"OBJECTID = {object_id}",
        "outFields": "OBJECTID,LARID,LARName,GISAcres",
        "returnGeometry": "true",
        "outSR": "4326",
        "resultRecordCount": "2",
        "f": "geojson",
    }

    try:
        data = _read_bia_response(params)
    except (httpx.HTTPError, ToolError, ValueError) as error:
        return {
            "status": "source_failed",
            "source": BIA_BOUNDARY_LAYER,
            "error": str(error),
            "boundary_saved": False,
        }

    if "error" in data:
        return {
            "status": "source_failed",
            "source": BIA_BOUNDARY_LAYER,
            "error": data["error"],
            "boundary_saved": False,
        }

    features = data.get("features", [])

    if data.get("type") != "FeatureCollection":
        return {
            "status": "unexpected_source_response",
            "source": BIA_BOUNDARY_LAYER,
            "boundary_saved": False,
        }

    if len(features) != 1 or data.get("exceededTransferLimit"):
        return {
            "status": "review_required",
            "message": (
                "The selected OBJECTID did not produce exactly one "
                "unambiguous BIA boundary."
            ),
            "boundary_saved": False,
        }

    feature = features[0]
    properties = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}

    if (
        geometry.get("type") not in {"Polygon", "MultiPolygon"}
        or not geometry.get("coordinates")
    ):
        return {
            "status": "invalid_geometry_response",
            "boundary_saved": False,
        }

    lar_name = str(properties.get("LARName") or "bia_land_area")
    lar_id = str(properties.get("LARID") or object_id)
    slug = re.sub(r"[^a-z0-9]+", "_", lar_name.lower()).strip("_")
    timestamp = datetime.now(timezone.utc)
    run_id = timestamp.strftime("%Y%m%dT%H%M%S%fZ")

    OUTPUT_FOLDER.mkdir(exist_ok=True)
    boundary_file = OUTPUT_FOLDER / f"{slug}_{run_id}.geojson"
    manifest_file = OUTPUT_FOLDER / f"{slug}_{run_id}_source.json"

    limitations = [
        "Public BIA land-area representation; not title, trust-status, or jurisdiction verification.",
        "Does not establish forestry management responsibility or legal access.",
        "Geometry topology and calculated acreage have not yet been validated.",
        "BIA source GIS acres are source attributes and may differ from later MapCP calculations.",
        "No imagery inspection or candidate cover-type mapping has been performed.",
    ]

    manifest = {
        "source_agency": "Bureau of Indian Affairs",
        "source_layer": BIA_BOUNDARY_LAYER,
        "source_feature": {
            "object_id": properties.get("OBJECTID"),
            "lar_id": properties.get("LARID"),
            "lar_name": properties.get("LARName"),
            "source_gis_acres": properties.get("GISAcres"),
        },
        "query_parameters": params,
        "retrieved_at_utc": timestamp.isoformat(),
        "output_crs": "EPSG:4326",
        "feature_count": 1,
        "limitations": limitations,
    }

    boundary_file.write_text(json.dumps(data), encoding="utf-8")
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "status": "downloaded_requires_geometry_review",
        "source_name": properties.get("LARName"),
        "source_lar_id": properties.get("LARID"),
        "source_gis_acres": properties.get("GISAcres"),
        "geometry_type": geometry["type"],
        "feature_count": 1,
        "boundary_geojson": str(boundary_file),
        "source_manifest": str(manifest_file),
        "review_flags": limitations,
    }


@mcp.tool()
def find_census_reservation_reference(boundary_name: str) -> dict:
    """
    Retrieve one exact-name Census reservation reference polygon as GeoJSON.

    Use a Census BASENAME such as "Mescalero Apache" or "Acoma". This tool
    searches only the allowlisted Census Federal American Indian Reservations
    (AIANNH) TIGERweb layer and returns a comparison reference only.

    Use as a cross-check or fallback alongside the BIA NLAR. A Census
    reference polygon does not verify ownership, trust status, jurisdiction,
    forestry management responsibility, or legal access.

    Review note: confirm BASENAME field availability and layer path before
    production use on the RHEL VM or another environment.
    """
    name = boundary_name.strip()

    if not re.fullmatch(r"[A-Za-z][A-Za-z '-]{0,79}", name):
        raise ToolError(
            "Enter a name of 1–80 characters using letters, spaces, "
            "apostrophes, or hyphens."
        )

    escaped_name = name.replace("'", "''")

    params = {
        "where": f"BASENAME = '{escaped_name}'",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "resultRecordCount": "2",
        "f": "geojson",
    }

    try:
        data = _read_census_response(params)
    except (httpx.HTTPError, ToolError, ValueError) as error:
        return {
            "status": "source_failed",
            "source": CENSUS_BOUNDARY_LAYER,
            "error": str(error),
            "boundary_saved": False,
        }

    if "error" in data:
        return {
            "status": "source_failed",
            "source": CENSUS_BOUNDARY_LAYER,
            "error": data["error"],
            "boundary_saved": False,
        }

    features = data.get("features", [])

    if data.get("type") != "FeatureCollection":
        return {
            "status": "unexpected_source_response",
            "boundary_saved": False,
        }

    if not features:
        return {
            "status": "not_found",
            "searched_name": name,
            "source": CENSUS_BOUNDARY_LAYER,
            "boundary_saved": False,
        }

    if len(features) != 1 or data.get("exceededTransferLimit"):
        return {
            "status": "review_required",
            "message": "The query did not produce one unambiguous boundary.",
            "boundary_saved": False,
        }

    feature = features[0]
    geometry = feature.get("geometry") or {}

    if (
        geometry.get("type") not in {"Polygon", "MultiPolygon"}
        or not geometry.get("coordinates")
    ):
        return {
            "status": "invalid_geometry_response",
            "boundary_saved": False,
        }

    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    timestamp = datetime.now(timezone.utc)
    run_id = timestamp.strftime("%Y%m%dT%H%M%S%fZ")

    OUTPUT_FOLDER.mkdir(exist_ok=True)
    boundary_file = OUTPUT_FOLDER / f"{slug}_{run_id}.geojson"
    manifest_file = OUTPUT_FOLDER / f"{slug}_{run_id}_source.json"

    limitations = [
        "Census comparison/fallback reference; not ownership or trust-status verification.",
        "Does not establish forestry management responsibility or legal access.",
        "Polygon topology and acreage have not been validated.",
        "No imagery inspection or cover-type mapping has been performed.",
    ]

    manifest = {
        "source_agency": "U.S. Census Bureau",
        "source_layer": CENSUS_BOUNDARY_LAYER,
        "query_parameters": params,
        "retrieved_at_utc": timestamp.isoformat(),
        "output_crs": "EPSG:4326",
        "feature_count": len(features),
        "limitations": limitations,
    }

    boundary_file.write_text(json.dumps(data), encoding="utf-8")
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "status": "downloaded_requires_review",
        "source_name": feature.get("properties", {}).get("NAME"),
        "geometry_type": geometry["type"],
        "feature_count": len(features),
        "boundary_geojson": str(boundary_file),
        "source_manifest": str(manifest_file),
        "provenance": manifest,
        "review_flags": limitations,
    }
@mcp.tool()
def inspect_mapping_inputs(boundary_filename: str) -> dict:
    """
    Inspect a downloaded MapCP boundary and export a boundary-only GeoPackage.

    This first version checks one polygon feature, CRS, geometry validity,
    extent, and projected acreage. It does not inspect imagery or vegetation
    coverage. Accept only a GeoJSON filename in the project's outputs folder.
    """
    if not re.fullmatch(
        r"[a-z0-9_]+_\d{8}T\d{12}Z\.geojson",
        boundary_filename,
    ):
        raise ToolError(
            "Use the exact generated GeoJSON filename only, not a full path."
        )

    folder = OUTPUT_FOLDER.resolve()
    boundary_path = (folder / boundary_filename).resolve()

    if boundary_path.parent != folder:
        raise ToolError("Boundary must remain inside the outputs folder.")

    if not boundary_path.is_file():
        raise ToolError("That boundary file was not found in outputs.")

    if boundary_path.stat().st_size > MAX_RESPONSE_BYTES:
        raise ToolError("Boundary exceeds this test's 5 MB size limit.")

    try:
        boundary = gpd.read_file(boundary_path)
    except Exception as error:
        return {
            "status": "failed",
            "stage": "read_boundary",
            "error": str(error),
        }

    if len(boundary) != 1:
        raise ToolError("This test requires exactly one boundary feature.")

    if boundary.crs is None:
        raise ToolError("Boundary CRS is missing; do not guess it.")

    geometry = boundary.geometry.iloc[0]

    if geometry is None or geometry.is_empty:
        raise ToolError("Boundary geometry is missing or empty.")

    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ToolError("Boundary must be Polygon or MultiPolygon.")

    if not geometry.is_valid:
        return {
            "status": "review_required",
            "stage": "geometry_validation",
            "reason": explain_validity(geometry),
            "message": "No automatic geometry repair was performed.",
        }

    lonlat = boundary.to_crs(epsg=4326)
    west, south, east, north = map(float, lonlat.total_bounds)

    if not all(math.isfinite(v) for v in [west, south, east, north]):
        raise ToolError("Boundary contains invalid coordinate bounds.")

    if not (
        -125 <= west <= east <= -66
        and 24 <= south <= north <= 50
    ):
        raise ToolError(
            "Boundary is outside this prototype's lower-48 test extent. "
            "A region-appropriate area method must be selected."
        )

    projected = boundary.to_crs(epsg=5070)
    area_m2 = float(projected.geometry.area.iloc[0])

    if not math.isfinite(area_m2) or area_m2 <= 0:
        raise ToolError("Calculated area is not a positive finite value.")

    acres = area_m2 / 4046.8564224
    projected["mapcp_acres"] = acres

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stem = f"{boundary_path.stem}_inspection_{run_id}"
    gpkg_path = folder / f"{stem}.gpkg"
    report_path = folder / f"{stem}_qc.json"
    source_manifest = boundary_path.with_name(
        f"{boundary_path.stem}_source.json"
    )

    warnings = [
        "Geometry checks do not establish boundary authority or suitability.",
        "Imagery and vegetation coverage have not been inspected.",
        "No forest/nonforest or candidate cover-type mapping exists yet.",
        "Professional forestry and GIS review is required.",
    ]

    if not source_manifest.is_file():
        warnings.append("The associated source manifest is missing.")

    report = {
        "status": "boundary_checks_passed_review_required",
        "input_boundary": str(boundary_path),
        "source_manifest": (
            str(source_manifest) if source_manifest.is_file() else None
        ),
        "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
        "feature_count": len(boundary),
        "geometry_type": geometry.geom_type,
        "geometry_valid": True,
        "input_crs": boundary.crs.to_string(),
        "area_crs": "EPSG:5070",
        "area_method": "Planar area in Conus Albers equal-area projection",
        "square_meters_per_acre": 4046.8564224,
        "boundary_acres": acres,
        "bounds_lonlat": [west, south, east, north],
        "boundary_geopackage": str(gpkg_path),
        "geopackage_layer": "public_reference_boundary",
        "qc_report": str(report_path),
        "software": {"geopandas": gpd.__version__},
        "review_flags": warnings,
    }

    try:
        projected.to_file(
            gpkg_path,
            layer="public_reference_boundary",
            driver="GPKG",
            engine="pyogrio",
            index=False,
        )
        report_path.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
    except Exception as error:
        return {
            "status": "failed",
            "stage": "write_outputs",
            "error": str(error),
            "message": "Check outputs for incomplete files before using them.",
        }

    return report

NAIP_IMAGE_SERVICE = (
    "https://apps.geo.fpac.usda.gov/geo-imagery/rest/services/"
    "naip/conus_naip/ImageServer"
)

MAX_NAIP_CATALOG_ITEMS = 20


def _read_naip_json(endpoint: str, params: dict) -> dict:
    """
    Read an allowlisted USDA NAIP REST endpoint with bounded retries.

    This helper accepts only endpoint suffixes supplied by this module,
    not user-provided URLs.
    """
    for attempt in range(2):
        try:
            with httpx.Client(
                timeout=30.0,
                follow_redirects=False,
            ) as client:
                response = client.get(
                    f"{NAIP_IMAGE_SERVICE}{endpoint}",
                    params=params,
                )
                response.raise_for_status()

                if response.is_redirect:
                    raise ToolError(
                        "NAIP source redirected; refusing to follow an "
                        "unreviewed URL."
                    )

                if len(response.content) > MAX_RESPONSE_BYTES:
                    raise ToolError(
                        "NAIP service response exceeded the 5 MB test limit."
                    )

                return response.json()

        except httpx.TransportError:
            if attempt == 1:
                raise
            time.sleep(1)

    raise ToolError("NAIP request did not complete.")


@mcp.tool()
def inspect_naip_coverage(boundary_filename: str) -> dict:
    """
    Inspect public USDA NAIP imagery service metadata and catalog overlap for
    one validated MapCP boundary.

    This tool retrieves no imagery pixels. It reports service metadata and a
    bounded set of imagery catalog items intersecting the boundary envelope.
    Catalog overlap does not prove complete boundary coverage or a single
    uniform image acquisition date.
    """
    if not re.fullmatch(
        r"[a-z0-9_]+_\d{8}T\d{12}Z\.geojson",
        boundary_filename,
    ):
        raise ToolError(
            "Use the generated boundary GeoJSON filename only, not a full path."
        )

    folder = OUTPUT_FOLDER.resolve()
    boundary_path = (folder / boundary_filename).resolve()

    if boundary_path.parent != folder:
        raise ToolError("Boundary must remain inside the outputs folder.")

    if not boundary_path.is_file():
        raise ToolError("Boundary GeoJSON was not found in outputs.")

    try:
        boundary = gpd.read_file(boundary_path)
    except Exception as error:
        return {
            "status": "failed",
            "stage": "read_boundary",
            "error": str(error),
        }

    if len(boundary) != 1:
        raise ToolError("This test requires exactly one boundary feature.")

    if boundary.crs is None:
        raise ToolError("Boundary CRS is missing; do not guess it.")

    geometry = boundary.geometry.iloc[0]

    if geometry is None or geometry.is_empty:
        raise ToolError("Boundary geometry is missing or empty.")

    if not geometry.is_valid:
        raise ToolError(
            "Boundary geometry is invalid. Inspect or repair it before "
            "checking imagery coverage."
        )

    lonlat = boundary.to_crs(epsg=4326)
    west, south, east, north = map(float, lonlat.total_bounds)

    if not all(math.isfinite(value) for value in [west, south, east, north]):
        raise ToolError("Boundary has invalid geographic bounds.")

    if not (
        -125 <= west <= east <= -66
        and 24 <= south <= north <= 50
    ):
        raise ToolError(
            "Boundary is outside this first NAIP-CONUS test extent."
        )

    envelope = {
        "xmin": west,
        "ymin": south,
        "xmax": east,
        "ymax": north,
        "spatialReference": {"wkid": 4326},
    }

    try:
        service_info = _read_naip_json(
            "",
            {
                "f": "json",
            },
        )

        identify_result = _read_naip_json(
            "/identify",
            {
                "f": "json",
                "geometry": json.dumps(envelope),
                "geometryType": "esriGeometryEnvelope",
                "sr": "4326",
                "returnCatalogItems": "true",
                "returnGeometry": "false",
                "returnPixelValues": "false",
                "maxItemCount": str(MAX_NAIP_CATALOG_ITEMS),
            },
        )

    except (httpx.HTTPError, ToolError, ValueError) as error:
        return {
            "status": "source_failed",
            "source": NAIP_IMAGE_SERVICE,
            "error": str(error),
            "imagery_downloaded": False,
        }

    if "error" in service_info:
        return {
            "status": "source_failed",
            "source": NAIP_IMAGE_SERVICE,
            "error": service_info["error"],
            "imagery_downloaded": False,
        }

    if "error" in identify_result:
        return {
            "status": "source_failed",
            "source": NAIP_IMAGE_SERVICE,
            "error": identify_result["error"],
            "imagery_downloaded": False,
        }

    catalog_items = identify_result.get("catalogItems") or {}
    catalog_features = catalog_items.get("features") or []

    candidate_items = []

    for feature in catalog_features:
        attributes = feature.get("attributes") or {}

        name = (
            attributes.get("Name")
            or attributes.get("NAME")
            or attributes.get("Raster")
            or attributes.get("RASTER")
        )

        parsed_date = None

        if isinstance(name, str):
            match = re.search(r"_(\d{8})$", name)

            if match:
                raw_date = match.group(1)

                try:
                    parsed_date = datetime.strptime(
                        raw_date,
                        "%Y%m%d",
                    ).date().isoformat()
                except ValueError:
                    parsed_date = None

        candidate_items.append(
            {
                "object_id": (
                    attributes.get("OBJECTID")
                    or attributes.get("ObjectID")
                    or attributes.get("objectid")
                ),
                "name": name,
                "acquisition_date_from_source_field": (
                    attributes.get("AcquisitionDate")
                    or attributes.get("ACQUISITIONDATE")
                    or attributes.get("AcqDate")
                    or attributes.get("ACQDATE")
                    or attributes.get("Date")
                    or attributes.get("DATE")
                ),
                "date_parsed_from_catalog_name": parsed_date,
            }
        )

    source_manifest = boundary_path.with_name(
        f"{boundary_path.stem}_source.json"
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_path = (
        OUTPUT_FOLDER
        / f"{boundary_path.stem}_naip_coverage_{run_id}.json"
    )

    review_flags = [
        "No NAIP imagery pixels were downloaded by this coverage inspection.",
        "Catalog overlap with the boundary envelope does not prove complete polygon coverage.",
        "Catalog-name dates are parsed from tile names when available and are not a substitute for a documented source acquisition-date attribute.",
        "Image service metadata does not establish suitability for forest classification.",
        "Professional forestry and GIS review is required before interpretation.",
    ]

    if not candidate_items:
        review_flags.append(
            "No imagery catalog items were returned for the boundary envelope."
        )

    if len(candidate_items) >= MAX_NAIP_CATALOG_ITEMS:
        review_flags.append(
            "Catalog item count reached the response limit; additional "
            "overlapping imagery may exist."
        )

    report = {
        "status": (
            "coverage_candidates_found_review_required"
            if candidate_items
            else "no_catalog_items_returned_review_required"
        ),
        "boundary_input": str(boundary_path),
        "boundary_source_manifest": (
            str(source_manifest) if source_manifest.is_file() else None
        ),
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_agency": (
            "USDA Farm Production and Conservation Business Center"
        ),
        "source_service": NAIP_IMAGE_SERVICE,
        "source_service_description": service_info.get("description"),
        "service_spatial_reference": service_info.get("spatialReference"),
        "service_pixel_size_x": service_info.get("pixelSizeX"),
        "service_pixel_size_y": service_info.get("pixelSizeY"),
        "service_band_count": service_info.get("bandCount"),
        "service_max_image_width": service_info.get("maxImageWidth"),
        "service_max_image_height": service_info.get("maxImageHeight"),
        "boundary_bounds_lonlat": [west, south, east, north],
        "catalog_item_limit": MAX_NAIP_CATALOG_ITEMS,
        "catalog_items_returned": len(candidate_items),
        "catalog_candidates": candidate_items,
        "imagery_downloaded": False,
        "review_flags": review_flags,
        "limitations": [
            "This tool inspects service metadata and catalog overlap only.",
            "It does not download, mosaick, visually inspect, or classify imagery.",
            "It does not determine forest/nonforest, cover type, disturbance, or stand boundaries.",
            "It does not establish ownership, trust status, jurisdiction, legal access, or forestry management authority.",
        ],
    }

    report_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    report["coverage_report"] = str(report_path)

    return report

NAIP_SAMPLE_SIZE_METERS = 1_000
NAIP_SAMPLE_PIXEL_SIZE_METERS = 1
NAIP_SAMPLE_PIXEL_WIDTH = (
    NAIP_SAMPLE_SIZE_METERS // NAIP_SAMPLE_PIXEL_SIZE_METERS
)
NAIP_SAMPLE_PIXEL_HEIGHT = (
    NAIP_SAMPLE_SIZE_METERS // NAIP_SAMPLE_PIXEL_SIZE_METERS
)
MAX_NAIP_SAMPLE_BYTES = 50_000_000


@mcp.tool()
def download_naip_review_sample(
    boundary_filename: str,
    sample_strategy: Literal[
        "interior_representative"
    ] = "interior_representative",
) -> dict:
    """
    Download one automatically selected 1 km by 1 km, four-band USDA NAIP
    review sample from a validated MapCP boundary.

    The interior_representative strategy erodes the boundary inward by half
    the sample width, chooses a point guaranteed to lie inside the remaining
    usable area, then confirms the full sample square remains inside the
    original boundary.

    This creates a preliminary visual-review artifact only. It does not
    classify forest, establish a final project boundary, validate imagery
    acquisition date, or replace professional forestry/GIS review.
    """
    if not re.fullmatch(
        r"[a-z0-9_]+_\d{8}T\d{12}Z\.geojson",
        boundary_filename,
    ):
        raise ToolError(
            "Use the generated boundary GeoJSON filename only, not a full path."
        )

    if sample_strategy != "interior_representative":
        raise ToolError(
            "Only sample_strategy='interior_representative' is supported."
        )

    folder = OUTPUT_FOLDER.resolve()
    boundary_path = (folder / boundary_filename).resolve()

    if boundary_path.parent != folder:
        raise ToolError("Boundary must remain inside the outputs folder.")

    if not boundary_path.is_file():
        raise ToolError("Boundary GeoJSON was not found in outputs.")

    try:
        boundary = gpd.read_file(boundary_path)
    except Exception as error:
        return {
            "status": "failed",
            "stage": "read_boundary",
            "error": str(error),
            "imagery_downloaded": False,
        }

    if len(boundary) != 1:
        raise ToolError("This test requires exactly one boundary feature.")

    if boundary.crs is None:
        raise ToolError("Boundary CRS is missing; do not guess it.")

    original_geometry = boundary.geometry.iloc[0]

    if original_geometry is None or original_geometry.is_empty:
        raise ToolError("Boundary geometry is missing or empty.")

    if not original_geometry.is_valid:
        raise ToolError(
            "Boundary geometry is invalid. Inspect or repair it before "
            "requesting a NAIP sample."
        )

    boundary_5070 = boundary.to_crs(epsg=5070)
    original_5070 = boundary_5070.geometry.iloc[0]
    half_size = NAIP_SAMPLE_SIZE_METERS / 2

    # Account for the distance from the square's center to its corners.
    inward_buffer_meters = math.hypot(half_size, half_size) + 1.0
    usable_geometry = original_5070.buffer(-inward_buffer_meters)

    if usable_geometry.is_empty:
        return {
            "status": "review_required",
            "stage": "select_interior_sample",
            "message": (
                 "No usable interior remains after buffering for the sample's "
                 "corner clearance. A smaller sample or reviewed location is required."
            ),
            "imagery_downloaded": False,
        }

    if not usable_geometry.is_valid:
        return {
            "status": "review_required",
            "stage": "select_interior_sample",
            "message": (
                "The inward-buffered usable area is invalid. No automatic "
                "sample point was selected."
            ),
            "imagery_downloaded": False,
        }

    sample_center_5070 = usable_geometry.representative_point()

    sample_square_5070 = box(
        sample_center_5070.x - half_size,
        sample_center_5070.y - half_size,
        sample_center_5070.x + half_size,
        sample_center_5070.y + half_size,
    )

    if not original_5070.covers(sample_square_5070):
        return {
            "status": "review_required",
            "stage": "select_interior_sample",
            "message": (
                "The automatically selected 1 km sample square is not fully "
                "contained in the original boundary."
            ),
            "imagery_downloaded": False,
        }

    sample_center_lonlat = gpd.GeoSeries(
        [sample_center_5070],
        crs="EPSG:5070",
    ).to_crs(epsg=4326).iloc[0]

    sample_square_lonlat = gpd.GeoSeries(
        [sample_square_5070],
        crs="EPSG:5070",
    ).to_crs(epsg=4326).iloc[0]

    west, south, east, north = map(
        float,
        sample_square_lonlat.bounds,
    )

    if not all(
        math.isfinite(value)
        for value in [west, south, east, north]
    ):
        raise ToolError("Automatically selected sample has invalid bounds.")

    xmin, ymin, xmax, ymax = map(float, sample_square_5070.bounds)

    requested_bounds_5070 = [xmin, ymin, xmax, ymax]
    bbox = ",".join(str(value) for value in requested_bounds_5070)

    export_params = {
        "f": "image",
        "bbox": bbox,
        "bboxSR": "5070",
        "imageSR": "5070",
        "size": (
            f"{NAIP_SAMPLE_PIXEL_WIDTH},"
            f"{NAIP_SAMPLE_PIXEL_HEIGHT}"
        ),
        "format": "tiff",
        "pixelType": "U8",
        "interpolation": "RSP_BilinearInterpolation",
        "returnSquarePixels": "true",
    }

    try:
        with httpx.Client(
            timeout=90.0,
            follow_redirects=False,
        ) as client:
            response = client.get(
                f"{NAIP_IMAGE_SERVICE}/exportImage",
                params=export_params,
            )
            response.raise_for_status()

            if response.is_redirect:
                raise ToolError(
                    "NAIP source redirected; refusing to follow an "
                    "unreviewed URL."
                )

            if len(response.content) > MAX_NAIP_SAMPLE_BYTES:
                raise ToolError(
                    "NAIP review sample exceeded the 50 MB safety limit."
                )

            content_type = response.headers.get(
                "content-type",
                "",
            ).lower()

            if "json" in content_type:
                data = response.json()

                if "error" in data:
                    raise ToolError(
                        f"NAIP export failed: {data['error']}"
                    )

                raise ToolError(
                    "NAIP export returned JSON instead of a TIFF image."
                )

            image_bytes = response.content

    except (httpx.HTTPError, ToolError, ValueError) as error:
        return {
            "status": "source_failed",
            "source": NAIP_IMAGE_SERVICE,
            "error": str(error),
            "imagery_downloaded": False,
        }

    try:
        with rasterio.open(BytesIO(image_bytes)) as source:
            band_count = source.count
            source_transform = source.transform
            source_crs = (
                source.crs.to_string() if source.crs else None
            )
            source_bounds = [
                float(source.bounds.left),
                float(source.bounds.bottom),
                float(source.bounds.right),
                float(source.bounds.top),
            ]
            source_resolution = [
                abs(float(source.res[0])),
                abs(float(source.res[1])),
            ]
            source_width = source.width
            source_height = source.height
            source_dtype = source.dtypes[0]
    except Exception as error:
        return {
            "status": "failed",
            "stage": "validate_downloaded_tiff",
            "error": str(error),
            "imagery_downloaded": False,
        }

    if band_count != 4:
        return {
            "status": "review_required",
            "stage": "validate_downloaded_tiff",
            "message": (
                f"Expected four NAIP bands but received {band_count}. "
                "The sample was not saved."
            ),
            "imagery_downloaded": False,
        }

    validation_errors = []

    if source_crs is None:
            validation_errors.append("Downloaded TIFF has no CRS.")
    elif (
            rasterio.crs.CRS.from_user_input(source_crs)
            != rasterio.crs.CRS.from_epsg(5070)
    ):
        validation_errors.append(
            f"Expected EPSG:5070 but received {source_crs}."
    )

    if (
            source_width != NAIP_SAMPLE_PIXEL_WIDTH
            or source_height != NAIP_SAMPLE_PIXEL_HEIGHT
    ):
            validation_errors.append(
                f"Unexpected dimensions: {source_width} x {source_height}."
            )

    if not all(
        math.isclose(
            value,
            NAIP_SAMPLE_PIXEL_SIZE_METERS,
            rel_tol=0,
            abs_tol=0.000001,
        )
        for value in source_resolution
    ):
        validation_errors.append(
            f"Unexpected projected pixel spacing: {source_resolution}."
        )

    if (
        abs(source_transform.b) > 0.000001
        or abs(source_transform.d) > 0.000001
        or source_transform.a <= 0
        or source_transform.e >= 0
    ):
        validation_errors.append(
            "Expected a north-up raster without rotation."
        )

    if not all(
        math.isclose(
            actual,
            requested,
            rel_tol=0,
            abs_tol=0.01,
        )
        for actual, requested in zip(
            source_bounds,
            requested_bounds_5070,
        )
    ):
        validation_errors.append(
            "Returned extent differs from the requested square by more "
            "than the 0.01-meter comparison tolerance."
        )

    if not original_5070.covers(box(*source_bounds)):
        validation_errors.append(
            "Returned raster extent is not fully inside the boundary."
        )

    if validation_errors:
        return {
            "status": "review_required",
            "stage": "validate_downloaded_tiff",
            "validation_errors": validation_errors,
            "requested_bounds_epsg_5070": requested_bounds_5070,
            "returned_bounds_epsg_5070": source_bounds,
            "returned_crs": source_crs,
            "imagery_downloaded": True,
            "sample_saved": False,
        }

    timestamp = datetime.now(timezone.utc)
    run_id = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
    stem = f"{boundary_path.stem}_naip_sample_{run_id}"
    tiff_path = OUTPUT_FOLDER / f"{stem}.tif"
    manifest_path = OUTPUT_FOLDER / f"{stem}_source.json"

    tiff_path.write_bytes(image_bytes)

    limitations = [
        "This is one automatically selected 1 km by 1 km review sample, "
        "not full-boundary imagery.",
        "An interior location is geometrically safe but not necessarily "
        "ecologically representative of the full boundary.",
        "The sample is exported from a mosaic service; catalog-source date "
        "and tile lineage for these pixels have not been independently verified.",
        "No forest/nonforest or cover-type classification was performed.",
        "Imagery alone does not establish forest condition, stand composition, "
        "ownership, trust status, access, or management authority.",
        "Professional forestry and GIS review is required.",
    ]

    manifest = {
        "status": "downloaded_requires_review",
        "source_agency": (
            "USDA Farm Production and Conservation Business Center"
        ),
        "source_service": NAIP_IMAGE_SERVICE,
        "downloaded_at_utc": timestamp.isoformat(),
        "boundary_input": str(boundary_path),
        "sample_strategy": sample_strategy,
        "sample_selection_method": (
            "Boundary projected to EPSG:5070; inward buffer based on the "
            "sample half-diagonal plus a 1-meter margin; representative point "
            "selected; requested square and returned raster bounds checked "
            "for containment in the original boundary."
        ),
        "sample_center_epsg_5070": [
            float(sample_center_5070.x),
            float(sample_center_5070.y),
        ],
        "sample_center_lonlat": [
            float(sample_center_lonlat.x),
            float(sample_center_lonlat.y),
        ],
        "sample_size_meters": NAIP_SAMPLE_SIZE_METERS,
        "inward_buffer_meters": inward_buffer_meters,
        "requested_output_pixel_size_meters": (
            NAIP_SAMPLE_PIXEL_SIZE_METERS
        ),
        "requested_output_size_pixels": [
            NAIP_SAMPLE_PIXEL_WIDTH,
            NAIP_SAMPLE_PIXEL_HEIGHT,
        ],
        "requested_bbox_crs": "EPSG:5070",
        "requested_bbox_epsg_5070": requested_bounds_5070,
        "reference_envelope_lonlat": [west, south, east, north],
        "grid_validation_passed": True,
        "returned_footprint_within_boundary": True,
        "export_parameters": export_params,
        "downloaded_file": str(tiff_path),
        "downloaded_file_bytes": len(image_bytes),
        "downloaded_tiff": {
            "band_count": band_count,
            "crs": source_crs,
            "bounds": source_bounds,
            "resolution": source_resolution,
            "width": source_width,
            "height": source_height,
            "data_type": source_dtype,
        },
        "limitations": limitations,
    }

    manifest_path.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    return {
        "status": "downloaded_requires_review",
        "naip_review_sample": str(tiff_path),
        "source_manifest": str(manifest_path),
        "sample_strategy": sample_strategy,
        "sample_center_lonlat": [
            float(sample_center_lonlat.x),
            float(sample_center_lonlat.y),
        ],
        "requested_sample_size_meters": NAIP_SAMPLE_SIZE_METERS,
        "requested_bounds_epsg_5070": requested_bounds_5070,
        "downloaded_file_bytes": len(image_bytes),
        "band_count": band_count,
        "downloaded_tiff_crs": source_crs,
        "downloaded_tiff_resolution": source_resolution,
        "downloaded_tiff_dimensions": [
            source_width,
            source_height,
        ],
        "grid_validation_passed": True,
        "returned_footprint_within_boundary": True,
        "review_flags": limitations,
    }

LANDFIRE_LFPS_ROOT = "https://lfps.usgs.gov"
LANDFIRE_LFPS_REST_SERVICE = (
    "https://lfps.usgs.gov/arcgis/rest/services/"
    "LandfireProductService/GPServer"
)


def _read_landfire_json(url: str, params: dict) -> dict:
    """
    Read an allowlisted LANDFIRE LFPS endpoint with bounded retries.

    The caller supplies only fixed LANDFIRE service URLs defined in this
    module. User input never controls a request URL.
    """
    for attempt in range(2):
        try:
            with httpx.Client(
                timeout=30.0,
                follow_redirects=False,
            ) as client:
                response = client.get(
                    url,
                    params=params,
                )
                response.raise_for_status()

                if response.is_redirect:
                    raise ToolError(
                        "LANDFIRE service redirected; refusing to follow an "
                        "unreviewed URL."
                    )

                if len(response.content) > MAX_RESPONSE_BYTES:
                    raise ToolError(
                        "LANDFIRE metadata response exceeded the 5 MB limit."
                    )

                return response.json()

        except httpx.TransportError:
            if attempt == 1:
                raise
            time.sleep(1)

    raise ToolError("LANDFIRE metadata request did not complete.")


# Legacy/developer-only: retained but not exposed through MCP.
# @mcp.tool()
def inspect_vegetation_inputs(boundary_filename: str) -> dict:
    """
    Inspect planned LANDFIRE vegetation and disturbance inputs for one
    validated MapCP boundary before any raster download or classification.

    This tool checks boundary extent and LANDFIRE Product Service availability,
    writes an input-inspection report, and identifies the planned roles of
    EVT, EVC, EVH, and a future disturbance source.

    It does not download LANDFIRE, LCMS, or imagery pixels. It does not
    establish forest/nonforest, cover type, disturbance status, or stand
    boundaries.
    """
    if not re.fullmatch(
        r"[a-z0-9_]+_\d{8}T\d{12}Z\.geojson",
        boundary_filename,
    ):
        raise ToolError(
            "Use the generated boundary GeoJSON filename only, not a full path."
        )

    folder = OUTPUT_FOLDER.resolve()
    boundary_path = (folder / boundary_filename).resolve()

    if boundary_path.parent != folder:
        raise ToolError("Boundary must remain inside the outputs folder.")

    if not boundary_path.is_file():
        raise ToolError("Boundary GeoJSON was not found in outputs.")

    try:
        boundary = gpd.read_file(boundary_path)
    except Exception as error:
        return {
            "status": "failed",
            "stage": "read_boundary",
            "error": str(error),
        }

    if len(boundary) != 1:
        raise ToolError("This test requires exactly one boundary feature.")

    if boundary.crs is None:
        raise ToolError("Boundary CRS is missing; do not guess it.")

    geometry = boundary.geometry.iloc[0]

    if geometry is None or geometry.is_empty:
        raise ToolError("Boundary geometry is missing or empty.")

    if not geometry.is_valid:
        raise ToolError(
            "Boundary geometry is invalid. Inspect or repair it before "
            "checking vegetation inputs."
        )

    lonlat = boundary.to_crs(epsg=4326)
    west, south, east, north = map(float, lonlat.total_bounds)

    if not all(math.isfinite(value) for value in [west, south, east, north]):
        raise ToolError("Boundary has invalid geographic bounds.")

    if not (
        -125 <= west <= east <= -66
        and 24 <= south <= north <= 50
    ):
        raise ToolError(
            "Boundary is outside this first CONUS LANDFIRE workflow scope."
        )

    boundary_acres = float(
        boundary.to_crs(epsg=5070).geometry.area.iloc[0]
        / 4046.8564224
    )

    try:
        lfps_metadata = _read_landfire_json(
            LANDFIRE_LFPS_REST_SERVICE,
            {
                "f": "json",
            },
        )
    except (httpx.HTTPError, ToolError, ValueError) as error:
        return {
            "status": "source_failed",
            "source": LANDFIRE_LFPS_REST_SERVICE,
            "error": str(error),
            "rasters_downloaded": False,
        }

    if "error" in lfps_metadata:
        return {
            "status": "source_failed",
            "source": LANDFIRE_LFPS_REST_SERVICE,
            "error": lfps_metadata["error"],
            "rasters_downloaded": False,
        }

    source_manifest = boundary_path.with_name(
        f"{boundary_path.stem}_source.json"
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_path = (
        OUTPUT_FOLDER
        / f"{boundary_path.stem}_vegetation_inputs_{run_id}.json"
    )

    planned_inputs = [
        {
            "source": "LANDFIRE",
            "product_family": "Existing Vegetation Type",
            "abbreviation": "EVT",
            "planned_role": (
                "Broad candidate vegetation and cover-type evidence; "
                "not a final stand or inventory label."
            ),
            "downloaded": False,
            "layer_identifier_confirmed": False,
        },
        {
            "source": "LANDFIRE",
            "product_family": "Existing Vegetation Cover",
            "abbreviation": "EVC",
            "planned_role": (
                "Canopy-cover evidence for broad forest, woodland, shrub, "
                "and low-cover review."
            ),
            "downloaded": False,
            "layer_identifier_confirmed": False,
        },
        {
            "source": "LANDFIRE",
            "product_family": "Existing Vegetation Height",
            "abbreviation": "EVH",
            "planned_role": (
                "Dominant-height evidence for broad vegetation-structure "
                "review."
            ),
            "downloaded": False,
            "layer_identifier_confirmed": False,
        },
        {
            "source": "LCMS or LANDFIRE disturbance product",
            "product_family": "Disturbance/change",
            "abbreviation": "TBD",
            "planned_role": (
                "Flag possible recent disturbance or conflicts with "
                "vegetation products before cover-type review."
            ),
            "downloaded": False,
            "layer_identifier_confirmed": False,
        },
    ]

    review_flags = [
        "No LANDFIRE vegetation rasters were downloaded.",
        "No disturbance raster was downloaded.",
        "LFPS service availability does not confirm currently valid product codes.",
        "Product versions, layer identifiers, crosswalks, thresholds, and "
        "minimum mapping unit require explicit review before classification.",
        "LANDFIRE vegetation products are modeled products, not field "
        "inventory measurements or final stand labels.",
        "Public source availability does not establish suitability for a "
        "specific forestry project.",
        "Professional forestry and GIS review is required.",
    ]

    report = {
        "status": "inputs_identified_requires_product_selection",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "boundary_input": str(boundary_path),
        "boundary_source_manifest": (
            str(source_manifest) if source_manifest.is_file() else None
        ),
        "boundary_bounds_lonlat": [west, south, east, north],
        "boundary_acres": boundary_acres,
        "workflow_scope": "CONUS only for this initial implementation",
        "landfire_product_service": {
            "service_root": LANDFIRE_LFPS_ROOT,
            "rest_service": LANDFIRE_LFPS_REST_SERVICE,
            "service_description": lfps_metadata.get("serviceDescription"),
            "execution_type": lfps_metadata.get("executionType"),
            "tasks": lfps_metadata.get("tasks"),
        },
        "planned_inputs": planned_inputs,
        "rasters_downloaded": False,
        "classification_performed": False,
        "review_flags": review_flags,
        "limitations": [
            "This is source and boundary inspection only.",
            "It does not retrieve, resample, mosaic, or analyze vegetation "
            "or disturbance rasters.",
            "It does not determine candidate forest land, cover types, "
            "disturbance condition, stands, accessibility, or inventory strata.",
            "It does not establish ownership, trust status, jurisdiction, "
            "legal access, management authority, or forestry approval.",
        ],
    }

    report_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    report["input_inspection_report"] = str(report_path)

    return report

LANDFIRE_LFPS_TASK = (
    f"{LANDFIRE_LFPS_REST_SERVICE}/LandfireProductService"
)


# Legacy/developer-only: retained but not exposed through MCP.
# @mcp.tool()
def inspect_landfire_task_schema() -> dict:
    """
    Inspect the published LANDFIRE Product Service task parameter schema.

    Use before implementing an LFPS job request. Returns published input and
    output parameter names, data types, defaults, and choice lists when
    provided. Saves the complete task metadata for reproducible review.

    This tool does not submit a job, download rasters, verify product coverage,
    or approve classification definitions. Task metadata may not contain the
    full product catalog or processing limits.
    """
    checked_at = datetime.now(timezone.utc)

    try:
        metadata = _read_landfire_json(
            LANDFIRE_LFPS_TASK,
            {"f": "json"},
        )
    except (httpx.HTTPError, ToolError, ValueError) as error:
        return {
            "status": "source_failed",
            "stage": "read_task_metadata",
            "source": LANDFIRE_LFPS_TASK,
            "checked_at_utc": checked_at.isoformat(),
            "error": str(error),
            "job_submitted": False,
        }

    if not isinstance(metadata, dict):
        return {
            "status": "unexpected_source_response",
            "source": LANDFIRE_LFPS_TASK,
            "message": "Expected a JSON object containing task metadata.",
            "job_submitted": False,
        }

    if "error" in metadata:
        return {
            "status": "source_failed",
            "source": LANDFIRE_LFPS_TASK,
            "checked_at_utc": checked_at.isoformat(),
            "error": metadata["error"],
            "job_submitted": False,
        }

    parameters = metadata.get("parameters")

    if not isinstance(parameters, list) or not parameters:
        return {
            "status": "schema_unavailable",
            "source": LANDFIRE_LFPS_TASK,
            "message": "No nonempty parameter list was published.",
            "response_keys": list(metadata.keys()),
            "job_submitted": False,
        }

    if any(not isinstance(item, dict) for item in parameters):
        return {
            "status": "unexpected_parameter_schema",
            "source": LANDFIRE_LFPS_TASK,
            "message": "Parameter entries must be JSON objects.",
            "job_submitted": False,
        }

    summaries = []

    for parameter in parameters:
        choices = parameter.get("choiceList")
        published_choices = choices if isinstance(choices, list) else None

        summaries.append({
            "name": parameter.get("name"),
            "display_name": parameter.get("displayName"),
            "direction": parameter.get("direction"),
            "data_type": parameter.get("dataType"),
            "parameter_type": parameter.get("parameterType"),
            "required": (
                parameter.get("parameterType") == "esriGPParameterTypeRequired"
            ),
            "default_value": parameter.get("defaultValue"),
            "description": parameter.get("description"),
            "choice_list_published": published_choices is not None,
            "choice_count": (
                len(published_choices) if published_choices is not None else None
            ),
            "choice_preview": (
                published_choices[:40] if published_choices is not None else None
            ),
        })

    inputs = [
        item for item in summaries
        if item["direction"] == "esriGPParameterDirectionInput"
    ]
    outputs = [
        item for item in summaries
        if item["direction"] == "esriGPParameterDirectionOutput"
    ]
    other_parameters = [
        item for item in summaries
        if item["direction"] not in {
            "esriGPParameterDirectionInput",
            "esriGPParameterDirectionOutput",
        }
    ]

    run_id = checked_at.strftime("%Y%m%dT%H%M%S%fZ")
    OUTPUT_FOLDER.mkdir(exist_ok=True)

    raw_path = OUTPUT_FOLDER / f"landfire_task_schema_{run_id}_raw.json"
    report_path = OUTPUT_FOLDER / f"landfire_task_schema_{run_id}_report.json"

    report = {
        "status": "task_schema_retrieved_requires_review",
        "checked_at_utc": checked_at.isoformat(),
        "source_task": LANDFIRE_LFPS_TASK,
        "task_name": metadata.get("name"),
        "task_display_name": metadata.get("displayName"),
        "task_description": metadata.get("description"),
        "execution_type_if_published": metadata.get("executionType"),
        "parameter_count": len(summaries),
        "input_parameters": inputs,
        "output_parameters": outputs,
        "other_parameters": other_parameters,
        "raw_task_metadata": str(raw_path),
        "task_schema_report": str(report_path),
        "job_submitted": False,
        "rasters_downloaded": False,
        "review_flags": [
            "Published parameter names are preserved without renaming.",
            "Choice previews are limited to 40 values; full metadata is saved.",
            "Null metadata means not published, not unrestricted.",
            "A published choice list is not proof of product coverage.",
            "Complete product catalog, versions, and processing limits still "
            "require verification.",
            "No job request or classification rules have been approved.",
        ],
    }

    try:
        raw_path.write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )
        report_path.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        return {
            "status": "failed",
            "stage": "save_schema_report",
            "error": str(error),
            "message": "Check outputs for an incomplete report pair.",
            "job_submitted": False,
        }

    return report

LANDFIRE_LFPS_SUBMIT_JOB = (
    f"{LANDFIRE_LFPS_TASK}/submitJob"
)

LANDFIRE_SAMPLE_LAYERS = (
    "LF2024_EVT;LF2024_EVC;LF2024_EVH"
)

LANDFIRE_SAMPLE_RESOLUTION_METERS = 30
LANDFIRE_SAMPLE_OUTPUT_CRS = "EPSG:5070"

# LFPS v2 constants.
# These are separate from the legacy ArcGIS GPServer constants above.
# Verified from the LFPS v2 Swagger interface and Products table on 2026-10-05.

LANDFIRE_LFPS_V2_BASE_URL = "https://lfps.usgs.gov"

LANDFIRE_LFPS_V2_HEALTH_URL = (
    f"{LANDFIRE_LFPS_V2_BASE_URL}/api/healthCheck"
)

LANDFIRE_LFPS_V2_SUBMIT_URL = (
    f"{LANDFIRE_LFPS_V2_BASE_URL}/api/job/submit"
)

LANDFIRE_LFPS_V2_STATUS_URL = (
    f"{LANDFIRE_LFPS_V2_BASE_URL}/api/job/status"
)

LANDFIRE_LFPS_V2_PRODUCTS_URL = (
    f"{LANDFIRE_LFPS_V2_BASE_URL}/products"
)

# Current LFPS v2 Products-table identifiers for the initial MapCP sample.
LANDFIRE_LFPS_V2_SAMPLE_LAYERS = [
    "LF2025_EVT",
    "LF2025_EVC",
    "LF2025_EVH",
]

LANDFIRE_LFPS_V2_LAYER_LIST = ";".join(
    LANDFIRE_LFPS_V2_SAMPLE_LAYERS
)

# NAD83 / Conus Albers projected output.
LANDFIRE_LFPS_V2_OUTPUT_WKID = 5070

# These are MapCP prototype safety limits, not LANDFIRE service limits.
LANDFIRE_LFPS_V2_MAX_AOI_WIDTH_DEGREES = 0.25
LANDFIRE_LFPS_V2_MAX_AOI_HEIGHT_DEGREES = 0.25

# Bounded LFPS v2 collection limits for the initial MapCP prototype.
LANDFIRE_LFPS_V2_MAX_BUNDLE_BYTES = 100_000_000
LANDFIRE_LFPS_V2_MAX_EXTRACTED_BYTES = 250_000_000
LANDFIRE_LFPS_V2_MAX_ZIP_MEMBERS = 50

LANDFIRE_LFPS_V2_OUTPUT_HOST = "lfps.usgs.gov"
LANDFIRE_LFPS_V2_OUTPUT_PATH_PREFIX = (
    "/arcgis/rest/directories/arcgisjobs/"
    "landfireproductservice_gpserver/"
)

# Legacy/developer-only: retained but not exposed through MCP.
# @mcp.tool()
def prepare_landfire_sample_request(
    naip_manifest_filename: str,
) -> dict:
    """
    Prepare, but do not submit, a matched LANDFIRE vegetation request for a
    validated MapCP NAIP review sample.

    The request uses LF 2024 Existing Vegetation Type, Existing Vegetation
    Cover, and Existing Vegetation Height at 30-meter output resolution.
    It derives the area of interest from the saved NAIP sample manifest.

    This tool submits no remote job, downloads no LANDFIRE raster, and does
    not perform forest/nonforest or cover-type classification.
    """
    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+_naip_sample_\d{8}T\d{12}Z_source\.json",
        naip_manifest_filename,
    ):
        raise ToolError(
            "Use the generated NAIP sample source-manifest filename only, "
            "not a full path."
        )

    folder = OUTPUT_FOLDER.resolve()
    manifest_path = (folder / naip_manifest_filename).resolve()

    if manifest_path.parent != folder:
        raise ToolError("NAIP manifest must remain inside the outputs folder.")

    if not manifest_path.is_file():
        raise ToolError("NAIP sample source manifest was not found in outputs.")

    if manifest_path.stat().st_size > MAX_RESPONSE_BYTES:
        raise ToolError("NAIP source manifest exceeds the 5 MB size limit.")

    try:
        naip_manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        return {
            "status": "failed",
            "stage": "read_naip_manifest",
            "error": str(error),
            "job_submitted": False,
        }

    if not naip_manifest.get("grid_validation_passed"):
        return {
            "status": "review_required",
            "stage": "validate_naip_manifest",
            "message": (
                "The NAIP sample manifest does not show a passed grid "
                "validation. No LANDFIRE request was prepared."
            ),
            "job_submitted": False,
        }

    if not naip_manifest.get("returned_footprint_within_boundary"):
        return {
            "status": "review_required",
            "stage": "validate_naip_manifest",
            "message": (
                "The NAIP sample manifest does not show that the raster "
                "footprint was contained within the boundary."
            ),
            "job_submitted": False,
        }

    requested_crs = naip_manifest.get("requested_bbox_crs")
    sample_bounds_5070 = naip_manifest.get(
        "requested_bbox_epsg_5070"
    )

    if requested_crs != "EPSG:5070":
        return {
            "status": "review_required",
            "stage": "validate_naip_manifest",
            "message": (
                "This first LANDFIRE matcher requires an EPSG:5070 "
                "validated NAIP sample."
            ),
            "job_submitted": False,
        }

    if (
        not isinstance(sample_bounds_5070, list)
        or len(sample_bounds_5070) != 4
        or not all(
            isinstance(value, int | float)
            and math.isfinite(value)
            for value in sample_bounds_5070
        )
    ):
        return {
            "status": "review_required",
            "stage": "validate_naip_manifest",
            "message": (
                "NAIP sample bounds are missing or invalid in the source "
                "manifest."
            ),
            "job_submitted": False,
        }

    xmin, ymin, xmax, ymax = map(float, sample_bounds_5070)

    if not (xmin < xmax and ymin < ymax):
        return {
            "status": "review_required",
            "stage": "validate_naip_manifest",
            "message": "NAIP sample bounds are not a valid extent.",
            "job_submitted": False,
        }

    west, south, east, north = transform_bounds(
        "EPSG:5070",
        "EPSG:4326",
        xmin,
        ymin,
        xmax,
        ymax,
        densify_pts=21,
    )

    if not all(
        math.isfinite(value)
        for value in [west, south, east, north]
    ):
        return {
            "status": "review_required",
            "stage": "transform_aoi",
            "message": "Transformed LANDFIRE AOI contains invalid values.",
            "job_submitted": False,
        }

    if not (
        -125 <= west < east <= -66
        and 24 <= south < north <= 50
    ):
        return {
            "status": "review_required",
            "stage": "transform_aoi",
            "message": (
                "Transformed AOI is outside this initial CONUS workflow."
            ),
            "job_submitted": False,
        }

    aoi_wgs84 = f"{west} {south} {east} {north}"

    submit_parameters = {
        "Layer_List": LANDFIRE_SAMPLE_LAYERS,
        "Include_Layer_List_XML_File": "true",
        "Area_of_Interest": aoi_wgs84,
        "Output_Projection": LANDFIRE_SAMPLE_OUTPUT_CRS,
        "Resample_Resolution": str(
            LANDFIRE_SAMPLE_RESOLUTION_METERS
        ),
        "f": "json",
    }

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    request_path = (
        OUTPUT_FOLDER
        / f"{manifest_path.stem}_landfire_request_{run_id}.json"
    )

    request_record = {
        "status": "request_prepared_requires_submission_approval",
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_task": LANDFIRE_LFPS_TASK,
        "submit_job_endpoint": LANDFIRE_LFPS_SUBMIT_JOB,
        "naip_source_manifest": str(manifest_path),
        "matched_naip_bounds_epsg_5070": sample_bounds_5070,
        "landfire_aoi_wgs84_west_south_east_north": [
            west,
            south,
            east,
            north,
        ],
        "layers_in_requested_band_order": [
            "LF2024_EVT",
            "LF2024_EVC",
            "LF2024_EVH",
        ],
        "submit_parameters": submit_parameters,
        "review_flags": [
            "This request has not been submitted to LANDFIRE.",
            "LFPS output bands must be validated against returned metadata.",
            "Thirty-meter LANDFIRE evidence is not equivalent to the "
            "one-meter NAIP sample.",
            "No forest/nonforest or cover-type classification has occurred.",
            "Professional forestry and GIS review is required.",
        ],
        "limitations": [
            "The WGS84 AOI is the transformed envelope of the validated "
            "EPSG:5070 NAIP square; it is not a polygon clip geometry.",
            "The request does not establish product coverage, raster values, "
            "or output format until LFPS successfully completes a job.",
            "LANDFIRE products are modeled planning evidence, not field "
            "inventory measurements or final stand labels.",
        ],
    }

    request_path.write_text(
        json.dumps(request_record, indent=2),
        encoding="utf-8",
    )

    return {
        "status": "request_prepared_requires_submission_approval",
        "prepared_request": str(request_path),
        "source_task": LANDFIRE_LFPS_TASK,
        "layers_in_requested_band_order": (
            request_record["layers_in_requested_band_order"]
        ),
        "aoi_wgs84_west_south_east_north": (
            request_record[
                "landfire_aoi_wgs84_west_south_east_north"
            ]
        ),
        "output_projection": LANDFIRE_SAMPLE_OUTPUT_CRS,
        "resample_resolution_meters": (
            LANDFIRE_SAMPLE_RESOLUTION_METERS
        ),
        "job_submitted": False,
        "review_flags": request_record["review_flags"],
    }

# Legacy/developer-only: retained but not exposed through MCP.
# @mcp.tool()
def submit_landfire_sample_job(
    prepared_request_filename: str,
) -> dict:
    """
    Submit one previously prepared MapCP LANDFIRE sample request.

    This tool reads a reviewed request record from the outputs folder and
    submits its saved parameters exactly as written to the allowlisted LFPS
    submitJob endpoint. It saves the returned job ID and submission response.

    This tool does not poll job status, download output rasters, or perform
    forest/nonforest or cover-type classification.
    """
    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+_landfire_request_\d{8}T\d{12}Z\.json",
        prepared_request_filename,
    ):
        raise ToolError(
            "Use the generated LANDFIRE prepared-request filename only, "
            "not a full path."
        )

    folder = OUTPUT_FOLDER.resolve()
    request_path = (folder / prepared_request_filename).resolve()

    if request_path.parent != folder:
        raise ToolError(
            "Prepared request must remain inside the outputs folder."
        )

    if not request_path.is_file():
        raise ToolError(
            "Prepared LANDFIRE request was not found in outputs."
        )

    if request_path.stat().st_size > MAX_RESPONSE_BYTES:
        raise ToolError(
            "Prepared LANDFIRE request exceeds the 5 MB size limit."
        )

    try:
        prepared_request = json.loads(
            request_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        return {
            "status": "failed",
            "stage": "read_prepared_request",
            "error": str(error),
            "job_submitted": False,
        }

    if (
        prepared_request.get("status")
        != "request_prepared_requires_submission_approval"
    ):
        return {
            "status": "review_required",
            "stage": "validate_prepared_request",
            "message": (
                "The request file does not have the expected prepared-request "
                "status. No LANDFIRE job was submitted."
            ),
            "job_submitted": False,
        }

    if prepared_request.get("source_task") != LANDFIRE_LFPS_TASK:
        return {
            "status": "review_required",
            "stage": "validate_prepared_request",
            "message": (
                "Prepared request uses an unexpected LANDFIRE task endpoint. "
                "No job was submitted."
            ),
            "job_submitted": False,
        }

    if (
        prepared_request.get("submit_job_endpoint")
        != LANDFIRE_LFPS_SUBMIT_JOB
    ):
        return {
            "status": "review_required",
            "stage": "validate_prepared_request",
            "message": (
                "Prepared request uses an unexpected submitJob endpoint. "
                "No job was submitted."
            ),
            "job_submitted": False,
        }

    expected_layers = [
        "LF2024_EVT",
        "LF2024_EVC",
        "LF2024_EVH",
    ]

    if (
        prepared_request.get("layers_in_requested_band_order")
        != expected_layers
    ):
        return {
            "status": "review_required",
            "stage": "validate_prepared_request",
            "message": (
                "Prepared request layers differ from the approved LF 2024 "
                "EVT/EVC/EVH sample stack. No job was submitted."
            ),
            "job_submitted": False,
        }

    submit_parameters = prepared_request.get("submit_parameters")

    if not isinstance(submit_parameters, dict):
        return {
            "status": "review_required",
            "stage": "validate_prepared_request",
            "message": (
                "Prepared request has no valid submit-parameter dictionary. "
                "No job was submitted."
            ),
            "job_submitted": False,
        }

    expected_layer_list = LANDFIRE_SAMPLE_LAYERS

    if submit_parameters.get("Layer_List") != expected_layer_list:
        return {
            "status": "review_required",
            "stage": "validate_prepared_request",
            "message": (
                "Prepared Layer_List differs from the approved LF 2024 "
                "EVT/EVC/EVH stack. No job was submitted."
            ),
            "job_submitted": False,
        }

    if submit_parameters.get("Output_Projection") != (
        LANDFIRE_SAMPLE_OUTPUT_CRS
    ):
        return {
            "status": "review_required",
            "stage": "validate_prepared_request",
            "message": (
                "Prepared output projection differs from EPSG:5070. "
                "No job was submitted."
            ),
            "job_submitted": False,
        }

    if submit_parameters.get("Resample_Resolution") != str(
        LANDFIRE_SAMPLE_RESOLUTION_METERS
    ):
        return {
            "status": "review_required",
            "stage": "validate_prepared_request",
            "message": (
                "Prepared resolution differs from the approved 30-meter "
                "sample request. No job was submitted."
            ),
            "job_submitted": False,
        }

    aoi = submit_parameters.get("Area_of_Interest")

    if not isinstance(aoi, str):
        return {
            "status": "review_required",
            "stage": "validate_prepared_request",
            "message": (
                "Prepared Area_of_Interest is missing or invalid. "
                "No job was submitted."
            ),
            "job_submitted": False,
        }

    try:
        west, south, east, north = map(float, aoi.split())
    except ValueError:
        return {
            "status": "review_required",
            "stage": "validate_prepared_request",
            "message": (
                "Area_of_Interest must contain W S E N coordinates. "
                "No job was submitted."
            ),
            "job_submitted": False,
        }

    if not (
        all(math.isfinite(value) for value in [west, south, east, north])
        and -125 <= west < east <= -66
        and 24 <= south < north <= 50
    ):
        return {
            "status": "review_required",
            "stage": "validate_prepared_request",
            "message": (
                "Prepared Area_of_Interest is outside the initial CONUS "
                "workflow scope or has invalid bounds. No job was submitted."
            ),
            "job_submitted": False,
        }

    if submit_parameters.get("f") != "json":
        return {
            "status": "review_required",
            "stage": "validate_prepared_request",
            "message": (
                "Prepared request must specify f=json. No job was submitted."
            ),
            "job_submitted": False,
        }

    submitted_at = datetime.now(timezone.utc)

    try:
        with httpx.Client(
            timeout=60.0,
            follow_redirects=False,
        ) as client:
            response = client.post(
                LANDFIRE_LFPS_SUBMIT_JOB,
                data=submit_parameters,
            )
            response.raise_for_status()

            if response.is_redirect:
                raise ToolError(
                    "LANDFIRE service redirected; refusing to follow an "
                    "unreviewed URL."
                )

            if len(response.content) > MAX_RESPONSE_BYTES:
                raise ToolError(
                    "LANDFIRE submitJob response exceeded the 5 MB limit."
                )

            response_content_type = response.headers.get(
                "content-type",
                ""
            )
            response_text = response.text.strip()

            if not response_text:
                return {
                    "status": "source_response_unconfirmed",
                    "stage": "submit_landfire_job",
                    "source": LANDFIRE_LFPS_SUBMIT_JOB,
                    "http_status_code": response.status_code,
                    "response_content_type": response_content_type,
                    "response_body_length_bytes": len(response.content),
                    "message": (
                        "LANDFIRE returned HTTP 200 but no response body. "
                        "MapCP cannot confirm whether a job was created, so "
                        "it did not create a local job manifest and will not "
                        "automatically resubmit."
                    ),
                    "job_submitted": "unknown",
                    "rasters_downloaded": False,
                    "classification_performed": False,
                    "review_flags": [
                        "Check the LANDFIRE service manually before retrying.",
                        "Do not assume an empty HTTP 200 response means the "
                        "request was accepted.",
                        "No local LANDFIRE job ID or job manifest was created.",
                    ],
                }

            try:
                submit_response = response.json()
            except json.JSONDecodeError:
                html_application_shell = (
                    response_content_type.lower().startswith("text/html")
                    and "_next/" in response_text
                )

                if html_application_shell:
                    return {
                        "status": "source_api_version_incompatible",
                        "stage": "submit_landfire_job",
                        "source": LANDFIRE_LFPS_SUBMIT_JOB,
                        "http_status_code": response.status_code,
                        "response_content_type": response_content_type,
                        "response_body_length_bytes": len(response.content),
                        "response_preview": response_text[:1_000],
                        "message": (
                            "The legacy LFPS ArcGIS submitJob route returned the "
                            "LANDFIRE web application HTML rather than an API JSON "
                            "response. No job ID was returned. This tool will not "
                            "retry or claim that a job was submitted."
                        ),
                        "job_submitted": False,
                        "rasters_downloaded": False,
                        "classification_performed": False,
                        "review_flags": [
                            "Legacy LFPS ArcGIS submission route is not usable for "
                            "this workflow.",
                            "Inspect the current LFPS v2 API contract before creating "
                            "a replacement submission tool.",
                            "No local job manifest was created.",
                            "No raster download or classification occurred.",
                        ],
                }

            return {
                "status": "source_response_unconfirmed",
                "stage": "submit_landfire_job",
                "source": LANDFIRE_LFPS_SUBMIT_JOB,
                "http_status_code": response.status_code,
                "response_content_type": response_content_type,
                "response_body_length_bytes": len(response.content),
                "response_preview": response_text[:1_000],
                "message": (
                    "LANDFIRE returned a non-JSON response. MapCP cannot confirm "
                    "whether a job was created and will not automatically resubmit."
                ),
                "job_submitted": "unknown",
                "rasters_downloaded": False,
                "classification_performed": False,
                "review_flags": [
                    "Inspect the captured response preview before retrying.",
                    "No local LANDFIRE job ID or job manifest was created.",
        ],
    }

    except (
        httpx.HTTPError,
        ToolError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        return {
            "status": "source_failed",
            "stage": "submit_landfire_job",
            "source": LANDFIRE_LFPS_SUBMIT_JOB,
            "error": str(error),
            "job_submitted": False,
        }

    if not isinstance(submit_response, dict):
        return {
            "status": "unexpected_source_response",
            "stage": "submit_landfire_job",
            "source": LANDFIRE_LFPS_SUBMIT_JOB,
            "message": "Expected a JSON object from LFPS submitJob.",
            "job_submitted": False,
        }

    if "error" in submit_response:
        return {
            "status": "source_failed",
            "stage": "submit_landfire_job",
            "source": LANDFIRE_LFPS_SUBMIT_JOB,
            "error": submit_response["error"],
            "job_submitted": False,
        }

    job_id = submit_response.get("jobId")

    if not isinstance(job_id, str) or not job_id.strip():
        return {
            "status": "unexpected_source_response",
            "stage": "submit_landfire_job",
            "source": LANDFIRE_LFPS_SUBMIT_JOB,
            "message": "LFPS response did not contain a usable jobId.",
            "submit_response": submit_response,
            "job_submitted": False,
        }

    run_id = submitted_at.strftime("%Y%m%dT%H%M%S%fZ")
    job_manifest_path = (
        OUTPUT_FOLDER
        / f"{request_path.stem}_landfire_job_{run_id}.json"
    )

    job_manifest = {
        "status": "submitted_waiting_for_completion",
        "submitted_at_utc": submitted_at.isoformat(),
        "prepared_request": str(request_path),
        "source_task": LANDFIRE_LFPS_TASK,
        "submit_job_endpoint": LANDFIRE_LFPS_SUBMIT_JOB,
        "job_id": job_id,
        "initial_job_status": submit_response.get("jobStatus"),
        "submit_parameters": submit_parameters,
        "submit_response": submit_response,
        "job_status_endpoint": (
            f"{LANDFIRE_LFPS_TASK}/jobs/{job_id}"
        ),
        "output_result_endpoint": (
            f"{LANDFIRE_LFPS_TASK}/jobs/{job_id}/results/Output_File"
        ),
        "rasters_downloaded": False,
        "classification_performed": False,
        "review_flags": [
            "LANDFIRE job submission was accepted, but completion has not "
            "been confirmed.",
            "No output file has been downloaded or validated.",
            "Output layer order, CRS, cell size, NoData, and metadata XML "
            "must be validated after job completion.",
            "No forest/nonforest or cover-type classification has occurred.",
            "Professional forestry and GIS review is required.",
        ],
    }

    try:
        job_manifest_path.write_text(
            json.dumps(job_manifest, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        return {
            "status": "submitted_manifest_write_failed",
            "stage": "save_job_manifest",
            "job_id": job_id,
            "error": str(error),
            "job_submitted": True,
            "rasters_downloaded": False,
        }

    return {
        "status": "submitted_waiting_for_completion",
        "job_id": job_id,
        "initial_job_status": submit_response.get("jobStatus"),
        "job_manifest": str(job_manifest_path),
        "job_status_endpoint": (
            f"{LANDFIRE_LFPS_TASK}/jobs/{job_id}"
        ),
        "rasters_downloaded": False,
        "classification_performed": False,
        "review_flags": job_manifest["review_flags"],
    }

@mcp.tool()
def prepare_landfire_v2_sample_request(
    naip_manifest_filename: str,
) -> dict:
    """
    Prepare, but do not submit, one LANDFIRE Product Service v2 sample request.

    The tool reads one MapCP-generated NAIP review-sample source manifest,
    validates its sample extent, and writes a reviewed LFPS v2 request record.

    It does not accept, store, or transmit an email address. It does not
    submit a LANDFIRE job, download output, or classify forest/nonforest or
    cover types.
    """
    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+_naip_sample_\d{8}T\d{12}Z_source\.json",
        naip_manifest_filename,
    ):
        raise ToolError(
            "Use the exact generated NAIP sample source-manifest filename "
            "only, not a full path."
        )

    folder = OUTPUT_FOLDER.resolve()
    manifest_path = (folder / naip_manifest_filename).resolve()

    if manifest_path.parent != folder:
        raise ToolError(
            "NAIP source manifest must remain inside the outputs folder."
        )

    if not manifest_path.is_file():
        raise ToolError(
            "NAIP sample source manifest was not found in outputs."
        )

    if manifest_path.stat().st_size > MAX_RESPONSE_BYTES:
        raise ToolError(
            "NAIP source manifest exceeds the 5 MB safety limit."
        )

    try:
        naip_manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        return {
            "status": "failed",
            "stage": "read_naip_source_manifest",
            "input_manifest": str(manifest_path),
            "error": str(error),
            "job_submitted": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if not isinstance(naip_manifest, dict):
        return {
            "status": "review_required",
            "stage": "validate_naip_source_manifest",
            "input_manifest": str(manifest_path),
            "message": (
                "NAIP source manifest must contain a JSON object. "
                "No LANDFIRE request was prepared."
            ),
            "job_submitted": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if naip_manifest.get("status") != "downloaded_requires_review":
        return {
            "status": "review_required",
            "stage": "validate_naip_source_manifest",
            "input_manifest": str(manifest_path),
            "manifest_status": naip_manifest.get("status"),
            "message": (
                "NAIP source manifest does not have the expected "
                "downloaded_requires_review status. No LANDFIRE request "
                "was prepared."
            ),
            "job_submitted": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if not naip_manifest.get("grid_validation_passed"):
        return {
            "status": "review_required",
            "stage": "validate_naip_source_manifest",
            "input_manifest": str(manifest_path),
            "message": (
                "NAIP sample manifest does not show a passed grid "
                "validation. No LANDFIRE request was prepared."
            ),
            "job_submitted": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if not naip_manifest.get("returned_footprint_within_boundary"):
        return {
            "status": "review_required",
            "stage": "validate_naip_source_manifest",
            "input_manifest": str(manifest_path),
            "message": (
                "NAIP sample manifest does not show that the returned "
                "raster footprint was inside the selected boundary. "
                "No LANDFIRE request was prepared."
            ),
            "job_submitted": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    aoi_values = naip_manifest.get("reference_envelope_lonlat")

    if not (
        isinstance(aoi_values, list)
        and len(aoi_values) == 4
    ):
        return {
            "status": "review_required",
            "stage": "validate_naip_source_manifest",
            "input_manifest": str(manifest_path),
            "message": (
                "The NAIP source manifest does not contain the expected "
                "reference_envelope_lonlat extent. No LANDFIRE request "
                "was prepared."
            ),
            "job_submitted": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    try:
        west, south, east, north = map(float, aoi_values)
    except (TypeError, ValueError) as error:
        return {
            "status": "review_required",
            "stage": "validate_naip_source_manifest",
            "input_manifest": str(manifest_path),
            "error": str(error),
            "message": (
                "NAIP reference envelope must contain numeric WGS84 "
                "west, south, east, north values."
            ),
            "job_submitted": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if not all(
        math.isfinite(value)
        for value in [west, south, east, north]
    ):
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_aoi",
            "input_manifest": str(manifest_path),
            "message": (
                "NAIP reference envelope contains non-finite coordinate "
                "values. No LANDFIRE request was prepared."
            ),
            "job_submitted": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if not (
        -125 <= west < east <= -66
        and 24 <= south < north <= 50
    ):
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_aoi",
            "input_manifest": str(manifest_path),
            "aoi_wgs84_west_south_east_north": [
                west,
                south,
                east,
                north,
            ],
            "message": (
                "NAIP sample AOI is outside the initial lower-48 MapCP "
                "LFPS v2 workflow scope or has invalid coordinate order."
            ),
            "job_submitted": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    aoi_width_degrees = east - west
    aoi_height_degrees = north - south

    if (
        aoi_width_degrees > LANDFIRE_LFPS_V2_MAX_AOI_WIDTH_DEGREES
        or aoi_height_degrees > LANDFIRE_LFPS_V2_MAX_AOI_HEIGHT_DEGREES
    ):
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_aoi",
            "input_manifest": str(manifest_path),
            "aoi_wgs84_west_south_east_north": [
                west,
                south,
                east,
                north,
            ],
            "aoi_width_degrees": aoi_width_degrees,
            "aoi_height_degrees": aoi_height_degrees,
            "message": (
                "AOI exceeds the MapCP small-area LFPS v2 test limit. "
                "No LANDFIRE request was prepared."
            ),
            "job_submitted": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    aoi_text = (
        f"{west:.12f} {south:.12f} "
        f"{east:.12f} {north:.12f}"
    )

    # Email is deliberately absent. It is accepted only at approved
    # submission time and is never written to a local request record.
    submit_parameters_without_email = {
        "Layer_List": LANDFIRE_LFPS_V2_LAYER_LIST,
        "Include_Layer_List_XML_File": "true",
        "Area_of_Interest": aoi_text,
        "Output_Projection": str(
            LANDFIRE_LFPS_V2_OUTPUT_WKID
        ),
    }

    prepared_at = datetime.now(timezone.utc)
    run_id = prepared_at.strftime("%Y%m%dT%H%M%S%fZ")

    request_path = (
        OUTPUT_FOLDER
        / f"{manifest_path.stem}_landfire_v2_request_{run_id}.json"
    )

    review_flags = [
        "This request has not been submitted to LANDFIRE.",
        "The raw contact email is not stored in this request record.",
        "A valid personal, Tribal, contractor, university, work, or other "
        "contact email is required only at approved LFPS v2 submission.",
        "LFPS output bands and layer metadata must be validated after "
        "job completion.",
        "No Resample_Resolution parameter is sent; native LANDFIRE "
        "resolution is requested.",
        "Thirty-meter LANDFIRE evidence is not equivalent to the one-meter "
        "NAIP review sample.",
        "No forest/nonforest or cover-type classification has occurred.",
        "Professional forestry and GIS review is required.",
    ]

    request_record = {
        "status": "request_prepared_requires_submission_approval",
        "prepared_at_utc": prepared_at.isoformat(),
        "api_version": "LFPS v2",
        "prepared_request": str(request_path),
        "source_naip_manifest": str(manifest_path),
        "source_naip_manifest_status": naip_manifest.get("status"),
        "source_naip_aoi_field": "reference_envelope_lonlat",
        "submission_method": "GET",
        "submission_endpoint": LANDFIRE_LFPS_V2_SUBMIT_URL,
        "status_endpoint": LANDFIRE_LFPS_V2_STATUS_URL,
        "layers_in_requested_band_order": (
            LANDFIRE_LFPS_V2_SAMPLE_LAYERS
        ),
        "layer_list": LANDFIRE_LFPS_V2_LAYER_LIST,
        "aoi_wgs84_west_south_east_north": [
            west,
            south,
            east,
            north,
        ],
        "aoi_width_degrees": aoi_width_degrees,
        "aoi_height_degrees": aoi_height_degrees,
        "output_projection_wkid": (
            LANDFIRE_LFPS_V2_OUTPUT_WKID
        ),
        "resample_resolution_parameter_sent": False,
        "expected_native_resolution_meters": 30,
        "include_layer_list_xml_file": True,
        "contact_email_required_at_submission": True,
        "contact_email_stored": False,
        "submit_parameters_without_email": (
            submit_parameters_without_email
        ),
        "job_submitted": False,
        "rasters_downloaded": False,
        "classification_performed": False,
        "review_flags": review_flags,
        "limitations": [
            "The LFPS v2 AOI is the WGS84 envelope of the validated "
            "1 km NAIP review sample, not a polygon clip geometry.",
            "The prepared request does not establish product coverage, "
            "raster values, or final output format.",
            "LANDFIRE vegetation products are modeled planning evidence, "
            "not field inventory measurements or final stand labels.",
        ],
    }

    try:
        OUTPUT_FOLDER.mkdir(exist_ok=True)
        request_path.write_text(
            json.dumps(request_record, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        return {
            "status": "failed",
            "stage": "save_prepared_lfps_v2_request",
            "error": str(error),
            "job_submitted": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    return {
        "status": "request_prepared_requires_submission_approval",
        "prepared_request": str(request_path),
        "api_version": "LFPS v2",
        "submission_method": "GET",
        "submission_endpoint": LANDFIRE_LFPS_V2_SUBMIT_URL,
        "layers_in_requested_band_order": (
            LANDFIRE_LFPS_V2_SAMPLE_LAYERS
        ),
        "aoi_wgs84_west_south_east_north": [
            west,
            south,
            east,
            north,
        ],
        "output_projection_wkid": (
            LANDFIRE_LFPS_V2_OUTPUT_WKID
        ),
        "resample_resolution_parameter_sent": False,
        "expected_native_resolution_meters": 30,
        "include_layer_list_xml_file": True,
        "contact_email_required_at_submission": True,
        "contact_email_stored": False,
        "job_submitted": False,
        "rasters_downloaded": False,
        "classification_performed": False,
        "review_flags": review_flags,
    }

@mcp.tool()
def submit_landfire_v2_sample_job(
        prepared_request_filename: str,
        request_contact_email: str,
        submission_approval: Literal[
            "submit_this_exact_lfps_v2_request"
        ],
    ) -> dict:
        """
        Submit one explicitly approved MapCP LANDFIRE Product Service v2 request.

        The tool reads an existing local LFPS v2 prepared-request record and sends
        exactly one GET request to the fixed official LFPS v2 submission endpoint.

        The contact email is used only in the outbound LFPS request. MapCP does not
        save or return the raw email address. This tool does not retry, poll job
        status, download output, or perform classification.
        """
        if not re.fullmatch(
        r"[A-Za-z0-9_.-]+_landfire_v2_request_\d{8}T\d{12}Z\.json",
        prepared_request_filename,
        ):
            raise ToolError(
                "Use the exact generated LFPS v2 prepared-request filename only, "
                "not a full path."
            )

        contact_email = request_contact_email.strip()

        if not re.fullmatch(
            r"[^@\s]{1,64}@[^@\s]{1,253}\.[^@\s]{2,63}",
            contact_email,
        ):
            raise ToolError(
                "Enter a valid contact email address for the LFPS v2 request."
            )

        if submission_approval != "submit_this_exact_lfps_v2_request":
            raise ToolError(
                "Submission approval phrase did not match. No LANDFIRE job "
                "was submitted."
            )

        def redact_email(value: object) -> object:
            if isinstance(value, str):
                return value.replace(contact_email, "<redacted-email>")

            if isinstance(value, list):
                return [redact_email(item) for item in value]

            if isinstance(value, dict):
                redacted = {}

                for key, item in value.items():
                    if str(key).lower() == "email":
                        redacted[key] = "<redacted-email>"
                    else:
                        redacted[key] = redact_email(item)

                return redacted

            return value

        folder = OUTPUT_FOLDER.resolve()
        request_path = (folder / prepared_request_filename).resolve()

        if request_path.parent != folder:
            raise ToolError(
                "Prepared request must remain inside the outputs folder."
            )

        if not request_path.is_file():
            raise ToolError(
                "LFPS v2 prepared request was not found in outputs."
            )

        if request_path.stat().st_size > MAX_RESPONSE_BYTES:
            raise ToolError(
                "LFPS v2 prepared request exceeds the 5 MB safety limit."
            )

        try:
            prepared_request = json.loads(
                request_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            return {
                "status": "failed",
                "stage": "read_prepared_lfps_v2_request",
                "error": redact_email(str(error)),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if not isinstance(prepared_request, dict):
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared LFPS v2 request must contain a JSON object. "
                    "No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if (
            prepared_request.get("status")
            != "request_prepared_requires_submission_approval"
        ):
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request does not have the required review status. "
                    "No LANDFIRE job was submitted."
                ),
                "prepared_request_status": prepared_request.get("status"),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if prepared_request.get("api_version") != "LFPS v2":
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request is not an LFPS v2 request. "
                    "No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if prepared_request.get("submission_method") != "GET":
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request does not use the approved LFPS v2 GET "
                    "submission method. No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if (
            prepared_request.get("submission_endpoint")
            != LANDFIRE_LFPS_V2_SUBMIT_URL
        ):
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request uses an unexpected submission endpoint. "
                    "No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if (
            prepared_request.get("status_endpoint")
            != LANDFIRE_LFPS_V2_STATUS_URL
        ):
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request uses an unexpected status endpoint. "
                    "No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if (
            prepared_request.get("layers_in_requested_band_order")
            != LANDFIRE_LFPS_V2_SAMPLE_LAYERS
        ):
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request layers differ from the approved LF2025 "
                    "EVT/EVC/EVH sample stack. No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if (
            prepared_request.get("layer_list")
            != LANDFIRE_LFPS_V2_LAYER_LIST
        ):
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared Layer_List differs from the approved LF2025 "
                    "EVT/EVC/EVH sample stack. No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if (
            prepared_request.get("output_projection_wkid")
            != LANDFIRE_LFPS_V2_OUTPUT_WKID
        ):
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request projection differs from WKID 5070. "
                    "No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if prepared_request.get(
            "resample_resolution_parameter_sent"
        ) is not False:
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request includes an unapproved resampling setting. "
                    "No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if prepared_request.get(
            "include_layer_list_xml_file"
        ) is not True:
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request does not require metadata XML. "
                    "No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if prepared_request.get("contact_email_stored") is not False:
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request does not meet the MapCP contact-email "
                    "storage policy. No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        aoi_values = prepared_request.get(
            "aoi_wgs84_west_south_east_north"
        )

        if not (
            isinstance(aoi_values, list)
            and len(aoi_values) == 4
        ):
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request AOI is missing or invalid. "
                    "No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        try:
            west, south, east, north = map(float, aoi_values)
        except (TypeError, ValueError):
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request AOI must contain numeric WGS84 "
                    "west, south, east, north coordinates."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if not (
            all(
                math.isfinite(value)
                for value in [west, south, east, north]
            )
            and -125 <= west < east <= -66
            and 24 <= south < north <= 50
        ):
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request AOI is outside the current lower-48 "
                    "MapCP scope or has invalid coordinate order. "
                    "No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if (
            east - west > LANDFIRE_LFPS_V2_MAX_AOI_WIDTH_DEGREES
            or north - south > LANDFIRE_LFPS_V2_MAX_AOI_HEIGHT_DEGREES
        ):
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Prepared request AOI exceeds the MapCP small-area LFPS v2 "
                    "test limit. No LANDFIRE job was submitted."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        aoi_text = (
            f"{west:.12f} {south:.12f} "
            f"{east:.12f} {north:.12f}"
        )

        expected_parameters_without_email = {
            "Layer_List": LANDFIRE_LFPS_V2_LAYER_LIST,
            "Include_Layer_List_XML_File": "true",
            "Area_of_Interest": aoi_text,
            "Output_Projection": str(
                LANDFIRE_LFPS_V2_OUTPUT_WKID
            ),
        }

        saved_parameters_without_email = prepared_request.get(
            "submit_parameters_without_email"
        )

        if (
            saved_parameters_without_email
            != expected_parameters_without_email
        ):
            return {
                "status": "review_required",
                "stage": "validate_prepared_lfps_v2_request",
                "message": (
                    "Saved LFPS v2 parameters differ from the approved request. "
                    "No LANDFIRE job was submitted."
                ),
                "expected_parameters_without_email": (
                    expected_parameters_without_email
                ),
                "saved_parameters_without_email": (
                    saved_parameters_without_email
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        submission_parameters = dict(
            expected_parameters_without_email
        )
        submission_parameters["Email"] = contact_email

        submitted_at = datetime.now(timezone.utc)

        try:
            with httpx.Client(
                timeout=60.0,
                follow_redirects=False,
            ) as client:
                response = client.get(
                    LANDFIRE_LFPS_V2_SUBMIT_URL,
                    params=submission_parameters,
                    headers={"Accept": "application/json"},
                )

                if response.is_redirect:
                    raise ToolError(
                        "LFPS v2 submission endpoint redirected; refusing to "
                        "follow an unreviewed URL."
                    )

                response.raise_for_status()

                if len(response.content) > MAX_RESPONSE_BYTES:
                    raise ToolError(
                        "LFPS v2 submission response exceeded the 5 MB limit."
                    )

                response_content_type = response.headers.get(
                    "content-type",
                    ""
                ).lower()

                response_text = response.text.strip()

                if "application/json" not in response_content_type:
                    return {
                        "status": "unexpected_source_response",
                        "stage": "submit_landfire_v2_job",
                        "source": LANDFIRE_LFPS_V2_SUBMIT_URL,
                        "http_status_code": response.status_code,
                        "response_content_type": response_content_type,
                        "response_body_length_bytes": len(response.content),
                        "response_preview": redact_email(
                            response_text[:1_000]
                        ),
                        "message": (
                            "LFPS v2 submission returned a non-JSON response. "
                            "MapCP cannot confirm that a job was created."
                        ),
                        "job_submitted": "unknown",
                        "rasters_downloaded": False,
                        "classification_performed": False,
                    }

                submit_response = response.json()

        except (
            httpx.HTTPError,
            ToolError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            return {
                "status": "source_failed",
                "stage": "submit_landfire_v2_job",
                "source": LANDFIRE_LFPS_V2_SUBMIT_URL,
                "error": redact_email(str(error)),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        if not isinstance(submit_response, dict):
            return {
                "status": "unexpected_source_response",
                "stage": "submit_landfire_v2_job",
                "source": LANDFIRE_LFPS_V2_SUBMIT_URL,
                "message": (
                    "LFPS v2 submission response was not a JSON object."
                ),
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        safe_submit_response = redact_email(submit_response)

        if submit_response.get("success") is False:
            return {
                "status": "source_failed",
                "stage": "submit_landfire_v2_job",
                "source": LANDFIRE_LFPS_V2_SUBMIT_URL,
                "submit_response": safe_submit_response,
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        job_id = submit_response.get("jobId")

        if not isinstance(job_id, str) or not re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{12}",
            job_id,
        ):
            return {
                "status": "unexpected_source_response",
                "stage": "submit_landfire_v2_job",
                "source": LANDFIRE_LFPS_V2_SUBMIT_URL,
                "message": (
                    "LFPS v2 response did not contain a usable UUID-style jobId."
                ),
                "submit_response": safe_submit_response,
                "job_submitted": False,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        run_id = submitted_at.strftime("%Y%m%dT%H%M%S%fZ")

        OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

        job_manifest_path = (
            OUTPUT_FOLDER
            / f"lfps_v2_job_{run_id}_{job_id}.json"
        )

        job_manifest = {
            "status": "submitted_waiting_for_completion",
            "submitted_at_utc": submitted_at.isoformat(),
            "api_version": "LFPS v2",
            "prepared_request": str(request_path),
            "submission_method": "GET",
            "submission_endpoint": LANDFIRE_LFPS_V2_SUBMIT_URL,
            "status_endpoint": LANDFIRE_LFPS_V2_STATUS_URL,
            "job_status_request_parameters": {
                "JobId": job_id,
            },
            "job_status_url": (
                f"{LANDFIRE_LFPS_V2_STATUS_URL}?JobId={job_id}"
            ),
            "job_id": job_id,
            "initial_status": submit_response.get("status"),
            "initial_queue_position": submit_response.get(
                "queuePosition"
            ),
            "initial_messages": redact_email(
                submit_response.get("messages")
            ),
            "initial_output_file": redact_email(
                submit_response.get("outputFile")
            ),
            "layers_in_requested_band_order": (
                LANDFIRE_LFPS_V2_SAMPLE_LAYERS
            ),
            "aoi_wgs84_west_south_east_north": [
                west,
                south,
                east,
                north,
            ],
            "output_projection_wkid": (
                LANDFIRE_LFPS_V2_OUTPUT_WKID
            ),
            "resample_resolution_parameter_sent": False,
            "include_layer_list_xml_file": True,
            "contact_email_supplied": True,
            "contact_email_stored": False,
            "submit_parameters_without_email": (
                expected_parameters_without_email
            ),
            "job_submitted": True,
            "rasters_downloaded": False,
            "classification_performed": False,
            "review_flags": [
                "LFPS v2 accepted this job request, but completion has not "
                "been confirmed.",
                "No output file has been downloaded or validated.",
                "Returned output layer order and metadata XML must be checked.",
                "No forest/nonforest or cover-type classification has occurred.",
                "Professional forestry and GIS review is required.",
            ],
        }

        try:
            job_manifest_path.write_text(
                json.dumps(job_manifest, indent=2),
                encoding="utf-8",
            )
        except OSError as error:
            return {
                "status": "submitted_manifest_write_failed",
                "stage": "save_lfps_v2_job_manifest",
                "job_id": job_id,
                "error": redact_email(str(error)),
                "job_submitted": True,
                "rasters_downloaded": False,
                "classification_performed": False,
            }

        return {
            "status": "submitted_waiting_for_completion",
            "job_id": job_id,
            "initial_status": submit_response.get("status"),
            "initial_queue_position": submit_response.get(
                "queuePosition"
            ),
            "job_manifest": str(job_manifest_path),
            "job_status_endpoint": LANDFIRE_LFPS_V2_STATUS_URL,
            "job_status_request_parameters": {
                "JobId": job_id,
            },
            "job_submitted": True,
            "rasters_downloaded": False,
            "classification_performed": False,
            "review_flags": job_manifest["review_flags"],
        }

@mcp.tool()
def recover_landfire_v2_job_manifest(
    prepared_request_filename: str,
    job_id: str,
) -> dict:
    """
    Create a short local manifest for an LFPS v2 job that was accepted by
    LANDFIRE but whose original MapCP manifest could not be written.

    This tool makes no network request. It does not submit, cancel, poll,
    download, or modify a LANDFIRE job. It writes only a local recovery
    manifest without a raw contact email address.
    """
    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+_landfire_v2_request_\d{8}T\d{12}Z\.json",
        prepared_request_filename,
    ):
        raise ToolError(
            "Use the exact generated LFPS v2 prepared-request filename only, "
            "not a full path."
        )

    if not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}",
        job_id,
    ):
        raise ToolError(
            "job_id must be the UUID returned by LFPS v2."
        )

    folder = OUTPUT_FOLDER.resolve()
    request_path = (folder / prepared_request_filename).resolve()

    if request_path.parent != folder:
        raise ToolError(
            "Prepared request must remain inside the outputs folder."
        )

    if not request_path.is_file():
        raise ToolError(
            "LFPS v2 prepared request was not found in outputs."
        )

    if request_path.stat().st_size > MAX_RESPONSE_BYTES:
        raise ToolError(
            "LFPS v2 prepared request exceeds the 5 MB safety limit."
        )

    try:
        prepared_request = json.loads(
            request_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        return {
            "status": "failed",
            "stage": "read_prepared_lfps_v2_request",
            "error": str(error),
            "job_submitted": "unknown",
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if not isinstance(prepared_request, dict):
        return {
            "status": "review_required",
            "stage": "validate_prepared_lfps_v2_request",
            "message": (
                "Prepared LFPS v2 request must contain a JSON object. "
                "No recovery manifest was created."
            ),
            "job_submitted": "unknown",
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if (
        prepared_request.get("status")
        != "request_prepared_requires_submission_approval"
    ):
        return {
            "status": "review_required",
            "stage": "validate_prepared_lfps_v2_request",
            "message": (
                "Prepared request does not have the expected review status. "
                "No recovery manifest was created."
            ),
            "job_submitted": "unknown",
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if prepared_request.get("api_version") != "LFPS v2":
        return {
            "status": "review_required",
            "stage": "validate_prepared_lfps_v2_request",
            "message": (
                "Prepared request is not an LFPS v2 request. "
                "No recovery manifest was created."
            ),
            "job_submitted": "unknown",
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if (
        prepared_request.get("submission_endpoint")
        != LANDFIRE_LFPS_V2_SUBMIT_URL
    ):
        return {
            "status": "review_required",
            "stage": "validate_prepared_lfps_v2_request",
            "message": (
                "Prepared request uses an unexpected LFPS v2 endpoint. "
                "No recovery manifest was created."
            ),
            "job_submitted": "unknown",
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if (
        prepared_request.get("layers_in_requested_band_order")
        != LANDFIRE_LFPS_V2_SAMPLE_LAYERS
    ):
        return {
            "status": "review_required",
            "stage": "validate_prepared_lfps_v2_request",
            "message": (
                "Prepared request does not use the approved LF2025 "
                "EVT/EVC/EVH stack. No recovery manifest was created."
            ),
            "job_submitted": "unknown",
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    recovered_at = datetime.now(timezone.utc)
    run_id = recovered_at.strftime("%Y%m%dT%H%M%S%fZ")

    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    recovery_manifest_path = (
        OUTPUT_FOLDER
        / f"lfps_v2_job_recovered_{run_id}_{job_id}.json"
    )

    recovery_manifest = {
        "status": "submitted_manifest_recovered_needs_status_check",
        "recovered_at_utc": recovered_at.isoformat(),
        "api_version": "LFPS v2",
        "prepared_request": str(request_path),
        "submission_method": "GET",
        "submission_endpoint": LANDFIRE_LFPS_V2_SUBMIT_URL,
        "status_endpoint": LANDFIRE_LFPS_V2_STATUS_URL,
        "job_status_request_parameters": {
            "JobId": job_id,
        },
        "job_status_url": (
            f"{LANDFIRE_LFPS_V2_STATUS_URL}?JobId={job_id}"
        ),
        "job_id": job_id,
        "initial_status": "unknown_manifest_write_failed",
        "initial_queue_position": None,
        "initial_messages": None,
        "initial_output_file": None,
        "layers_in_requested_band_order": (
            prepared_request.get("layers_in_requested_band_order")
        ),
        "aoi_wgs84_west_south_east_north": (
            prepared_request.get(
                "aoi_wgs84_west_south_east_north"
            )
        ),
        "output_projection_wkid": (
            prepared_request.get("output_projection_wkid")
        ),
        "resample_resolution_parameter_sent": (
            prepared_request.get(
                "resample_resolution_parameter_sent"
            )
        ),
        "include_layer_list_xml_file": (
            prepared_request.get(
                "include_layer_list_xml_file"
            )
        ),
        "contact_email_supplied": True,
        "contact_email_stored": False,
        "submit_parameters_without_email": (
            prepared_request.get(
                "submit_parameters_without_email"
            )
        ),
        "job_submitted": True,
        "rasters_downloaded": False,
        "classification_performed": False,
        "review_flags": [
            "LANDFIRE accepted a job and returned this job ID.",
            "The original local job manifest could not be written because "
            "its generated filename was too long for the current Windows "
            "path environment.",
            "This is a local recovery record; the initial source response "
            "fields were not retained.",
            "Use check_landfire_v2_sample_job to verify current status.",
            "No output file has been downloaded or validated.",
            "No forest/nonforest or cover-type classification has occurred.",
            "Professional forestry and GIS review is required.",
        ],
    }

    try:
        recovery_manifest_path.write_text(
            json.dumps(recovery_manifest, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        return {
            "status": "recovery_manifest_write_failed",
            "stage": "save_recovery_manifest",
            "job_id": job_id,
            "error": str(error),
            "job_submitted": True,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    return {
        "status": "submitted_manifest_recovered_needs_status_check",
        "job_id": job_id,
        "recovery_manifest": str(recovery_manifest_path),
        "job_status_endpoint": LANDFIRE_LFPS_V2_STATUS_URL,
        "job_status_request_parameters": {
            "JobId": job_id,
        },
        "job_submitted": True,
        "rasters_downloaded": False,
        "classification_performed": False,
        "review_flags": recovery_manifest["review_flags"],
    }

@mcp.tool()
def check_landfire_v2_sample_job(
    job_manifest_filename: str,
) -> dict:
    """
    Check the current status of one existing LANDFIRE Product Service v2 job.

    This tool reads a short local LFPS v2 job manifest, validates its UUID and
    fixed status endpoint, then performs one read-only LFPS status request.

    It does not submit a job, resend an email, cancel a job, download output,
    or perform classification.
    """
    if not re.fullmatch(
        r"lfps_v2_job_(?:recovered_)?\d{8}T\d{12}Z_"
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}\.json",
        job_manifest_filename,
    ):
        raise ToolError(
            "Use the exact generated LFPS v2 job-manifest filename only, "
            "not a full path."
        )

    folder = OUTPUT_FOLDER.resolve()
    manifest_path = (folder / job_manifest_filename).resolve()

    if manifest_path.parent != folder:
        raise ToolError(
            "LFPS v2 job manifest must remain inside the outputs folder."
        )

    if not manifest_path.is_file():
        raise ToolError(
            "LFPS v2 job manifest was not found in outputs."
        )

    if manifest_path.stat().st_size > MAX_RESPONSE_BYTES:
        raise ToolError(
            "LFPS v2 job manifest exceeds the 5 MB safety limit."
        )

    try:
        job_manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        return {
            "status": "failed",
            "stage": "read_lfps_v2_job_manifest",
            "error": str(error),
            "job_status_checked": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if not isinstance(job_manifest, dict):
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_job_manifest",
            "message": (
                "LFPS v2 job manifest must contain a JSON object. "
                "No source status request was made."
            ),
            "job_status_checked": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if job_manifest.get("api_version") != "LFPS v2":
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_job_manifest",
            "message": (
                "Job manifest is not an LFPS v2 record. "
                "No source status request was made."
            ),
            "job_status_checked": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if (
        job_manifest.get("status_endpoint")
        != LANDFIRE_LFPS_V2_STATUS_URL
    ):
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_job_manifest",
            "message": (
                "Job manifest has an unexpected LFPS v2 status endpoint. "
                "No source status request was made."
            ),
            "job_status_checked": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    job_id = job_manifest.get("job_id")

    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}",
        job_id,
    ):
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_job_manifest",
            "message": (
                "Job manifest does not contain a valid UUID-style LFPS v2 "
                "job ID. No source status request was made."
            ),
            "job_status_checked": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    checked_at = datetime.now(timezone.utc)

    try:
        with httpx.Client(
            timeout=30.0,
            follow_redirects=False,
        ) as client:
            response = client.get(
                LANDFIRE_LFPS_V2_STATUS_URL,
                params={"JobId": job_id},
                headers={"Accept": "application/json"},
            )

            if response.is_redirect:
                raise ToolError(
                    "LFPS v2 status endpoint redirected; refusing to follow "
                    "an unreviewed URL."
                )

            response.raise_for_status()

            if len(response.content) > MAX_RESPONSE_BYTES:
                raise ToolError(
                    "LFPS v2 status response exceeded the 5 MB limit."
                )

            response_content_type = response.headers.get(
                "content-type",
                ""
            ).lower()

            response_text = response.text.strip()

            if "application/json" not in response_content_type:
                return {
                    "status": "unexpected_source_response",
                    "stage": "check_lfps_v2_job_status",
                    "source": LANDFIRE_LFPS_V2_STATUS_URL,
                    "job_id": job_id,
                    "http_status_code": response.status_code,
                    "response_content_type": response_content_type,
                    "response_body_length_bytes": len(response.content),
                    "response_preview": response_text[:1_000],
                    "job_status_checked": False,
                    "rasters_downloaded": False,
                    "classification_performed": False,
                }

            status_response = response.json()

    except (
        httpx.HTTPError,
        ToolError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        return {
            "status": "source_failed",
            "stage": "check_lfps_v2_job_status",
            "source": LANDFIRE_LFPS_V2_STATUS_URL,
            "job_id": job_id,
            "error": str(error),
            "job_status_checked": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if not isinstance(status_response, dict):
        return {
            "status": "unexpected_source_response",
            "stage": "check_lfps_v2_job_status",
            "source": LANDFIRE_LFPS_V2_STATUS_URL,
            "job_id": job_id,
            "message": (
                "LFPS v2 status response was not a JSON object."
            ),
            "job_status_checked": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if status_response.get("success") is False:
        return {
            "status": "source_failed",
            "stage": "check_lfps_v2_job_status",
            "source": LANDFIRE_LFPS_V2_STATUS_URL,
            "job_id": job_id,
            "status_response": status_response,
            "job_status_checked": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    returned_job_id = status_response.get("jobId")

    if returned_job_id != job_id:
        return {
            "status": "unexpected_source_response",
            "stage": "check_lfps_v2_job_status",
            "source": LANDFIRE_LFPS_V2_STATUS_URL,
            "requested_job_id": job_id,
            "returned_job_id": returned_job_id,
            "message": (
                "LFPS v2 status response job ID does not match the "
                "requested job ID."
            ),
            "job_status_checked": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    source_status = status_response.get("status")

    if not isinstance(source_status, str) or not source_status.strip():
        return {
            "status": "unexpected_source_response",
            "stage": "check_lfps_v2_job_status",
            "source": LANDFIRE_LFPS_V2_STATUS_URL,
            "job_id": job_id,
            "message": (
                "LFPS v2 status response did not contain a usable status."
            ),
            "status_response": status_response,
            "job_status_checked": False,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    normalized_status = source_status.strip().lower()

    if normalized_status in {"pending", "queued"}:
        mapcp_status = "submitted_waiting_in_queue"
    elif normalized_status in {"executing", "running", "processing"}:
        mapcp_status = "submitted_processing"
    elif normalized_status in {"succeeded", "success", "completed"}:
        mapcp_status = "completed_requires_output_collection"
    elif normalized_status in {"failed", "error"}:
        mapcp_status = "source_job_failed"
    elif normalized_status in {"canceled", "cancelled"}:
        mapcp_status = "source_job_canceled"
    else:
        mapcp_status = "source_job_status_unrecognized"

    run_id = checked_at.strftime("%Y%m%dT%H%M%S%fZ")

    status_report_path = (
        OUTPUT_FOLDER
        / f"lfps_v2_status_{run_id}_{job_id}.json"
    )

    status_report = {
        "status": mapcp_status,
        "checked_at_utc": checked_at.isoformat(),
        "api_version": "LFPS v2",
        "source_job_manifest": str(manifest_path),
        "status_endpoint": LANDFIRE_LFPS_V2_STATUS_URL,
        "job_status_request_parameters": {
            "JobId": job_id,
        },
        "job_id": job_id,
        "source_status": source_status,
        "queue_position": status_response.get("queuePosition"),
        "messages": status_response.get("messages"),
        "output_file": status_response.get("outputFile"),
        "job_status_checked": True,
        "rasters_downloaded": False,
        "classification_performed": False,
        "review_flags": [
            "This tool checked source job status only.",
            "No job was submitted or resubmitted.",
            "No output file has been downloaded or validated.",
            "No forest/nonforest or cover-type classification has occurred.",
            "Professional forestry and GIS review is required.",
        ],
    }

    try:
        OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
        status_report_path.write_text(
            json.dumps(status_report, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        return {
            "status": "status_checked_report_write_failed",
            "job_id": job_id,
            "source_status": source_status,
            "queue_position": status_response.get("queuePosition"),
            "output_file": status_response.get("outputFile"),
            "error": str(error),
            "job_status_checked": True,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    return {
        "status": mapcp_status,
        "job_id": job_id,
        "source_status": source_status,
        "queue_position": status_response.get("queuePosition"),
        "messages": status_response.get("messages"),
        "output_file": status_response.get("outputFile"),
        "status_report": str(status_report_path),
        "job_status_checked": True,
        "rasters_downloaded": False,
        "classification_performed": False,
        "review_flags": status_report["review_flags"],
    }

@mcp.tool()
def collect_landfire_v2_sample_result(
    status_report_filename: str,
    collection_approval: Literal[
        "download_and_validate_this_exact_lfps_v2_bundle"
    ],
) -> dict:
    """
    Download and validate one completed LANDFIRE Product Service v2 output.

    This tool reads a successful MapCP LFPS v2 status report, validates the
    source-provided ZIP URL against a fixed allowlist, downloads one bounded
    ZIP file, validates archive safety, extracts files to a controlled folder,
    and inspects the GeoTIFF and expected XML metadata files.

    It does not submit or resubmit a job, send an email, change remote data,
    perform forest/nonforest classification, create cover types, or create
    stands.
    """
    if not re.fullmatch(
        r"lfps_v2_status_\d{8}T\d{12}Z_"
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}\.json",
        status_report_filename,
    ):
        raise ToolError(
            "Use the exact generated LFPS v2 status-report filename only, "
            "not a full path."
        )

    if (
        collection_approval
        != "download_and_validate_this_exact_lfps_v2_bundle"
    ):
        raise ToolError(
            "Collection approval phrase did not match. No LFPS output "
            "bundle was downloaded."
        )

    folder = OUTPUT_FOLDER.resolve()
    status_report_path = (
        folder / status_report_filename
    ).resolve()

    if status_report_path.parent != folder:
        raise ToolError(
            "LFPS v2 status report must remain inside the outputs folder."
        )

    if not status_report_path.is_file():
        raise ToolError(
            "LFPS v2 status report was not found in outputs."
        )

    if status_report_path.stat().st_size > MAX_RESPONSE_BYTES:
        raise ToolError(
            "LFPS v2 status report exceeds the 5 MB safety limit."
        )

    try:
        status_report = json.loads(
            status_report_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        return {
            "status": "failed",
            "stage": "read_lfps_v2_status_report",
            "error": str(error),
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if not isinstance(status_report, dict):
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_status_report",
            "message": (
                "LFPS v2 status report must contain a JSON object. "
                "No bundle was downloaded."
            ),
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if status_report.get("status") != (
        "completed_requires_output_collection"
    ):
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_status_report",
            "message": (
                "LFPS v2 status report does not show a completed job. "
                "No bundle was downloaded."
            ),
            "saved_status": status_report.get("status"),
            "source_status": status_report.get("source_status"),
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    if str(status_report.get("source_status", "")).strip().lower() not in {
        "succeeded",
        "success",
        "completed",
    }:
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_status_report",
            "message": (
                "LFPS v2 source status is not a terminal successful state. "
                "No bundle was downloaded."
            ),
            "source_status": status_report.get("source_status"),
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    job_id = status_report.get("job_id")

    if not isinstance(job_id, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}",
        job_id,
    ):
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_status_report",
            "message": (
                "LFPS v2 status report does not contain a valid UUID-style "
                "job ID. No bundle was downloaded."
            ),
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    output_url = status_report.get("output_file")

    if not isinstance(output_url, str):
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_output_url",
            "job_id": job_id,
            "message": (
                "LFPS v2 status report has no usable output_file URL. "
                "No bundle was downloaded."
            ),
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    parsed_url = urlparse(output_url)

    if not (
        parsed_url.scheme == "https"
        and parsed_url.netloc.lower()
        == LANDFIRE_LFPS_V2_OUTPUT_HOST
        and parsed_url.path.startswith(
            LANDFIRE_LFPS_V2_OUTPUT_PATH_PREFIX
        )
        and parsed_url.path.lower().endswith(".zip")
        and not parsed_url.username
        and not parsed_url.password
    ):
        return {
            "status": "review_required",
            "stage": "validate_lfps_v2_output_url",
            "job_id": job_id,
            "message": (
                "LFPS v2 output_file URL did not match the fixed HTTPS "
                "LANDFIRE output-bundle allowlist. No bundle was downloaded."
            ),
            "output_file": output_url,
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    zip_path = (
        OUTPUT_FOLDER / f"lfps_v2_bundle_{job_id}.zip"
    )

    partial_zip_path = (
        OUTPUT_FOLDER / f"lfps_v2_bundle_{job_id}.part"
    )

    extraction_path = (
        OUTPUT_FOLDER / f"lfps_v2_extract_{job_id}"
    )

    extraction_staging_path = (
        OUTPUT_FOLDER / f"lfps_v2_extract_{job_id}_staging"
    )

    if zip_path.exists():
        return {
            "status": "review_required",
            "stage": "prepare_lfps_v2_download",
            "job_id": job_id,
            "message": (
                "A ZIP bundle with this LFPS v2 job ID already exists. "
                "MapCP will not overwrite it automatically."
            ),
            "existing_bundle": str(zip_path),
            "rasters_downloaded": True,
            "classification_performed": False,
        }

    if extraction_path.exists() or extraction_staging_path.exists():
        return {
            "status": "review_required",
            "stage": "prepare_lfps_v2_extraction",
            "job_id": job_id,
            "message": (
                "An extraction folder for this LFPS v2 job already exists. "
                "MapCP will not overwrite it automatically."
            ),
            "existing_extraction_path": (
                str(extraction_path)
                if extraction_path.exists()
                else str(extraction_staging_path)
            ),
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    downloaded_bytes = 0

    try:
        with httpx.Client(
            timeout=120.0,
            follow_redirects=False,
        ) as client:
            with client.stream(
                "GET",
                output_url,
                headers={"Accept": "application/zip"},
            ) as response:
                if response.is_redirect:
                    raise ToolError(
                        "LFPS output URL redirected; refusing to follow an "
                        "unreviewed URL."
                    )

                response.raise_for_status()

                content_length = response.headers.get("content-length")

                if content_length is not None:
                    try:
                        advertised_bytes = int(content_length)
                    except ValueError:
                        advertised_bytes = None

                    if (
                        advertised_bytes is not None
                        and advertised_bytes
                        > LANDFIRE_LFPS_V2_MAX_BUNDLE_BYTES
                    ):
                        raise ToolError(
                            "LFPS output bundle exceeds the 100 MB "
                            "MapCP collection limit."
                        )

                with partial_zip_path.open("wb") as bundle_file:
                    for chunk in response.iter_bytes():
                        downloaded_bytes += len(chunk)

                        if (
                            downloaded_bytes
                            > LANDFIRE_LFPS_V2_MAX_BUNDLE_BYTES
                        ):
                            raise ToolError(
                                "LFPS output bundle exceeded the 100 MB "
                                "MapCP collection limit."
                            )

                        bundle_file.write(chunk)

        if downloaded_bytes == 0:
            raise ToolError(
                "LFPS output bundle download was empty."
            )

        partial_zip_path.replace(zip_path)

    except (httpx.HTTPError, OSError, ToolError) as error:
        if partial_zip_path.exists():
            partial_zip_path.unlink(missing_ok=True)

        return {
            "status": "source_download_failed",
            "stage": "download_lfps_v2_bundle",
            "job_id": job_id,
            "source": output_url,
            "downloaded_bytes_before_failure": downloaded_bytes,
            "error": str(error),
            "rasters_downloaded": False,
            "classification_performed": False,
        }

    try:
        with zipfile.ZipFile(zip_path, "r") as bundle_zip:
            members = bundle_zip.infolist()

            if not members:
                raise ToolError(
                    "LFPS output ZIP contains no files."
                )

            if len(members) > LANDFIRE_LFPS_V2_MAX_ZIP_MEMBERS:
                raise ToolError(
                    "LFPS output ZIP exceeds the 50-file safety limit."
                )

            total_uncompressed_bytes = sum(
                item.file_size for item in members
            )

            if (
                total_uncompressed_bytes
                > LANDFIRE_LFPS_V2_MAX_EXTRACTED_BYTES
            ):
                raise ToolError(
                    "LFPS output ZIP exceeds the 250 MB expanded-size "
                    "safety limit."
                )

            for item in members:
                member_path = Path(item.filename)

                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or item.filename.startswith(("/", "\\"))
                ):
                    raise ToolError(
                        "LFPS output ZIP contains an unsafe file path."
                    )

                if item.flag_bits & 0x1:
                    raise ToolError(
                        "LFPS output ZIP contains encrypted files, which "
                        "MapCP does not process."
                    )

                if (
                    item.compress_size > 0
                    and item.file_size / item.compress_size > 100
                ):
                    raise ToolError(
                        "LFPS output ZIP contains a suspicious compression "
                        "ratio above the MapCP safety limit."
                    )

            bad_member = bundle_zip.testzip()

            if bad_member is not None:
                raise ToolError(
                    f"LFPS output ZIP failed CRC validation for: "
                    f"{bad_member}"
                )

            tif_members = [
                item.filename
                for item in members
                if item.filename.lower().endswith(
                    (".tif", ".tiff")
                )
            ]

            if len(tif_members) != 1:
                raise ToolError(
                    "Expected exactly one GeoTIFF in the LFPS output ZIP; "
                    f"found {len(tif_members)}."
                )

            expected_xml_names = [
                "LF2025_EVT_CONUS.xml",
                "LF2025_EVC_CONUS.xml",
                "LF2025_EVH_CONUS.xml",
            ]

            member_names = {
                Path(item.filename).name
                for item in members
            }

            missing_xml_names = [
                name
                for name in expected_xml_names
                if name not in member_names
            ]

            if missing_xml_names:
                raise ToolError(
                    "LFPS output ZIP is missing expected layer metadata XML: "
                    + ", ".join(missing_xml_names)
                )

            extraction_staging_path.mkdir(
                parents=True,
                exist_ok=False,
            )

            extraction_root = extraction_staging_path.resolve()

            for item in members:
                destination = (
                    extraction_staging_path / item.filename
                ).resolve()

                try:
                    destination.relative_to(extraction_root)
                except ValueError as error:
                    raise ToolError(
                        "LFPS output ZIP member escaped the controlled "
                        "extraction folder."
                    ) from error

                if item.is_dir():
                    destination.mkdir(
                        parents=True,
                        exist_ok=True,
                    )
                    continue

                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                with bundle_zip.open(item, "r") as source_file:
                    with destination.open("wb") as target_file:
                        while True:
                            chunk = source_file.read(1024 * 1024)

                            if not chunk:
                                break

                            target_file.write(chunk)

        extraction_staging_path.replace(extraction_path)

    except (
        OSError,
        ToolError,
        zipfile.BadZipFile,
    ) as error:
        return {
            "status": "bundle_validation_or_extraction_failed",
            "stage": "validate_extract_lfps_v2_bundle",
            "job_id": job_id,
            "bundle": str(zip_path),
            "error": str(error),
            "rasters_downloaded": True,
            "classification_performed": False,
            "review_flags": [
                "The ZIP bundle was downloaded but did not complete "
                "MapCP validation or extraction.",
                "Do not use partial files without manual review.",
            ],
        }

    extracted_tif_path = (
        extraction_path / tif_members[0]
    ).resolve()

    xml_paths = {
        xml_name: str(
            (
                extraction_path / xml_name
            ).resolve()
        )
        for xml_name in expected_xml_names
    }

    try:
        with rasterio.open(extracted_tif_path) as dataset:
            band_count = dataset.count
            raster_crs = (
                dataset.crs.to_string()
                if dataset.crs is not None
                else None
            )
            raster_epsg = (
                dataset.crs.to_epsg()
                if dataset.crs is not None
                else None
            )
            raster_width = dataset.width
            raster_height = dataset.height
            raster_bounds = [
                float(dataset.bounds.left),
                float(dataset.bounds.bottom),
                float(dataset.bounds.right),
                float(dataset.bounds.top),
            ]
            raster_resolution = [
                abs(float(dataset.res[0])),
                abs(float(dataset.res[1])),
            ]
            raster_data_types = list(dataset.dtypes)
            raster_nodata_values = list(dataset.nodatavals)
            raster_band_descriptions = list(
                dataset.descriptions
            )

        raster_bounds_wgs84 = list(
            transform_bounds(
                raster_crs,
                "EPSG:4326",
                *raster_bounds,
                densify_pts=21,
            )
        )

    except Exception as error:
        return {
            "status": "raster_validation_failed",
            "stage": "inspect_lfps_v2_geotiff",
            "job_id": job_id,
            "bundle": str(zip_path),
            "extraction_folder": str(extraction_path),
            "error": str(error),
            "rasters_downloaded": True,
            "classification_performed": False,
        }

    validation_errors = []

    if band_count != 3:
        validation_errors.append(
            f"Expected 3 GeoTIFF bands but found {band_count}."
        )

    if raster_epsg != LANDFIRE_LFPS_V2_OUTPUT_WKID:
        validation_errors.append(
            "Expected GeoTIFF CRS EPSG:"
            f"{LANDFIRE_LFPS_V2_OUTPUT_WKID} but found {raster_crs}."
        )

    if not all(
        math.isclose(
            value,
            30.0,
            rel_tol=0.0,
            abs_tol=0.01,
        )
        for value in raster_resolution
    ):
        validation_errors.append(
            "Expected approximately 30 m GeoTIFF resolution but found "
            f"{raster_resolution}."
        )

    for xml_name, xml_path in xml_paths.items():
        if not Path(xml_path).is_file():
            validation_errors.append(
                f"Expected XML file was not extracted: {xml_name}."
            )

    expected_layer_order = [
        "LF2025_EVT_CONUS",
        "LF2025_EVC_CONUS",
        "LF2025_EVH_CONUS",
    ]

    normalized_descriptions = [
        description.strip()
        if isinstance(description, str)
        else None
        for description in raster_band_descriptions
    ]

    if normalized_descriptions == expected_layer_order:
        band_order_validation = "validated_from_geotiff_descriptions"
    else:
        band_order_validation = (
            "requires_metadata_and_arcgis_review"
        )

    collected_at = datetime.now(timezone.utc)
    run_id = collected_at.strftime("%Y%m%dT%H%M%S%fZ")

    collection_manifest_path = (
        OUTPUT_FOLDER
        / f"lfps_v2_collection_{run_id}_{job_id}.json"
    )

    collection_manifest = {
        "status": (
            "bundle_collected_requires_gis_review"
            if not validation_errors
            else "bundle_collected_validation_review_required"
        ),
        "collected_at_utc": collected_at.isoformat(),
        "api_version": "LFPS v2",
        "source_status_report": str(status_report_path),
        "source_output_url": output_url,
        "job_id": job_id,
        "bundle_file": str(zip_path),
        "bundle_file_bytes": downloaded_bytes,
        "extraction_folder": str(extraction_path),
        "geotiff_file": str(extracted_tif_path),
        "expected_layers_in_requested_band_order": (
            LANDFIRE_LFPS_V2_SAMPLE_LAYERS
        ),
        "expected_metadata_xml_files": xml_paths,
        "geotiff_band_count": band_count,
        "geotiff_band_descriptions": raster_band_descriptions,
        "band_order_validation": band_order_validation,
        "geotiff_crs": raster_crs,
        "geotiff_epsg": raster_epsg,
        "geotiff_width": raster_width,
        "geotiff_height": raster_height,
        "geotiff_bounds_epsg5070": raster_bounds,
        "geotiff_bounds_wgs84": raster_bounds_wgs84,
        "geotiff_resolution_meters": raster_resolution,
        "geotiff_data_types": raster_data_types,
        "geotiff_nodata_values": raster_nodata_values,
        "validation_errors": validation_errors,
        "job_submitted": True,
        "rasters_downloaded": True,
        "classification_performed": False,
        "review_flags": [
            "GeoTIFF band order is not assumed from request order.",
            "Open the GeoTIFF and metadata XML in ArcGIS Pro before "
            "using it as vegetation evidence.",
            "LANDFIRE vegetation products are modeled planning evidence, "
            "not field inventory measurements or final stand labels.",
            "No forest/nonforest or candidate cover-type classification "
            "has occurred.",
            "Professional forestry and GIS review is required.",
        ],
    }

    try:
        collection_manifest_path.write_text(
            json.dumps(collection_manifest, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        return {
            "status": "collection_manifest_write_failed",
            "stage": "save_lfps_v2_collection_manifest",
            "job_id": job_id,
            "bundle": str(zip_path),
            "extraction_folder": str(extraction_path),
            "error": str(error),
            "rasters_downloaded": True,
            "classification_performed": False,
        }

    return {
        "status": collection_manifest["status"],
        "job_id": job_id,
        "bundle_file": str(zip_path),
        "bundle_file_bytes": downloaded_bytes,
        "extraction_folder": str(extraction_path),
        "geotiff_file": str(extracted_tif_path),
        "expected_metadata_xml_files": xml_paths,
        "geotiff_band_count": band_count,
        "geotiff_band_descriptions": raster_band_descriptions,
        "band_order_validation": band_order_validation,
        "geotiff_crs": raster_crs,
        "geotiff_epsg": raster_epsg,
        "geotiff_resolution_meters": raster_resolution,
        "geotiff_bounds_epsg5070": raster_bounds,
        "geotiff_bounds_wgs84": raster_bounds_wgs84,
        "geotiff_nodata_values": raster_nodata_values,
        "validation_errors": validation_errors,
        "collection_manifest": str(collection_manifest_path),
        "job_submitted": True,
        "rasters_downloaded": True,
        "classification_performed": False,
        "review_flags": collection_manifest["review_flags"],
    }


# ---------------------------------------------------------------------------
# Slice 2 — inspect_landfire_v2_cover_type_inputs
# Internal helper and public MCP tool.
# Inspects already-collected LF2025 EVT/EVC/EVH raster and writes three
# durable artifacts:  *_report.md,  *_summary.json,  *_evt_inventory.csv
# No classification, crosswalk, forest-land determination, or polygon output.
# ---------------------------------------------------------------------------

_SLICE2_SENTINELS = {
    "classification_performed": False,
    "forest_land_determination_performed": False,
    "crosswalk_applied": False,
    "candidate_cover_types_produced": False,
    "candidate_polygons_produced": False,
}

_NO_CLASSIFICATION_STMT = (
    "This report is a pre-classification source inspection only. "
    "No candidate cover type, forest-land determination, crosswalk, "
    "polygon, or stand assignment has been made. "
    "Professional forestry and GIS review is required before any "
    "classification work begins."
)

_EVT_LABEL_NOTE = (
    "LF2025 EVT per-code labels are resolved from the public LANDFIRE ADD CSV "
    "(LF2025_EVT.csv) when a valid local cache exists. "
    "Labels are unavailable only when the cache is absent and the download fails."
)

# ---------------------------------------------------------------------------
# Slice 2b — LF2025 EVT reference-label join
# ---------------------------------------------------------------------------

# Fixed allowlisted URL for the LF2025 EVT Attribute Data Dictionary CSV.
LF2025_EVT_ADD_URL = (
    "https://landfire.gov/sites/default/files/CSV/LF2025/LF2025_EVT.csv"
)

# Path relative to project_data/ root.
LF2025_EVT_ADD_CACHE_RELPATH = Path(
    "reference_data", "landfire", "LF2025_EVT.csv"
)

# Columns required in the ADD CSV.
_LF2025_EVT_ADD_REQUIRED_COLS = {"VALUE", "EVT_NAME", "EVT_LF", "EVT_PHYS", "EVT_GP_N", "SAF_SRM"}

# Columns to copy into the inventory (in output order).
_LF2025_EVT_LABEL_COLS = ("EVT_NAME", "EVT_LF", "EVT_PHYS", "EVT_GP_N", "SAF_SRM")

LF2025_EVT_ADD_MAX_BYTES = 20_000_000   # 20 MB guard
LF2025_EVT_ADD_RETRY = 2                # download attempts
LF2025_EVT_ADD_TIMEOUT = 60.0           # seconds

# EVT fill / NoData VALUE in the ADD CSV — not an observed vegetation class.
_LF2025_EVT_ADD_FILL_VALUE = -9999

# Project-data root (sibling of outputs/).
_PROJECT_DATA_DIR = Path(__file__).resolve().parent / "project_data"


def _load_lf2025_evt_labels(
    cache_dir: Path = _PROJECT_DATA_DIR,
) -> tuple:
    """Download or read the LF2025 EVT ADD CSV and return a label map.

    Returns:
        (label_map, provenance, error_msg)

        label_map  : dict[int, dict] mapping EVT VALUE -> {EVT_NAME, EVT_LF,
                     EVT_PHYS, EVT_GP_N, SAF_SRM}.  Empty on failure.
        provenance : dict with url, source ('cache'|'download'), download_date,
                     sha256, row_count, cache_path, contact_email_supplied.
        error_msg  : non-empty string on failure, empty string on success.

    Never raises.  All error conditions return gracefully with an empty map.
    The raw contact-email rule does not apply to this public CSV; no email is
    required.  contact_email_supplied is always False.
    """
    import hashlib

    cache_path = (cache_dir / LF2025_EVT_ADD_CACHE_RELPATH).resolve()
    provenance: dict = {
        "url": LF2025_EVT_ADD_URL,
        "source": None,
        "download_date": None,
        "sha256": None,
        "row_count": None,
        "cache_path": str(cache_path),
        "contact_email_supplied": False,
    }

    # --- Try cache first ----------------------------------------------------
    raw_bytes: bytes | None = None
    if cache_path.is_file():
        try:
            raw_bytes = cache_path.read_bytes()
            provenance["source"] = "cache"
            provenance["download_date"] = "cached"
        except OSError as exc:
            return {}, provenance, f"Cache read failed: {exc}"
    else:
        # --- Download -----------------------------------------------------------
        last_error = ""
        for attempt in range(LF2025_EVT_ADD_RETRY):
            try:
                with httpx.Client(
                    timeout=LF2025_EVT_ADD_TIMEOUT,
                    follow_redirects=False,
                ) as client:
                    resp = client.get(LF2025_EVT_ADD_URL)
                    resp.raise_for_status()
                    if resp.is_redirect:
                        last_error = "Server redirected; refusing to follow unreviewed URL."
                        break
                    if len(resp.content) > LF2025_EVT_ADD_MAX_BYTES:
                        last_error = (
                            f"LF2025 EVT ADD CSV response exceeded the "
                            f"{LF2025_EVT_ADD_MAX_BYTES // 1_000_000} MB limit."
                        )
                        break
                    raw_bytes = resp.content
                    provenance["source"] = "download"
                    provenance["download_date"] = (
                        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    )
                    last_error = ""
                    break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                if attempt < LF2025_EVT_ADD_RETRY - 1:
                    time.sleep(1)

        if raw_bytes is None:
            return (
                {},
                provenance,
                f"LF2025 EVT ADD CSV download failed after "
                f"{LF2025_EVT_ADD_RETRY} attempt(s): {last_error}",
            )

        # Atomic write to cache (write to .part then rename).
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            part_path = cache_path.with_suffix(".csv.part")
            part_path.write_bytes(raw_bytes)
            part_path.replace(cache_path)
        except OSError as exc:
            # Non-fatal: continue with in-memory bytes, skip cache.
            provenance["cache_path"] = f"write_failed: {exc}"

    # --- Checksum -----------------------------------------------------------
    digest = hashlib.sha256(raw_bytes).hexdigest()
    provenance["sha256"] = digest

    # --- Parse --------------------------------------------------------------
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return {}, provenance, f"LF2025 EVT ADD CSV decode failed: {exc}"

    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        return {}, provenance, "LF2025 EVT ADD CSV appears to be empty."

    present_cols = set(reader.fieldnames)
    missing_cols = _LF2025_EVT_ADD_REQUIRED_COLS - present_cols
    if missing_cols:
        return (
            {},
            provenance,
            f"LF2025 EVT ADD CSV is missing required columns: {sorted(missing_cols)}",
        )

    label_map: dict[int, dict] = {}
    duplicate_codes: list[int] = []
    row_count = 0
    for row in reader:
        row_count += 1
        try:
            code = int(row["VALUE"])
        except (ValueError, KeyError):
            continue
        if code == _LF2025_EVT_ADD_FILL_VALUE:
            # -9999 is Fill-NoData in the ADD CSV, not a vegetation class.
            continue
        entry = {col.lower(): row.get(col, "") for col in _LF2025_EVT_LABEL_COLS}
        if code in label_map:
            duplicate_codes.append(code)
        else:
            label_map[code] = entry

    provenance["row_count"] = row_count

    if duplicate_codes:
        return (
            {},
            provenance,
            f"LF2025 EVT ADD CSV contains duplicate non-NoData VALUE rows for "
            f"codes: {sorted(set(duplicate_codes))}. "
            "Cannot silently choose between duplicate rows.",
        )

    return label_map, provenance, ""


# EPSG codes confirmed to use metres in a planar equal-area projection
# suitable for direct cell-area calculation in this prototype.
_METRE_EPSG_SAFE = {5070}


def _safe_cell_area(transform, crs) -> tuple:
    """Return (cell_area_m2, cell_area_acres, limitation_note).

    Uses the full affine determinant:
        abs(transform.a * transform.e - transform.b * transform.d)

    Returns (None, None, note) when area cannot be safely computed.
    """
    try:
        epsg = crs.to_epsg() if crs is not None else None
        if epsg not in _METRE_EPSG_SAFE:
            return (
                None,
                None,
                "Cell area in square metres and acres cannot be safely "
                "calculated for the raster CRS. "
                "Reported cell counts cannot be converted to acreage.",
            )
        det = abs(transform.a * transform.e - transform.b * transform.d)
        if not math.isfinite(det) or det <= 0:
            return (
                None,
                None,
                "Affine determinant is invalid; cell area cannot be computed.",
            )
        acres = det / 4046.8564224
        return (det, acres, None)
    except Exception as exc:  # pylint: disable=broad-except
        return (None, None, f"Cell area computation error: {exc}")


def _parse_xml_product_info(xml_path) -> dict:
    """Parse citation and VALUE-attribute domain from one LANDFIRE XML file.

    Returns a dict with keys:
        title, edition, pubdate, doi,
        value_attr_definition, value_domain_type,
        value_domain_min, value_domain_max, value_domain_description,
        classnames_definition, classnames_domain_description,
        parse_status  ('parsed' | 'partial' | 'failed')
    """
    result = {
        "title": None,
        "edition": None,
        "pubdate": None,
        "doi": None,
        "value_attr_definition": None,
        "value_domain_type": "unknown",
        "value_domain_min": None,
        "value_domain_max": None,
        "value_domain_description": None,
        "classnames_definition": None,
        "classnames_domain_description": None,
        "parse_status": "failed",
    }
    if xml_path is None or not Path(xml_path).is_file():
        return result
    try:
        tree = _ET.parse(str(xml_path))
        root = tree.getroot()

        def _text(path):
            el = root.find(path)
            return el.text.strip() if el is not None and el.text else None

        result["title"] = _text(".//idinfo/citation/citeinfo/title")
        result["edition"] = _text(".//idinfo/citation/citeinfo/edition")
        result["pubdate"] = _text(".//idinfo/citation/citeinfo/pubdate")

        # First onlink containing doi.org
        for el in root.findall(".//idinfo/citation/citeinfo/onlink"):
            if el.text and "doi.org" in el.text:
                result["doi"] = el.text.strip()
                break

        # Walk <eainfo>/<detailed>/<attr> elements
        for attr in root.findall(".//eainfo/detailed/attr"):
            label_el = attr.find("attrlabl")
            label = label_el.text.strip() if label_el is not None and label_el.text else ""

            if label == "VALUE":
                attrdef_el = attr.find("attrdef")
                result["value_attr_definition"] = (
                    attrdef_el.text.strip()
                    if attrdef_el is not None and attrdef_el.text
                    else None
                )
                # Scan all <attrdomv> children.  Prefer <rdom> (numeric
                # range) over <edom> (enumerated entry) when both are
                # present — the LF2025 XMLs place the NoData <edom> first
                # and the <rdom> second for the VALUE attribute.
                found_rdom = None
                found_edom_text = None
                found_udom_text = None
                for domv in attr.findall("attrdomv"):
                    rdom = domv.find("rdom")
                    edom = domv.find("edom")
                    udom = domv.find("udom")
                    if rdom is not None and found_rdom is None:
                        found_rdom = rdom
                    if edom is not None and found_edom_text is None:
                        edomvd = edom.find("edomvd")
                        found_edom_text = (
                            edomvd.text.strip()
                            if edomvd is not None and edomvd.text
                            else ""
                        )
                    if udom is not None and found_udom_text is None:
                        found_udom_text = udom.text.strip() if udom.text else ""

                if found_rdom is not None:
                    result["value_domain_type"] = "range"
                    rmin = found_rdom.find("rdommin")
                    rmax = found_rdom.find("rdommax")
                    try:
                        result["value_domain_min"] = float(rmin.text) if rmin is not None and rmin.text else None
                        result["value_domain_max"] = float(rmax.text) if rmax is not None and rmax.text else None
                    except ValueError:
                        pass
                elif found_udom_text is not None:
                    result["value_domain_type"] = "unrepresented"
                    result["value_domain_description"] = found_udom_text
                elif found_edom_text is not None:
                    result["value_domain_type"] = "enumerated"
                    result["value_domain_description"] = found_edom_text

            elif label == "CLASSNAMES":
                attrdef_el = attr.find("attrdef")
                result["classnames_definition"] = (
                    attrdef_el.text.strip()
                    if attrdef_el is not None and attrdef_el.text
                    else None
                )
                for domv in attr.findall("attrdomv"):
                    udom = domv.find("udom")
                    if udom is not None and udom.text:
                        result["classnames_domain_description"] = udom.text.strip()
                        break

        result["parse_status"] = "parsed"
    except _ET.ParseError as exc:
        result["parse_status"] = "failed"
        result["_parse_error"] = str(exc)
    except Exception as exc:  # pylint: disable=broad-except
        result["parse_status"] = "partial"
        result["_parse_error"] = str(exc)
    return result


def _classify_value_against_domain(
    val: int,
    nodata_val,
    domain_type: str,
    domain_min,
    domain_max,
) -> str:
    """Return the domain membership category for one observed raster value.

    Categories:
        nodata                    — equals the band nodata sentinel
        defined_in_enumeration    — found in an explicit edom list (future)
        within_numeric_range_only — inside <rdom> but not enumerated
        outside_numeric_range     — outside <rdom> and not nodata
        metadata_domain_unavailable — no domain info available
    """
    if nodata_val is not None and val == int(nodata_val):
        return "nodata"
    if domain_type == "enumerated":
        # Enumerated entries from the actual LF2025 XMLs are only the
        # -9999 NoData sentinel; integer codes are in the external CSV.
        # Treat as within-range-only when a numeric range is also declared.
        return "within_numeric_range_only"
    if domain_type == "range" and domain_min is not None and domain_max is not None:
        if domain_min <= val <= domain_max:
            return "within_numeric_range_only"
        return "outside_numeric_range"
    return "metadata_domain_unavailable"


def _read_band_array(src, band_index: int):
    """Read one 1-based raster band as a flat int32 NumPy array."""
    try:
        import numpy as np  # transitive dep via rasterio
        arr = src.read(band_index).astype(np.int32).ravel()
        return arr, np, None
    except ImportError:
        return None, None, "numpy_unavailable"


def _band_stats(arr, nodata_val, np):
    """Return (nodata_count, valid_arr, valid_count, unique_vals, unique_counts).

    All counts are Python ints; unique_vals/counts are Python lists.
    """
    nodata_int = int(nodata_val) if nodata_val is not None else None
    if nodata_int is not None:
        mask = arr != nodata_int
    else:
        mask = np.ones(arr.shape, dtype=bool)
    nodata_count = int((~mask).sum())
    valid_arr = arr[mask]
    valid_count = int(valid_arr.size)
    if valid_count > 0:
        uvals, ucounts = np.unique(valid_arr, return_counts=True)
        return nodata_count, valid_arr, valid_count, uvals.tolist(), ucounts.tolist()
    return nodata_count, valid_arr, valid_count, [], []


def _inspect_landfire_v2_inputs(manifest: dict, manifest_path: Path) -> dict:
    """Read-only inspection of a collected LF2025 EVT/EVC/EVH GeoTIFF.

    Returns a complete report dict.  Never writes files.  Never makes
    network calls.  Never classifies.  All sentinel fields are always False.
    """
    warnings_list = []
    report = dict(_SLICE2_SENTINELS)
    report["inspection_status"] = "failed"
    report["inspected_at_utc"] = datetime.now(timezone.utc).isoformat()

    # --- Provenance from manifest -------------------------------------------
    job_id = manifest.get("job_id", "unknown")
    api_version = manifest.get("api_version", "unknown")
    geotiff_file = manifest.get("geotiff_file")
    xml_map = manifest.get("expected_metadata_xml_files", {})  # name -> path

    # Resolve XML paths by matching key substrings
    evt_xml = None
    evc_xml = None
    evh_xml = None
    for key, val in xml_map.items():
        ku = key.upper()
        if "EVT" in ku:
            evt_xml = val
        elif "EVC" in ku:
            evc_xml = val
        elif "EVH" in ku:
            evh_xml = val

    report["collection_manifest_file"] = str(manifest_path)
    report["geotiff_file"] = geotiff_file
    report["evt_xml_file"] = evt_xml
    report["evc_xml_file"] = evc_xml
    report["evh_xml_file"] = evh_xml
    report["job_id"] = job_id
    report["api_version"] = api_version

    for label, xpath in [("EVT", evt_xml), ("EVC", evc_xml), ("EVH", evh_xml)]:
        if not xpath or not Path(xpath).is_file():
            warnings_list.append(
                f"{label} XML metadata file is missing or not found: {xpath}"
            )

    # --- Open raster --------------------------------------------------------
    if not geotiff_file or not Path(geotiff_file).is_file():
        report["inspection_status"] = "failed"
        report["warnings"] = warnings_list + [
            f"GeoTIFF not found: {geotiff_file}",
            _NO_CLASSIFICATION_STMT,
        ]
        return report

    try:
        src_context = rasterio.open(str(geotiff_file))
    except Exception as exc:
        report["inspection_status"] = "failed"
        report["warnings"] = warnings_list + [
            f"Could not open GeoTIFF: {exc}",
            _NO_CLASSIFICATION_STMT,
        ]
        return report

    with src_context as src:
        width = src.width
        height = src.height
        band_count = src.count
        crs = src.crs
        transform = src.transform
        descriptions = src.descriptions  # tuple, 0-indexed, may contain None
        nodata_shared = src.nodata
        # Per-band nodata if available (rasterio >= 1.3)
        try:
            nodata_vals = list(src.nodatavals)
        except AttributeError:
            nodata_vals = [nodata_shared] * band_count

        # --- Band identification -------------------------------------------
        band_id = {}  # keyword -> 1-based index
        band_desc_stored = {}
        band_confidence = {}
        for keyword in ("EVT", "EVC", "EVH"):
            matches = []
            for i, desc in enumerate(descriptions):
                if desc and keyword in desc.upper():
                    matches.append((i + 1, desc))  # 1-based
            if len(matches) == 1:
                idx, desc = matches[0]
                band_id[keyword] = idx
                band_desc_stored[keyword] = desc
                band_confidence[keyword] = (
                    "exact" if keyword in (desc or "") else "case_insensitive"
                )
            elif len(matches) == 0:
                band_id[keyword] = None
                band_desc_stored[keyword] = None
                band_confidence[keyword] = "not_found"
            else:
                band_id[keyword] = None
                band_desc_stored[keyword] = [d for _, d in matches]
                band_confidence[keyword] = "ambiguous"

        band_id_section = {
            "band_identification_method": "description_matching",
            "EVT": {
                "band_index_found": band_id.get("EVT"),
                "band_description_stored": band_desc_stored.get("EVT"),
                "match_confidence": band_confidence.get("EVT"),
            },
            "EVC": {
                "band_index_found": band_id.get("EVC"),
                "band_description_stored": band_desc_stored.get("EVC"),
                "match_confidence": band_confidence.get("EVC"),
            },
            "EVH": {
                "band_index_found": band_id.get("EVH"),
                "band_description_stored": band_desc_stored.get("EVH"),
                "match_confidence": band_confidence.get("EVH"),
            },
        }

        failed_bands = [
            k for k in ("EVT", "EVC", "EVH")
            if band_confidence.get(k) in ("not_found", "ambiguous")
        ]
        if failed_bands:
            band_id_section["band_identification_status"] = "failed"
            report["band_identification"] = band_id_section
            report["inspection_status"] = "failed"
            report["warnings"] = warnings_list + [
                f"Band identification failed for: {', '.join(failed_bands)}. "
                "No raster data was read.",
                _NO_CLASSIFICATION_STMT,
            ]
            return report
        band_id_section["band_identification_status"] = "all_identified"
        report["band_identification"] = band_id_section

        # --- CRS and cell area ---------------------------------------------
        crs_epsg = None
        crs_wkt = None
        try:
            crs_epsg = crs.to_epsg() if crs is not None else None
            crs_wkt = crs.to_wkt() if crs is not None else None
        except Exception:
            pass

        cell_area_m2, cell_area_acres, area_limit = _safe_cell_area(transform, crs)
        if area_limit:
            warnings_list.append(area_limit)

        bounds = src.bounds
        raster_geometry = {
            "width_pixels": width,
            "height_pixels": height,
            "total_cells": width * height,
            "crs_epsg": crs_epsg,
            "crs_wkt": crs_wkt,
            "affine_transform": {
                "a": transform.a,
                "b": transform.b,
                "c": transform.c,
                "d": transform.d,
                "e": transform.e,
                "f": transform.f,
            },
            "cell_size_x_map_units": transform.a,
            "cell_size_y_map_units": transform.e,
            "cell_area_map_units_sq": abs(
                transform.a * transform.e - transform.b * transform.d
            ),
            "cell_area_m2": cell_area_m2,
            "cell_area_acres": cell_area_acres,
            "cell_area_limitation": area_limit,
            "bounding_box_native_crs": {
                "west": bounds.left,
                "south": bounds.bottom,
                "east": bounds.right,
                "north": bounds.top,
            },
        }
        report["raster_geometry"] = raster_geometry

        # --- Alignment checks ----------------------------------------------
        # All bands are in a single file; geometry is shared by construction.
        # We check band-level metadata consistency explicitly.
        evt_nodata = nodata_vals[band_id["EVT"] - 1] if nodata_vals else nodata_shared
        evc_nodata = nodata_vals[band_id["EVC"] - 1] if nodata_vals else nodata_shared
        evh_nodata = nodata_vals[band_id["EVH"] - 1] if nodata_vals else nodata_shared

        alignment = {
            "dimensions_match": True,   # single file
            "crs_match": True,
            "transform_match": True,
            "extent_match": True,
            "resolution_match": True,
            "source_note": (
                "All three bands reside in a single multi-band GeoTIFF. "
                "Spatial geometry is shared by construction. "
                "Band-level NoData values are recorded separately."
            ),
            "evt_nodata_value": evt_nodata,
            "evc_nodata_value": evc_nodata,
            "evh_nodata_value": evh_nodata,
        }
        report["alignment_checks"] = alignment

        # --- Parse XML metadata for all three products --------------------
        evt_xml_info = _parse_xml_product_info(evt_xml)
        evc_xml_info = _parse_xml_product_info(evc_xml)
        evh_xml_info = _parse_xml_product_info(evh_xml)

        for label, info in [("EVT", evt_xml_info), ("EVC", evc_xml_info), ("EVH", evh_xml_info)]:
            if info["parse_status"] != "parsed":
                warnings_list.append(
                    f"{label} XML parse status: {info['parse_status']}. "
                    + info.get("_parse_error", "")
                )

        report["evt_xml_metadata"] = {k: v for k, v in evt_xml_info.items() if not k.startswith("_")}
        report["evc_xml_metadata"] = {k: v for k, v in evc_xml_info.items() if not k.startswith("_")}
        report["evh_xml_metadata"] = {k: v for k, v in evh_xml_info.items() if not k.startswith("_")}

        # --- Read EVT band -------------------------------------------------
        evt_arr, np_mod, np_err = _read_band_array(src, band_id["EVT"])
        if np_err or np_mod is None:
            report["inspection_status"] = "failed"
            report["warnings"] = warnings_list + [
                f"Could not read EVT band array: {np_err}",
                _NO_CLASSIFICATION_STMT,
            ]
            return report

        total_cells = int(evt_arr.size)
        evt_nd_count, evt_valid_arr, evt_valid_count, evt_uvals, evt_ucounts = (
            _band_stats(evt_arr, evt_nodata, np_mod)
        )
        evt_nd_acres = (
            evt_nd_count * cell_area_acres if cell_area_acres is not None else None
        )

        evt_value_domain = {
            "value_domain_type": evt_xml_info["value_domain_type"],
            "value_domain_min": evt_xml_info["value_domain_min"],
            "value_domain_max": evt_xml_info["value_domain_max"],
        }

        evt_codes_outside = []
        evt_codes_observed = []
        for code, count in zip(evt_uvals, evt_ucounts):
            domain_status = _classify_value_against_domain(
                code,
                evt_nodata,
                evt_xml_info["value_domain_type"],
                evt_xml_info["value_domain_min"],
                evt_xml_info["value_domain_max"],
            )
            if domain_status == "outside_numeric_range":
                evt_codes_outside.append(int(code))
                warnings_list.append(
                    f"EVT observed code {code} is outside the XML-declared "
                    f"domain range "
                    f"[{evt_xml_info['value_domain_min']}, "
                    f"{evt_xml_info['value_domain_max']}]."
                )
            sq_m = int(count) * cell_area_m2 if cell_area_m2 is not None else None
            acres_val = int(count) * cell_area_acres if cell_area_acres is not None else None
            frac = round(int(count) / evt_valid_count, 6) if evt_valid_count > 0 else None
            evt_codes_observed.append({
                "evt_code": int(code),
                "cell_count": int(count),
                "square_meters": round(sq_m, 2) if sq_m is not None else None,
                "acres": round(acres_val, 4) if acres_val is not None else None,
                "valid_cell_fraction": frac,
                "evt_name": None,
                "evt_name_source": None,
                "label_missing": True,
                "evt_lf": None,
                "evt_phys": None,
                "evt_gp_n": None,
                "saf_srm": None,
                "domain_membership": domain_status,
                "source_tif": str(geotiff_file),
                "source_xml": str(evt_xml) if evt_xml else None,
            })

        # --- EVT label join (Slice 2b) -------------------------------------
        label_map, evt_add_prov, label_err = _load_lf2025_evt_labels()
        if label_err:
            warnings_list.append(
                f"Reference-data warning: LF2025 EVT ADD CSV not available — "
                f"labels not resolved. Attempted URL: {LF2025_EVT_ADD_URL}. "
                f"Error: {label_err}"
            )
            # inspection_status will be set to partial below (label_missing=true for all)
        else:
            for entry in evt_codes_observed:
                code_int = entry["evt_code"]
                lbl = label_map.get(code_int)
                if lbl is not None:
                    entry["evt_name"] = lbl["evt_name"]
                    entry["evt_name_source"] = "LF2025_EVT.csv"
                    entry["label_missing"] = False
                    entry["evt_lf"] = lbl["evt_lf"]
                    entry["evt_phys"] = lbl["evt_phys"]
                    entry["evt_gp_n"] = lbl["evt_gp_n"]
                    entry["saf_srm"] = lbl["saf_srm"]
                else:
                    warnings_list.append(
                        f"EVT label not found for code {code_int} in "
                        f"LF2025_EVT.csv — label_missing=true."
                    )

        report["evt_band"] = {
            "nodata_value": evt_nodata,
            "nodata_cell_count": evt_nd_count,
            "nodata_acres": round(evt_nd_acres, 4) if evt_nd_acres is not None else None,
            "valid_cell_count": evt_valid_count,
            "total_cells": total_cells,
            "value_domain_from_xml": evt_value_domain,
            "evt_label_availability_note": _EVT_LABEL_NOTE,
            "evt_add_provenance": evt_add_prov,
            "evt_codes_outside_xml_domain": evt_codes_outside,
            "evt_codes_observed": evt_codes_observed,
        }

        # --- Read EVC band -------------------------------------------------
        evc_arr, _, _ = _read_band_array(src, band_id["EVC"])
        evc_nd_count, evc_valid_arr, evc_valid_count, evc_uvals, evc_ucounts = (
            _band_stats(evc_arr, evc_nodata, np_mod)
        )
        evc_nd_acres = (
            evc_nd_count * cell_area_acres if cell_area_acres is not None else None
        )
        evc_obs_min = int(evc_valid_arr.min()) if evc_valid_count > 0 else None
        evc_obs_max = int(evc_valid_arr.max()) if evc_valid_count > 0 else None

        evc_value_domain = {
            "value_domain_type": evc_xml_info["value_domain_type"],
            "value_domain_min": evc_xml_info["value_domain_min"],
            "value_domain_max": evc_xml_info["value_domain_max"],
        }

        evc_codes_outside = []
        evc_value_counts = []
        for code, count in zip(evc_uvals, evc_ucounts):
            domain_status = _classify_value_against_domain(
                code,
                evc_nodata,
                evc_xml_info["value_domain_type"],
                evc_xml_info["value_domain_min"],
                evc_xml_info["value_domain_max"],
            )
            if domain_status == "outside_numeric_range":
                evc_codes_outside.append(int(code))
                warnings_list.append(
                    f"EVC observed code {code} is outside the XML-declared "
                    f"domain range "
                    f"[{evc_xml_info['value_domain_min']}, "
                    f"{evc_xml_info['value_domain_max']}]."
                )
            sq_m = int(count) * cell_area_m2 if cell_area_m2 is not None else None
            acres_val = int(count) * cell_area_acres if cell_area_acres is not None else None
            frac = round(int(count) / evc_valid_count, 6) if evc_valid_count > 0 else None
            evc_value_counts.append({
                "evc_code": int(code),
                "cell_count": int(count),
                "square_meters": round(sq_m, 2) if sq_m is not None else None,
                "acres": round(acres_val, 4) if acres_val is not None else None,
                "valid_cell_fraction": frac,
                "domain_membership": domain_status,
            })

        report["evc_band"] = {
            "nodata_value": evc_nodata,
            "nodata_cell_count": evc_nd_count,
            "nodata_acres": round(evc_nd_acres, 4) if evc_nd_acres is not None else None,
            "valid_cell_count": evc_valid_count,
            "total_cells": total_cells,
            "value_domain_from_xml": evc_value_domain,
            "value_encoding_note": evc_xml_info["classnames_domain_description"],
            "observed_min": evc_obs_min,
            "observed_max": evc_obs_max,
            "evc_codes_outside_xml_domain": evc_codes_outside,
            "evc_value_counts": evc_value_counts,
            "evc_xml_parse_status": evc_xml_info["parse_status"],
            "statistics_note": (
                "Mean, median, and standard deviation are not reported for "
                "EVC encoded class codes. Values represent encoded lifeform "
                "cover classes, not percent canopy cover."
            ),
        }

        # --- Read EVH band -------------------------------------------------
        evh_arr, _, _ = _read_band_array(src, band_id["EVH"])
        evh_nd_count, evh_valid_arr, evh_valid_count, evh_uvals, evh_ucounts = (
            _band_stats(evh_arr, evh_nodata, np_mod)
        )
        evh_nd_acres = (
            evh_nd_count * cell_area_acres if cell_area_acres is not None else None
        )
        evh_obs_min = int(evh_valid_arr.min()) if evh_valid_count > 0 else None
        evh_obs_max = int(evh_valid_arr.max()) if evh_valid_count > 0 else None

        evh_value_domain = {
            "value_domain_type": evh_xml_info["value_domain_type"],
            "value_domain_min": evh_xml_info["value_domain_min"],
            "value_domain_max": evh_xml_info["value_domain_max"],
        }

        evh_codes_outside = []
        evh_value_counts = []
        for code, count in zip(evh_uvals, evh_ucounts):
            domain_status = _classify_value_against_domain(
                code,
                evh_nodata,
                evh_xml_info["value_domain_type"],
                evh_xml_info["value_domain_min"],
                evh_xml_info["value_domain_max"],
            )
            if domain_status == "outside_numeric_range":
                evh_codes_outside.append(int(code))
                warnings_list.append(
                    f"EVH observed code {code} is outside the XML-declared "
                    f"domain range "
                    f"[{evh_xml_info['value_domain_min']}, "
                    f"{evh_xml_info['value_domain_max']}]."
                )
            sq_m = int(count) * cell_area_m2 if cell_area_m2 is not None else None
            acres_val = int(count) * cell_area_acres if cell_area_acres is not None else None
            frac = round(int(count) / evh_valid_count, 6) if evh_valid_count > 0 else None
            evh_value_counts.append({
                "evh_code": int(code),
                "cell_count": int(count),
                "square_meters": round(sq_m, 2) if sq_m is not None else None,
                "acres": round(acres_val, 4) if acres_val is not None else None,
                "valid_cell_fraction": frac,
                "domain_membership": domain_status,
            })

        report["evh_band"] = {
            "nodata_value": evh_nodata,
            "nodata_cell_count": evh_nd_count,
            "nodata_acres": round(evh_nd_acres, 4) if evh_nd_acres is not None else None,
            "valid_cell_count": evh_valid_count,
            "total_cells": total_cells,
            "value_domain_from_xml": evh_value_domain,
            "value_encoding_note": evh_xml_info["classnames_domain_description"],
            "observed_min": evh_obs_min,
            "observed_max": evh_obs_max,
            "evh_codes_outside_xml_domain": evh_codes_outside,
            "evh_value_counts": evh_value_counts,
            "evh_xml_parse_status": evh_xml_info["parse_status"],
            "statistics_note": (
                "Mean, median, and standard deviation are not reported for "
                "EVH encoded class codes. Values represent encoded height "
                "classes, not vegetation height in metres."
            ),
        }

        # --- Valid-data overlap --------------------------------------------
        nd_evt = int(evt_nodata) if evt_nodata is not None else None
        nd_evc = int(evc_nodata) if evc_nodata is not None else None
        nd_evh = int(evh_nodata) if evh_nodata is not None else None
        mask_evt = evt_arr != nd_evt if nd_evt is not None else np_mod.ones(total_cells, dtype=bool)
        mask_evc = evc_arr != nd_evc if nd_evc is not None else np_mod.ones(total_cells, dtype=bool)
        mask_evh = evh_arr != nd_evh if nd_evh is not None else np_mod.ones(total_cells, dtype=bool)
        overlap_count = int((mask_evt & mask_evc & mask_evh).sum())
        overlap_acres = (
            overlap_count * cell_area_acres if cell_area_acres is not None else None
        )
        alignment["valid_data_overlap_cells"] = overlap_count
        alignment["valid_data_overlap_acres"] = (
            round(overlap_acres, 4) if overlap_acres is not None else None
        )

    # --- Determine final status -------------------------------------------
    any_xml_missing = any(
        not p or not Path(p).is_file()
        for p in [evt_xml, evc_xml, evh_xml]
    )
    any_parse_fail = any(
        info["parse_status"] != "parsed"
        for info in [evt_xml_info, evc_xml_info, evh_xml_info]
    )
    any_outside = bool(
        evt_codes_outside or evc_codes_outside or evh_codes_outside
    )
    any_labels_missing = any(
        entry.get("label_missing", True)
        for entry in report.get("evt_band", {}).get("evt_codes_observed", [])
    )
    if any_xml_missing or any_parse_fail or any_outside or any_labels_missing:
        report["inspection_status"] = "partial"
    else:
        report["inspection_status"] = "success"

    warnings_list.append(_EVT_LABEL_NOTE)
    warnings_list.append(_NO_CLASSIFICATION_STMT)
    report["warnings"] = warnings_list
    return report


def _build_markdown_report(report: dict, job_id: str) -> str:
    """Render the inspection report dict as a Markdown document."""
    lines = []
    a = lines.append

    status = report.get("inspection_status", "unknown")
    a(f"# LF2025 Cover-Type Input Inspection Report")
    a(f"")
    a(f"**Inspection status:** `{status}`  ")
    a(f"**Inspected at (UTC):** {report.get('inspected_at_utc', 'unknown')}  ")
    a(f"**Job ID:** {job_id}  ")
    a(f"**API version:** {report.get('api_version', 'unknown')}  ")
    a(f"")

    a(f"## No-Classification Sentinels")
    a(f"")
    a(f"| Field | Value |")
    a(f"|---|---|")
    for k in (
        "classification_performed",
        "forest_land_determination_performed",
        "crosswalk_applied",
        "candidate_cover_types_produced",
        "candidate_polygons_produced",
    ):
        a(f"| `{k}` | `{report.get(k)}` |")
    a(f"")

    # Source files
    a(f"## Source Files")
    a(f"")
    a(f"- **Collection manifest:** `{report.get('collection_manifest_file')}`")
    a(f"- **GeoTIFF:** `{report.get('geotiff_file')}`")
    a(f"- **EVT XML:** `{report.get('evt_xml_file')}`")
    a(f"- **EVC XML:** `{report.get('evc_xml_file')}`")
    a(f"- **EVH XML:** `{report.get('evh_xml_file')}`")
    a(f"")

    # XML product metadata per band
    a(f"## Source Product Metadata (from XML)")
    a(f"")
    for label, key in [("EVT", "evt_xml_metadata"), ("EVC", "evc_xml_metadata"), ("EVH", "evh_xml_metadata")]:
        info = report.get(key, {})
        a(f"### {label}")
        a(f"- **Title:** {info.get('title')}")
        a(f"- **Edition:** {info.get('edition')}")
        a(f"- **Publication date:** {info.get('pubdate')}")
        a(f"- **DOI:** {info.get('doi')}")
        a(f"- **VALUE attribute definition:** {info.get('value_attr_definition')}")
        a(f"- **VALUE domain type:** `{info.get('value_domain_type')}`")
        a(f"- **VALUE domain range:** {info.get('value_domain_min')} – {info.get('value_domain_max')}")
        a(f"- **CLASSNAMES description:** {info.get('classnames_domain_description')}")
        a(f"- **XML parse status:** `{info.get('parse_status')}`")
        a(f"")

    # Band identification
    bi = report.get("band_identification", {})
    a(f"## Band Identification")
    a(f"")
    a(f"**Method:** {bi.get('band_identification_method')}  ")
    a(f"**Status:** `{bi.get('band_identification_status')}`  ")
    a(f"")
    a(f"| Band | Index | Stored Description | Confidence |")
    a(f"|---|---|---|---|")
    for bk in ("EVT", "EVC", "EVH"):
        bd = bi.get(bk, {})
        a(f"| {bk} | {bd.get('band_index_found')} | `{bd.get('band_description_stored')}` | {bd.get('match_confidence')} |")
    a(f"")

    # Raster geometry
    rg = report.get("raster_geometry", {})
    a(f"## Raster Geometry")
    a(f"")
    a(f"- **Dimensions:** {rg.get('width_pixels')} × {rg.get('height_pixels')} pixels ({rg.get('total_cells')} total cells)")
    a(f"- **CRS EPSG:** {rg.get('crs_epsg')}")
    tr = rg.get("affine_transform", {})
    a(f"- **Affine transform:** a={tr.get('a')}, b={tr.get('b')}, c={tr.get('c')}, d={tr.get('d')}, e={tr.get('e')}, f={tr.get('f')}")
    a(f"- **Cell size (map units):** x={rg.get('cell_size_x_map_units')}, y={rg.get('cell_size_y_map_units')}")
    a(f"- **Cell area (affine det, map units²):** {rg.get('cell_area_map_units_sq')}")
    a(f"- **Cell area m²:** {rg.get('cell_area_m2')}")
    a(f"- **Cell area acres:** {rg.get('cell_area_acres')}")
    if rg.get("cell_area_limitation"):
        a(f"- ⚠️ **Area limitation:** {rg.get('cell_area_limitation')}")
    bb = rg.get("bounding_box_native_crs", {})
    a(f"- **Bounding box (native CRS):** W={bb.get('west')}, S={bb.get('south')}, E={bb.get('east')}, N={bb.get('north')}")
    a(f"")

    # Alignment
    al = report.get("alignment_checks", {})
    a(f"## Alignment Checks")
    a(f"")
    a(f"| Check | Result |")
    a(f"|---|---|")
    for ck in ("dimensions_match", "crs_match", "transform_match", "extent_match", "resolution_match"):
        a(f"| {ck} | `{al.get(ck)}` |")
    a(f"| valid_data_overlap_cells | {al.get('valid_data_overlap_cells')} |")
    a(f"| valid_data_overlap_acres | {al.get('valid_data_overlap_acres')} |")
    a(f"")
    a(f"*{al.get('source_note', '')}*")
    a(f"")

    # EVT code inventory
    evt = report.get("evt_band", {})
    a(f"## EVT Band — Code Inventory")
    a(f"")
    a(f"- **NoData value:** {evt.get('nodata_value')}")
    a(f"- **NoData cell count:** {evt.get('nodata_cell_count')}")
    a(f"- **NoData acres:** {evt.get('nodata_acres')}")
    a(f"- **Valid cell count:** {evt.get('valid_cell_count')}")
    a(f"- **XML domain:** {evt.get('value_domain_from_xml')}")
    a(f"")
    a(f"> **Label availability note:** {evt.get('evt_label_availability_note')}")
    a(f"")
    codes = evt.get("evt_codes_observed", [])
    if codes:
        a(f"| EVT Code | Cell Count | Acres | Valid Fraction | Domain Membership |")
        a(f"|---|---|---|---|---|")
        for row in codes:
            a(
                f"| {row['evt_code']} | {row['cell_count']} "
                f"| {row['acres'] if row['acres'] is not None else 'n/a'} "
                f"| {row['valid_cell_fraction']} "
                f"| {row['domain_membership']} |"
            )
    else:
        a(f"*No valid EVT codes observed (all cells are NoData).*")
    a(f"")
    if evt.get("evt_codes_outside_xml_domain"):
        a(f"⚠️ **Codes outside XML domain:** {evt['evt_codes_outside_xml_domain']}")
        a(f"")

    # EVC band
    evc = report.get("evc_band", {})
    a(f"## EVC Band — Value Distribution")
    a(f"")
    a(f"- **NoData value:** {evc.get('nodata_value')}")
    a(f"- **NoData cell count:** {evc.get('nodata_cell_count')}")
    a(f"- **NoData acres:** {evc.get('nodata_acres')}")
    a(f"- **Valid cell count:** {evc.get('valid_cell_count')}")
    a(f"- **XML domain:** {evc.get('value_domain_from_xml')}")
    a(f"- **Observed min:** {evc.get('observed_min')}  |  **Observed max:** {evc.get('observed_max')}")
    a(f"- **Encoding note:** {evc.get('value_encoding_note')}")
    a(f"- **Statistics note:** {evc.get('statistics_note')}")
    a(f"")
    evc_counts = evc.get("evc_value_counts", [])
    if evc_counts:
        a(f"| EVC Code | Cell Count | Acres | Valid Fraction | Domain Membership |")
        a(f"|---|---|---|---|---|")
        for row in evc_counts:
            a(
                f"| {row['evc_code']} | {row['cell_count']} "
                f"| {row['acres'] if row['acres'] is not None else 'n/a'} "
                f"| {row['valid_cell_fraction']} "
                f"| {row['domain_membership']} |"
            )
    if evc.get("evc_codes_outside_xml_domain"):
        a(f"")
        a(f"⚠️ **Codes outside XML domain:** {evc['evc_codes_outside_xml_domain']}")
    a(f"")

    # EVH band
    evh = report.get("evh_band", {})
    a(f"## EVH Band — Value Distribution")
    a(f"")
    a(f"- **NoData value:** {evh.get('nodata_value')}")
    a(f"- **NoData cell count:** {evh.get('nodata_cell_count')}")
    a(f"- **NoData acres:** {evh.get('nodata_acres')}")
    a(f"- **Valid cell count:** {evh.get('valid_cell_count')}")
    a(f"- **XML domain:** {evh.get('value_domain_from_xml')}")
    a(f"- **Observed min:** {evh.get('observed_min')}  |  **Observed max:** {evh.get('observed_max')}")
    a(f"- **Encoding note:** {evh.get('value_encoding_note')}")
    a(f"- **Statistics note:** {evh.get('statistics_note')}")
    a(f"")
    evh_counts = evh.get("evh_value_counts", [])
    if evh_counts:
        a(f"| EVH Code | Cell Count | Acres | Valid Fraction | Domain Membership |")
        a(f"|---|---|---|---|---|")
        for row in evh_counts:
            a(
                f"| {row['evh_code']} | {row['cell_count']} "
                f"| {row['acres'] if row['acres'] is not None else 'n/a'} "
                f"| {row['valid_cell_fraction']} "
                f"| {row['domain_membership']} |"
            )
    if evh.get("evh_codes_outside_xml_domain"):
        a(f"")
        a(f"⚠️ **Codes outside XML domain:** {evh['evh_codes_outside_xml_domain']}")
    a(f"")

    # Warnings
    a(f"## Warnings")
    a(f"")
    wlist = report.get("warnings", [])
    if wlist:
        for w in wlist:
            a(f"- {w}")
    else:
        a(f"*No warnings.*")
    a(f"")

    a(f"---")
    a(f"")
    a(f"*{_NO_CLASSIFICATION_STMT}*")
    a(f"")

    return "\n".join(lines)


def _build_failure_markdown(report: dict, job_id: str) -> str:
    """Render a failure inspection report as Markdown."""
    lines = []
    a = lines.append
    a(f"# LF2025 Cover-Type Input Inspection — FAILED")
    a(f"")
    a(f"**Inspection status:** `failed`  ")
    a(f"**Inspected at (UTC):** {report.get('inspected_at_utc', 'unknown')}  ")
    a(f"**Job ID:** {job_id}  ")
    a(f"")
    a(f"## No-Classification Sentinels")
    a(f"")
    for k in (
        "classification_performed",
        "forest_land_determination_performed",
        "crosswalk_applied",
        "candidate_cover_types_produced",
        "candidate_polygons_produced",
    ):
        a(f"- `{k}`: `{report.get(k)}`")
    a(f"")
    a(f"## Source Paths")
    a(f"")
    a(f"- **Collection manifest:** `{report.get('collection_manifest_file')}`")
    a(f"- **GeoTIFF:** `{report.get('geotiff_file')}`")
    a(f"")
    a(f"## Failure Details and Warnings")
    a(f"")
    for w in report.get("warnings", []):
        a(f"- {w}")
    a(f"")
    a(f"---")
    a(f"*{_NO_CLASSIFICATION_STMT}*")
    a(f"")
    return "\n".join(lines)


@mcp.tool()
def inspect_landfire_v2_cover_type_inputs(
    collection_manifest_filename: str,
) -> dict:
    """
    Inspect collected LF2025 EVT, EVC, and EVH raster inputs for cover-type
    mapping review.

    This tool reads one previously collected LFPS v2 collection manifest,
    opens the three-band GeoTIFF and co-located XML metadata files it
    references, and produces a durable pre-classification inspection record.

    Prerequisites: A completed LFPS v2 collection (produced by
    collect_landfire_v2_sample_result) with all three metadata XML files
    present in the same extraction folder.

    Outputs written to outputs/:
      - inspect_lf2025_<job_id>_report.md    — human-readable Markdown report
      - inspect_lf2025_<job_id>_summary.json — machine-readable JSON summary
      - inspect_lf2025_<job_id>_evt_inventory.csv — one row per observed EVT
        code (written only when inspection succeeds or is partial)

    Returns: inspection_status (success/partial/failed), paths to artifacts,
    observed EVT codes, EVC/EVH domain summaries, NoData counts, alignment
    checks, and all no-classification sentinel fields.

    Limitations: Does not classify, crosswalk, produce candidate layers, or
    determine forest land. Per-code EVT labels are not available from the
    local LFPS v2 bundle; only the external LF ADD CSV contains them.
    EVC and EVH values are encoded class codes; mean/median/std are not
    reported for encoded classes.

    Failure behavior: On hard failure (unreadable raster, missing GeoTIFF,
    band identification failure) returns a structured failure dict and writes
    Markdown and JSON failure artifacts when safe to do so. EVT CSV is not
    written on failure.
    """
    if not re.fullmatch(
        r"lfps_v2_collection_\d{8}T\d{12}Z_"
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}\.json",
        collection_manifest_filename,
    ):
        raise ToolError(
            "Use the exact generated LFPS v2 collection-manifest filename "
            "only, not a full path."
        )

    folder = OUTPUT_FOLDER.resolve()
    manifest_path = (folder / collection_manifest_filename).resolve()

    if manifest_path.parent != folder:
        raise ToolError(
            "LFPS v2 collection manifest must remain inside the outputs folder."
        )

    if not manifest_path.is_file():
        raise ToolError(
            "LFPS v2 collection manifest was not found in outputs."
        )

    if manifest_path.stat().st_size > MAX_RESPONSE_BYTES:
        raise ToolError(
            "LFPS v2 collection manifest exceeds the 5 MB safety limit."
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ToolError(f"Could not read collection manifest: {error}")

    if not isinstance(manifest, dict):
        raise ToolError("Collection manifest must contain a JSON object.")

    if manifest.get("api_version") != "LFPS v2":
        raise ToolError(
            "Collection manifest is not an LFPS v2 record."
        )

    job_id = manifest.get("job_id", "unknown")

    # Compose output artifact paths
    md_name = f"inspect_lf2025_{job_id}_report.md"
    json_name = f"inspect_lf2025_{job_id}_summary.json"
    csv_name = f"inspect_lf2025_{job_id}_evt_inventory.csv"

    md_path = folder / md_name
    json_path = folder / json_name
    csv_path = folder / csv_name

    # Never overwrite existing artifacts
    for p in (md_path, json_path, csv_path):
        if p.exists():
            raise ToolError(
                f"Inspection artifact already exists and will not be "
                f"overwritten: {p.name}. "
                f"Use the existing report or move/rename it first."
            )

    # Run inspection
    report = _inspect_landfire_v2_inputs(manifest, manifest_path)
    report["inspection_report_md"] = str(md_path)
    report["inspection_report_json"] = str(json_path)
    report["evt_inventory_csv"] = str(csv_path) if report["inspection_status"] != "failed" else None
    report["csv_artifact_created"] = False

    # Build output content
    failed = report["inspection_status"] == "failed"

    if failed:
        md_content = _build_failure_markdown(report, job_id)
    else:
        md_content = _build_markdown_report(report, job_id)

    json_content = json.dumps(report, indent=2, default=str)

    # Write Markdown and JSON (always, for both success/partial and failure)
    write_errors = []
    try:
        OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content, encoding="utf-8")
    except OSError as error:
        write_errors.append(f"Markdown write failed: {error}")

    try:
        json_path.write_text(json_content, encoding="utf-8")
    except OSError as error:
        write_errors.append(f"JSON write failed: {error}")

    if write_errors:
        report["write_errors"] = write_errors

    # Write EVT CSV only when not failed
    if not failed:
        try:
            buf = StringIO()
            writer = csv.writer(buf, lineterminator="\n")
            writer.writerow([
                "evt_code", "evt_name", "evt_name_source", "label_missing",
                "evt_lf", "evt_phys", "evt_gp_n", "saf_srm",
                "cell_count", "square_meters", "acres", "valid_cell_fraction",
                "domain_membership", "source_tif", "source_xml",
            ])
            for row in report.get("evt_band", {}).get("evt_codes_observed", []):
                writer.writerow([
                    row["evt_code"],
                    row.get("evt_name"),
                    row.get("evt_name_source"),
                    row["label_missing"],
                    row.get("evt_lf"),
                    row.get("evt_phys"),
                    row.get("evt_gp_n"),
                    row.get("saf_srm"),
                    row["cell_count"],
                    row["square_meters"],
                    row["acres"],
                    row["valid_cell_fraction"],
                    row["domain_membership"],
                    row["source_tif"],
                    row["source_xml"],
                ])
            csv_path.write_text(buf.getvalue(), encoding="utf-8")
            report["csv_artifact_created"] = True
        except OSError as error:
            report["csv_artifact_created"] = False
            report.setdefault("write_errors", []).append(
                f"EVT CSV write failed: {error}"
            )
    else:
        report["csv_artifact_created"] = False
        report.setdefault("write_errors", []).append(
            "EVT CSV not written: inspection_status is failed."
        )

    return report


# ===========================================================================
# Slice 3 — map_candidate_cover_types
# Internal helper and public MCP tool.
# Applies the approved EVT crosswalk to produce two GeoTIFFs:
#   candidate_cover_type_30m.tif  — integer class codes per codebook
#   candidate_forest_land_30m.tif — 1/0/2/-9999 (forest/nonforest/unknown/nodata)
# Plus codebook CSV, two acreage CSVs, and a methods/provenance JSON.
# ---------------------------------------------------------------------------

_SLICE3_MAPPING_SENTINELS = {
    "classification_performed": True,
    "crosswalk_applied": True,
    "candidate_cover_types_produced": True,
    "candidate_forest_land_produced": True,
    "field_inventory_performed": False,
    "authoritative_forest_land_determination_performed": False,
    "candidate_polygons_produced": False,
}

_CROSSWALK_DIR = _PROJECT_DATA_DIR / "crosswalks"
_COVER_SCHEME_DIR = _PROJECT_DATA_DIR / "cover_schemes"

# Stable forest-land raster encoding
_FL_TRUE = 1      # candidate_forest_land = true
_FL_FALSE = 0     # candidate_forest_land = false
_FL_UNKNOWN = 2   # candidate_forest_land = null/unknown
_FL_NODATA = -9999

_UNMAPPED_CODE = 255
_MAP_NODATA = -9999


def _load_crosswalk(crosswalk_filename: str) -> tuple:
    """Load and validate a crosswalk JSON from the crosswalks directory.

    Returns (crosswalk_dict, error_str).
    error_str is empty on success.
    """
    path = (_CROSSWALK_DIR / crosswalk_filename).resolve()
    if path.parent != _CROSSWALK_DIR.resolve():
        return {}, "Crosswalk filename must not contain path separators."
    if not path.is_file():
        return {}, f"Crosswalk file not found: {path.name}"
    if path.stat().st_size > MAX_RESPONSE_BYTES:
        return {}, "Crosswalk file exceeds the 5 MB safety limit."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"Could not read crosswalk: {exc}"
    if not isinstance(data, dict):
        return {}, "Crosswalk file must contain a JSON object."
    required = {"crosswalk_id", "crosswalk_version", "cover_scheme_id", "entries",
                "output_code_table", "nodata_value", "unmapped_valid_output_code"}
    missing = required - set(data.keys())
    if missing:
        return {}, f"Crosswalk missing required fields: {sorted(missing)}"
    return data, ""


def _apply_evt_crosswalk(
    manifest: dict,
    crosswalk: dict,
) -> dict:
    """Apply the approved EVT crosswalk to the GeoTIFF referenced in manifest.

    Returns a report dict with raster arrays, statistics, and all provenance.
    Never writes files. Never makes network calls.
    """
    import numpy as np  # transitive dep via rasterio

    report = dict(_SLICE3_MAPPING_SENTINELS)
    report["mapping_status"] = "failed"
    report["mapped_at_utc"] = datetime.now(timezone.utc).isoformat()
    warnings_list = []

    # --- Build EVT-code → output-code lookup from crosswalk entries -----------
    evt_to_output: dict[int, int] = {}
    evt_to_fl: dict[int, int] = {}   # output_code → forest-land raster code
    fl_by_output: dict[int, int] = {}

    # Build forest-land map from output_code_table
    for row in crosswalk.get("output_code_table", []):
        oc = row.get("output_code")
        cfl = row.get("candidate_forest_land")
        if oc is None:
            continue
        if cfl is True:
            fl_by_output[oc] = _FL_TRUE
        elif cfl is False:
            fl_by_output[oc] = _FL_FALSE
        else:
            fl_by_output[oc] = _FL_UNKNOWN

    for entry in crosswalk.get("entries", []):
        ec = entry.get("evt_code")
        oc = entry.get("output_code")
        if ec is None or oc is None:
            continue
        evt_to_output[int(ec)] = int(oc)

    nodata_val = int(crosswalk.get("nodata_value", _MAP_NODATA))
    unmapped_code = int(crosswalk.get("unmapped_valid_output_code", _UNMAPPED_CODE))

    # --- Open GeoTIFF ---------------------------------------------------------
    geotiff_file = manifest.get("geotiff_file")
    if not geotiff_file or not Path(geotiff_file).is_file():
        report["warnings"] = [f"GeoTIFF not found: {geotiff_file}"]
        return report

    try:
        with rasterio.open(str(geotiff_file)) as src:
            transform = src.transform
            crs = src.crs
            shape = (src.height, src.width)
            total_pixels = src.height * src.width
            descriptions = src.descriptions

            # Identify EVT band
            evt_band_index = None
            for i, desc in enumerate(descriptions):
                if desc and "EVT" in desc.upper():
                    evt_band_index = i + 1
                    break
            if evt_band_index is None:
                report["warnings"] = ["Could not identify EVT band by description."]
                return report

            evt_arr_2d = src.read(evt_band_index).astype(np.int32)
            evt_arr_flat = evt_arr_2d.ravel()
    except Exception as exc:  # noqa: BLE001
        report["warnings"] = [f"GeoTIFF read error: {exc}"]
        return report

    cell_area_m2, cell_area_acres, area_limit = _safe_cell_area(transform, crs)
    if area_limit:
        warnings_list.append(f"Cell area limitation: {area_limit}")

    # --- Apply crosswalk pixel-by-pixel (vectorised) --------------------------
    out_flat = np.full(total_pixels, nodata_val, dtype=np.int32)
    fl_flat = np.full(total_pixels, _FL_NODATA, dtype=np.int32)

    nd_mask = (evt_arr_flat == nodata_val)
    valid_mask = ~nd_mask

    # Vectorised: for each observed unique valid EVT code, fill output array
    valid_evt = evt_arr_flat[valid_mask]
    unique_evts = np.unique(valid_evt).tolist()

    unmapped_codes_seen = []
    for evt_code_int in unique_evts:
        pixel_mask = valid_mask & (evt_arr_flat == evt_code_int)
        if evt_code_int in evt_to_output:
            oc = evt_to_output[evt_code_int]
        else:
            oc = unmapped_code
            unmapped_codes_seen.append(evt_code_int)
            warnings_list.append(
                f"EVT code {evt_code_int} not in approved crosswalk — "
                f"assigned unmapped_evt (code {unmapped_code}). "
                "source_evt_code_unmapped flag applies."
            )
        out_flat[pixel_mask] = oc
        fl_flat[pixel_mask] = fl_by_output.get(oc, _FL_UNKNOWN)

    # Reshape back to 2D
    out_2d = out_flat.reshape(shape)
    fl_2d = fl_flat.reshape(shape)

    # --- Acreage statistics for cover-type raster ----------------------------
    cover_type_stats = []
    nodata_count = int(nd_mask.sum())
    nodata_acres = round(nodata_count * cell_area_acres, 4) if cell_area_acres else None

    for row in crosswalk.get("output_code_table", []):
        oc = row.get("output_code")
        if oc is None or oc == nodata_val:
            continue
        count = int((out_flat == oc).sum())
        if count == 0:
            continue
        acres = round(count * cell_area_acres, 4) if cell_area_acres else None
        cover_type_stats.append({
            "output_code": oc,
            "output_label": row["output_label"],
            "candidate_forest_land": row.get("candidate_forest_land"),
            "cell_count": count,
            "square_meters": round(count * cell_area_m2, 2) if cell_area_m2 else None,
            "acres": acres,
            "fraction_of_valid": round(count / int(valid_mask.sum()), 6) if valid_mask.sum() > 0 else None,
        })

    # --- Acreage statistics for forest-land raster ---------------------------
    fl_code_labels = {
        _FL_TRUE: "candidate_forest_land_true",
        _FL_FALSE: "candidate_forest_land_false",
        _FL_UNKNOWN: "candidate_forest_land_unknown",
    }
    forest_land_stats = []
    for fl_code, fl_label in fl_code_labels.items():
        count = int((fl_flat == fl_code).sum())
        acres = round(count * cell_area_acres, 4) if cell_area_acres else None
        forest_land_stats.append({
            "forest_land_code": fl_code,
            "meaning": fl_label,
            "cell_count": count,
            "acres": acres,
        })
    forest_land_stats.append({
        "forest_land_code": _FL_NODATA,
        "meaning": "nodata",
        "cell_count": nodata_count,
        "acres": nodata_acres,
    })

    # --- Closure check -------------------------------------------------------
    valid_count = int(valid_mask.sum())
    ct_sum = sum(r["cell_count"] for r in cover_type_stats)
    ct_closure_ok = (ct_sum == valid_count)
    if not ct_closure_ok:
        warnings_list.append(
            f"Cover-type acreage closure FAILED: valid_count={valid_count}, "
            f"sum_of_classes={ct_sum}."
        )

    fl_sum = sum(r["cell_count"] for r in forest_land_stats if r["forest_land_code"] != _FL_NODATA)
    fl_closure_ok = (fl_sum == valid_count)
    if not fl_closure_ok:
        warnings_list.append(
            f"Forest-land acreage closure FAILED: valid_count={valid_count}, "
            f"sum_of_fl_classes={fl_sum}."
        )

    total_with_nodata = ct_sum + nodata_count
    total_closure_ok = (total_with_nodata == total_pixels)
    if not total_closure_ok:
        warnings_list.append(
            f"Total pixel closure FAILED: total_pixels={total_pixels}, "
            f"valid+nodata={total_with_nodata}."
        )

    report.update({
        "mapping_status": "complete",
        "job_id": manifest.get("job_id", "unknown"),
        "geotiff_file": geotiff_file,
        "evt_band_index_used": evt_band_index,
        "raster_shape": list(shape),
        "raster_crs_epsg": crs.to_epsg() if crs else None,
        "raster_transform": list(transform)[:6],
        "nodata_value": nodata_val,
        "total_pixels": total_pixels,
        "nodata_cell_count": nodata_count,
        "nodata_acres": nodata_acres,
        "valid_cell_count": valid_count,
        "valid_acres": round(valid_count * cell_area_acres, 4) if cell_area_acres else None,
        "cell_area_m2": cell_area_m2,
        "cell_area_acres": cell_area_acres,
        "cover_type_stats": cover_type_stats,
        "forest_land_stats": forest_land_stats,
        "unmapped_evt_codes_seen": unmapped_codes_seen,
        "acreage_closure": {
            "cover_type_valid_sum_matches": ct_closure_ok,
            "forest_land_valid_sum_matches": fl_closure_ok,
            "total_pixel_sum_matches": total_closure_ok,
            "valid_cell_count": valid_count,
            "cover_type_class_sum": ct_sum,
            "forest_land_class_sum": fl_sum,
            "nodata_count": nodata_count,
            "total_pixels": total_pixels,
        },
        "_out_2d": out_2d,
        "_fl_2d": fl_2d,
        "warnings": warnings_list,
    })
    return report


@mcp.tool()
def map_candidate_cover_types(
    collection_manifest_filename: str,
    crosswalk_filename: str = "mescalero_v1_evt_crosswalk_v1.json",
) -> dict:
    """Apply the approved EVT crosswalk and produce candidate cover-type and
    forest-land rasters for professional review.

    This tool reads one previously collected and inspected LFPS v2 GeoTIFF,
    applies the approved EVT-to-candidate-class crosswalk, and writes six
    durable artifacts to outputs/.

    Prerequisites:
      - A completed LFPS v2 collection (produced by collect_landfire_v2_sample_result).
      - The approved crosswalk JSON in project_data/crosswalks/.
      - The cover scheme JSON in project_data/cover_schemes/.

    Outputs written to outputs/:
      - cmap_<job_id>_<crosswalk_version>_cover_type_30m.tif
      - cmap_<job_id>_<crosswalk_version>_forest_land_30m.tif
      - cmap_<job_id>_<crosswalk_version>_cover_type_codebook.csv
      - cmap_<job_id>_<crosswalk_version>_cover_type_acreage.csv
      - cmap_<job_id>_<crosswalk_version>_forest_land_acreage.csv
      - cmap_<job_id>_<crosswalk_version>_methods.json

    Returns: mapping_status, artifact paths, per-class acreage, closure checks,
    provenance, and all sentinel fields.

    Limitations: Outputs are preliminary candidate assignments. Not field
    inventory. Not Tribal-approved management classes. Species composition and
    crown-cover criteria not directly measured. EVC/EVH not used for
    classification in this pass. Disturbance not evaluated.

    Failure behavior: Returns a structured failure dict. Does not write raster
    artifacts on failure. Methods JSON is always written when safe to do so.
    """
    # --- Input validation -----------------------------------------------------
    if not re.fullmatch(
        r"lfps_v2_collection_\d{8}T\d{12}Z_"
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}\.json",
        collection_manifest_filename,
    ):
        raise ToolError(
            "Use the exact generated LFPS v2 collection-manifest filename only, "
            "not a full path."
        )

    if not re.fullmatch(r"[A-Za-z0-9_-]+\.json", crosswalk_filename):
        raise ToolError(
            "Crosswalk filename must be a simple JSON filename with no path separators."
        )

    folder = OUTPUT_FOLDER.resolve()
    manifest_path = (folder / collection_manifest_filename).resolve()
    if manifest_path.parent != folder:
        raise ToolError("Collection manifest must remain inside the outputs folder.")
    if not manifest_path.is_file():
        raise ToolError("Collection manifest not found in outputs.")
    if manifest_path.stat().st_size > MAX_RESPONSE_BYTES:
        raise ToolError("Collection manifest exceeds 5 MB safety limit.")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError(f"Could not read collection manifest: {exc}")
    if not isinstance(manifest, dict):
        raise ToolError("Collection manifest must contain a JSON object.")
    if manifest.get("api_version") != "LFPS v2":
        raise ToolError("Collection manifest is not an LFPS v2 record.")

    job_id = manifest.get("job_id", "unknown")

    # --- Load crosswalk -------------------------------------------------------
    crosswalk, cw_err = _load_crosswalk(crosswalk_filename)
    if cw_err:
        raise ToolError(f"Crosswalk load failed: {cw_err}")

    cw_version = crosswalk.get("crosswalk_version", "unknown")
    short_job = job_id.split("-")[0] if "-" in job_id else job_id[:8]

    # --- Compose output artifact paths ----------------------------------------
    prefix = f"cmap_{short_job}_{cw_version}"
    ct_tif_name = f"{prefix}_cover_type_30m.tif"
    fl_tif_name = f"{prefix}_forest_land_30m.tif"
    cb_csv_name = f"{prefix}_cover_type_codebook.csv"
    ct_csv_name = f"{prefix}_cover_type_acreage.csv"
    fl_csv_name = f"{prefix}_forest_land_acreage.csv"
    methods_name = f"{prefix}_methods.json"

    ct_tif_path = folder / ct_tif_name
    fl_tif_path = folder / fl_tif_name
    cb_csv_path = folder / cb_csv_name
    ct_csv_path = folder / ct_csv_name
    fl_csv_path = folder / fl_csv_name
    methods_path = folder / methods_name

    # Never overwrite
    for p in (ct_tif_path, fl_tif_path, cb_csv_path, ct_csv_path,
              fl_csv_path, methods_path):
        if p.exists():
            raise ToolError(
                f"Output artifact already exists and will not be overwritten: "
                f"{p.name}. Move or rename existing artifacts first."
            )

    # --- Run mapping ----------------------------------------------------------
    report = _apply_evt_crosswalk(manifest, crosswalk)

    # Extract and remove the private numpy arrays before JSON serialisation
    out_2d = report.pop("_out_2d", None)
    fl_2d = report.pop("_fl_2d", None)

    report["artifacts"] = {
        "cover_type_tif": str(ct_tif_path),
        "forest_land_tif": str(fl_tif_path),
        "cover_type_codebook_csv": str(cb_csv_path),
        "cover_type_acreage_csv": str(ct_csv_path),
        "forest_land_acreage_csv": str(fl_csv_path),
        "methods_json": str(methods_path),
    }
    report["crosswalk_filename"] = crosswalk_filename
    report["crosswalk_id"] = crosswalk.get("crosswalk_id")
    report["crosswalk_version"] = cw_version
    report["cover_scheme_id"] = crosswalk.get("cover_scheme_id")
    report["evt_add_sha256"] = crosswalk.get("evt_add_sha256")

    write_errors = []
    rasters_written = False

    # --- Write GeoTIFFs (only on successful mapping) --------------------------
    if report.get("mapping_status") == "complete" and out_2d is not None:
        try:
            import numpy as np
            import rasterio
            geotiff_file = manifest.get("geotiff_file")
            with rasterio.open(str(geotiff_file)) as src_ref:
                profile = src_ref.profile.copy()
            profile.update(count=1, dtype="int16", nodata=_MAP_NODATA)

            OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

            with rasterio.open(str(ct_tif_path), "w", **profile) as dst:
                dst.write(out_2d.astype("int16"), 1)
                dst.update_tags(
                    description="Candidate cover-type raster",
                    crosswalk_id=crosswalk.get("crosswalk_id", ""),
                    crosswalk_version=cw_version,
                    cover_scheme_id=crosswalk.get("cover_scheme_id", ""),
                    job_id=job_id,
                    status="preliminary_candidate_requires_review",
                )

            with rasterio.open(str(fl_tif_path), "w", **profile) as dst:
                dst.write(fl_2d.astype("int16"), 1)
                dst.update_tags(
                    description="Candidate forest-land raster",
                    crosswalk_id=crosswalk.get("crosswalk_id", ""),
                    crosswalk_version=cw_version,
                    cover_scheme_id=crosswalk.get("cover_scheme_id", ""),
                    job_id=job_id,
                    status="preliminary_candidate_requires_review",
                    forest_land_codes="1=forest_land_true 0=forest_land_false 2=unknown -9999=nodata",
                )
            rasters_written = True
        except Exception as exc:  # noqa: BLE001
            write_errors.append(f"GeoTIFF write failed: {exc}")

    # --- Write codebook CSV ---------------------------------------------------
    cb_written = False
    try:
        buf = StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow([
            "output_code", "output_label", "candidate_forest_land",
            "description", "source_evt_codes",
        ])
        # Build reverse map: output_code -> list of evt_codes
        oc_to_evts: dict[int, list] = {}
        for e in crosswalk.get("entries", []):
            oc = e.get("output_code")
            ec = e.get("evt_code")
            if oc is not None and ec is not None:
                oc_to_evts.setdefault(int(oc), []).append(int(ec))
        for row in crosswalk.get("output_code_table", []):
            oc = row.get("output_code")
            src_codes = "|".join(str(c) for c in sorted(oc_to_evts.get(oc, [])))
            cfl = row.get("candidate_forest_land")
            writer.writerow([
                oc,
                row.get("output_label", ""),
                "true" if cfl is True else ("false" if cfl is False else "null"),
                row.get("description", ""),
                src_codes,
            ])
        cb_csv_path.write_text(buf.getvalue(), encoding="utf-8")
        cb_written = True
    except OSError as exc:
        write_errors.append(f"Codebook CSV write failed: {exc}")

    # --- Write cover-type acreage CSV -----------------------------------------
    ct_written = False
    try:
        buf = StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow([
            "output_code", "output_label", "candidate_forest_land",
            "cell_count", "square_meters", "acres", "fraction_of_valid",
        ])
        for row in report.get("cover_type_stats", []):
            cfl = row.get("candidate_forest_land")
            writer.writerow([
                row["output_code"],
                row["output_label"],
                "true" if cfl is True else ("false" if cfl is False else "null"),
                row["cell_count"],
                row.get("square_meters", ""),
                row.get("acres", ""),
                row.get("fraction_of_valid", ""),
            ])
        # append nodata row
        writer.writerow([
            _MAP_NODATA, "nodata", "null",
            report.get("nodata_cell_count", ""),
            round(report.get("nodata_cell_count", 0) * (report.get("cell_area_m2") or 0), 2)
                if report.get("cell_area_m2") else "",
            report.get("nodata_acres", ""),
            "",
        ])
        ct_csv_path.write_text(buf.getvalue(), encoding="utf-8")
        ct_written = True
    except OSError as exc:
        write_errors.append(f"Cover-type acreage CSV write failed: {exc}")

    # --- Write forest-land acreage CSV ----------------------------------------
    fl_written = False
    try:
        buf = StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["forest_land_code", "meaning", "cell_count", "acres"])
        for row in report.get("forest_land_stats", []):
            writer.writerow([
                row["forest_land_code"],
                row["meaning"],
                row["cell_count"],
                row.get("acres", ""),
            ])
        fl_csv_path.write_text(buf.getvalue(), encoding="utf-8")
        fl_written = True
    except OSError as exc:
        write_errors.append(f"Forest-land acreage CSV write failed: {exc}")

    # --- Write methods JSON ---------------------------------------------------
    methods_written = False
    methods_doc = {
        "document_type": "candidate_cover_type_methods_and_provenance",
        "mapping_status": report.get("mapping_status"),
        "mapped_at_utc": report.get("mapped_at_utc"),
        "job_id": job_id,
        "collection_manifest": collection_manifest_filename,
        "geotiff_file": manifest.get("geotiff_file"),
        "crosswalk_id": crosswalk.get("crosswalk_id"),
        "crosswalk_version": cw_version,
        "cover_scheme_id": crosswalk.get("cover_scheme_id"),
        "cover_scheme_version": crosswalk.get("cover_scheme_version"),
        "evt_add_url": crosswalk.get("evt_add_url"),
        "evt_add_sha256": crosswalk.get("evt_add_sha256"),
        "crosswalk_approval_note": crosswalk.get("crosswalk_approval_note"),
        "sentinels": _SLICE3_MAPPING_SENTINELS,
        "raster_shape": report.get("raster_shape"),
        "raster_crs_epsg": report.get("raster_crs_epsg"),
        "raster_transform": report.get("raster_transform"),
        "nodata_value": _MAP_NODATA,
        "total_pixels": report.get("total_pixels"),
        "nodata_cell_count": report.get("nodata_cell_count"),
        "valid_cell_count": report.get("valid_cell_count"),
        "valid_acres": report.get("valid_acres"),
        "acreage_closure": report.get("acreage_closure"),
        "cover_type_stats": report.get("cover_type_stats"),
        "forest_land_stats": report.get("forest_land_stats"),
        "unmapped_evt_codes_seen": report.get("unmapped_evt_codes_seen"),
        "artifacts": report.get("artifacts"),
        "rasters_written": rasters_written,
        "write_errors": write_errors,
        "warnings": report.get("warnings", []),
        "evc_evh_policy": crosswalk.get("evc_evh_policy"),
        "disturbance_policy": crosswalk.get("disturbance_policy"),
        "universal_review_flags": crosswalk.get("universal_review_flags"),
        "limitations": [
            "Outputs are preliminary candidate assignments. Not field inventory.",
            "Not Tribal-approved management classes.",
            "Species composition and crown-cover criteria not directly measured.",
            "EVC/EVH not used for classification in this pass.",
            "Disturbance not evaluated.",
            "NT/NW policy preserved; neither assigned in this sample.",
            "ArcGIS Pro review by the forester required before any management use.",
            "This is a sample covering approximately 375 acres; not the full reservation.",
        ],
        "arcgis_pro_opening_instructions": (
            "1. In ArcGIS Pro, open or create a project. "
            "2. Add the cover-type raster: Insert > Add Data > "
            f"{ct_tif_name}. "
            "3. In the layer symbology, set renderer to 'Unique Values' on the "
            "raster value field. Map integer codes using the codebook CSV: "
            f"{cb_csv_name}. "
            "4. Add the forest-land raster: Insert > Add Data > "
            f"{fl_tif_name}. "
            "Symbology: 1=forest land (green), 0=nonforest (yellow), "
            "2=unknown (grey), -9999=NoData (transparent). "
            "5. Both rasters are EPSG:5070 (NAD83/Conus Albers), 30 m resolution. "
            "They should align exactly with the source LFPS v2 GeoTIFF. "
            "6. Review the acreage CSVs and methods JSON for provenance, "
            "closure checks, and limitations before any interpretation. "
            "7. All outputs are labeled preliminary and candidate. "
            "Professional forestry review is required."
        ),
    }
    try:
        methods_path.write_text(
            json.dumps(methods_doc, indent=2, default=str), encoding="utf-8"
        )
        methods_written = True
    except OSError as exc:
        write_errors.append(f"Methods JSON write failed: {exc}")

    if write_errors:
        report["write_errors"] = write_errors

    report["artifacts_written"] = {
        "cover_type_tif": rasters_written,
        "forest_land_tif": rasters_written,
        "cover_type_codebook_csv": cb_written,
        "cover_type_acreage_csv": ct_written,
        "forest_land_acreage_csv": fl_written,
        "methods_json": methods_written,
    }

    return report

from cover_type_patches import (
    RawPatchRequest,
    RawPatchResult,
    create_raw_cover_type_patches,
)

@mcp.tool()
def create_candidate_cover_type_patches(request: RawPatchRequest) -> RawPatchResult:
    """Create preliminary raw cover-type patch polygons from a completed Slice 3 map.

    Use after reviewing the candidate raster and approving four-neighbor
    connectivity. Accept a Slice 3 methods JSON filename in outputs/ only.
    Derive companion raster/codebook filenames internally; no arbitrary paths.

    Writes one GeoPackage polygon layer with multiple cover classes and
    attributes, a class-acreage CSV, QC/provenance JSON, and opening instructions
    in a new isolated outputs subfolder. Preserves the input raster unchanged.

    No smoothing, small-patch removal, classification, or stand delineation.
    Valid uncertain categories remain polygons; NoData remains holes/gaps,
    separately counted in QC. Class-level flags are conservative associations,
    not measured per-patch vegetation evidence. This prototype requires the
    existing EPSG:5070 north-up 30 m integer candidate raster and bounded inputs.

    Returns a structured failure if validation or processing fails. Any
    incomplete written run receives a failure marker and must not be accepted.
    Professional forestry and ArcGIS Pro review are required.
    """
    return create_raw_cover_type_patches(OUTPUT_FOLDER, request)

from cover_type_generalization import (
    GeneralizationRequest,
    GeneralizationResult,
    create_generalized_cover_type_patches,
)

@mcp.tool()
def generalize_candidate_cover_types(
    request: GeneralizationRequest,
) -> GeneralizationResult:
    """Create separate preliminary generalized cover-type review units.

    Use after successful raw-patch generation and professional review of the
    first sample. Obtain explicit user approval of the exact settings before
    invoking this output-writing tool; this function does not authenticate it.

    Accept only an existing raw-run subfolder name inside outputs and validated
    settings. Version 1 implements the approved Mescalero P/PJ inclusion trial:
    original small patches may join original P/PJ anchors at or above the
    threshold, ranked by shared edge, original anchor area, and stable ID.
    No cascading merges. Protected and explicitly excluded patches remain.

    Writes a new GeoPackage, membership/composition and acreage CSVs, QC and
    methods, and opening instructions. Preserves raw/source inputs. Display
    labels follow anchors; original-class acreage must use composition.
    No raster reclassification, smoothing, stands, hard-boundary screening,
    or disturbance-history analysis. Rejects unsupported settings.

    Returns structured summary/artifact references or a structured failure.
    Failed partial runs are marked FAILED_DO_NOT_USE.json where possible.
    ArcGIS review and remote file delivery are not performed by this tool.
    """
    return create_generalized_cover_type_patches(OUTPUT_FOLDER, request)

from boundary_mapping_preflight import (
    BoundaryPreparationRequest,
    BoundaryPreparationResult,
    prepare_boundary_mapping_request,
)

@mcp.tool()
def prepare_full_boundary_mapping_request(
    request: BoundaryPreparationRequest,
) -> BoundaryPreparationResult:
    """Preflight a selected public boundary and prepare a full-area request.

    Use after selecting/reviewing a public boundary and deciding to expand
    beyond the pilot sample. Accept only a GeoJSON filename directly inside
    outputs, not arbitrary paths or URLs. The boundary is not hardcoded to
    Mescalero. Version 1 supports lower-48 geometry and the LF2025 CONUS
    EVT/EVC/EVH profile with EPSG:5070 output; other regions/profiles fail.

    Revalidates geometry, estimates grid and illustrative array sizes, records
    existing sample-limit conflicts, and writes a separate review request,
    preflight report, and notes in a new folder. Get user consent for these
    local writes. Requires no contact email and makes no network request.

    A prepared request is NOT execution-ready: service limits/contract were
    not checked, and the existing sample submitter cannot use this document.
    No download, boundary clipping, classification, crosswalk approval,
    generalization or legal-boundary verification is performed.

    Returns a structured prepared-review result or failure; partial writes
    are marked FAILED_DO_NOT_USE.json where possible.
    """
    return prepare_boundary_mapping_request(OUTPUT_FOLDER, request)

if __name__ == "__main__":
    mcp.run(transport="stdio")
