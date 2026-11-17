"""Pure source-based configuration builder. No IO, network, or forest policy."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from urllib.parse import urlsplit

MAX_CSV_BYTES = 5_000_000
MAX_ROWS = 100_000
MAX_TEXT = 2_000
NODATA = -9999
REVIEW_ATTRIBUTES = (
    "EVT_LF", "EVT_PHYS", "EVT_GP", "EVT_GP_N",
    "SAF_SRM", "EVT_ORDER", "EVT_CLASS", "EVT_SBCLS",
)


class SourceConfigurationError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise SourceConfigurationError(message)


def _text(value, name):
    _require(
        isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_TEXT,
        f"{name} must be a bounded non-empty string.",
    )
    return value.strip()


def _code(value):
    _require(
        type(value) is int and 0 <= value <= 32767,
        "EVT codes must be nonnegative int16 integers; NoData is separate.",
    )
    return value


def build_source_configuration(
    csv_bytes: bytes,
    observed_evt_codes: list[int],
    *,
    raster_profile: dict,
    catalog_record: dict,
    code_column: str,
    name_column: str,
) -> dict:
    """Build an unapproved EVT-preserving configuration from reviewed metadata.

    catalog_record requires product, version, region, source_url, and sha256.
    Profile matching is exact. The record must be reviewed outside this function.
    NoData (-9999) may occur in observed codes but is not a vegetation category.
    No approval, geographic suitability, or forest-land policy is inferred.
    """
    _require(
        isinstance(csv_bytes, bytes) and 0 < len(csv_bytes) <= MAX_CSV_BYTES,
        "CSV must be non-empty bytes within the 5 MB limit.",
    )
    _require(
        isinstance(raster_profile, dict) and isinstance(catalog_record, dict),
        "Raster profile and catalog record must be objects.",
    )
    profile = {}
    for key in ("product", "version", "region"):
        profile[key] = _text(raster_profile.get(key), f"raster {key}")
        _require(
            profile[key] == _text(catalog_record.get(key), f"catalog {key}"),
            f"Raster/catalog {key} mismatch.",
        )
    _require(profile["product"] == "EVT", "Only EVT is supported.")

    source_url = _text(catalog_record.get("source_url"), "source_url")
    url = urlsplit(source_url)
    _require(
        url.scheme == "https"
        and url.netloc.lower() in ("landfire.gov", "www.landfire.gov")
        and not url.query
        and not url.fragment
        and bool(url.path),
        "Source reference must be a fixed HTTPS LANDFIRE URL without credentials or query.",
    )
    expected = catalog_record.get("sha256")
    _require(
        isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
        "Expected SHA-256 must be 64 lowercase hexadecimal characters.",
    )
    digest = hashlib.sha256(csv_bytes).hexdigest()
    _require(digest == expected, "Attribute-table checksum mismatch.")

    code_column = _text(code_column, "code_column")
    name_column = _text(name_column, "name_column")
    _require(code_column != name_column, "Code and name columns must differ.")
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceConfigurationError("CSV must be UTF-8.") from exc
    _require("\x00" not in text, "CSV contains NUL characters.")

    labels = {}
    attributes = {}
    try:
        reader = csv.DictReader(io.StringIO(text), strict=True)
        headers = reader.fieldnames or []
        _require(
            len(headers) == len(set(headers))
            and code_column in headers
            and name_column in headers,
            "CSV requires unique headers and the explicitly selected columns.",
        )
        for count, row in enumerate(reader, 1):
            _require(count <= MAX_ROWS, "CSV row limit exceeded.")
            _require(
                None not in row and all(value is not None for value in row.values()),
                "Malformed CSV row.",
            )
            value = row[code_column].strip()
            _require(bool(re.fullmatch(r"-?\d+", value)), "Invalid CSV EVT code.")
            code = int(value)
            _require(code not in labels, f"Duplicate CSV EVT code: {code}.")
            if code != NODATA:
                _code(code)
            label = row[name_column].strip()
            _require(len(label) <= MAX_TEXT, "Source label exceeds length limit.")
            labels[code] = label or None
            attributes[code] = {}
            for field in REVIEW_ATTRIBUTES:
                if field in row:
                    value = row[field].strip()
                    _require(
                        len(value) <= MAX_TEXT,
                        f"Source attribute {field} exceeds length limit.",
                    )
                    attributes[code][field] = value or None
    except csv.Error as exc:
        raise SourceConfigurationError("Malformed CSV.") from exc
    _require(bool(labels), "CSV contains no data rows.")

    _require(
        isinstance(observed_evt_codes, list)
        and len(observed_evt_codes) <= MAX_ROWS,
        "Observed EVT codes must be a bounded list.",
    )
    observed = set()
    for code in observed_evt_codes:
        _require(type(code) is int, "Observed EVT codes must be integers.")
        if code != NODATA:
            observed.add(_code(code))
    _require(bool(observed), "No valid observed EVT codes.")

    entries = []
    for code in sorted(observed):
        name = labels.get(code)
        entries.append({
            "source_evt_code": code,
            "output_code": code,
            "official_name": name,
            "source_attributes": attributes.get(code, {}),
            "display_label": (
                f"EVT {code} ? {name}"
                if name else f"EVT {code} ? official label unavailable"
            ),
            "label_status": "verified_table_match" if name else "missing_label",
            "candidate_forest_land": None,
            "review_flags": (
                ["source_based_not_local_management_class"]
                + ([] if name else ["official_label_missing"])
            ),
        })

    configuration = {
        "schema": "mapcp_source_configuration_v1",
        "status": "draft_requires_run_and_policy_review",
        "mode": "source_evt_identity",
        "profile": profile,
        "source": {
            "url": source_url,
            "sha256": digest,
            "code_column": code_column,
            "name_column": name_column,
        },
        "nodata_value": NODATA,
        "output_dtype": "int16",
        "unknown_codes_preserved_individually": True,
        "forest_land_policy": "not_assigned",
        "forest_land_classification_performed": False,
        "entries": entries,
        "warnings": [
            "Source identity is preserved; local management classes are not assigned.",
            "Forest-land assignments require a separately approved policy.",
            "Checksum/profile checks do not authenticate catalog approval or source origin.",
        ],
    }
    encoded = json.dumps(
        configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    configuration["configuration_sha256"] = hashlib.sha256(encoded).hexdigest()
    return configuration
