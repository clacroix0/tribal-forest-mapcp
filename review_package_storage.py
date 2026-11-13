"""Private IBM COS delivery; no buckets, credentials, ACLs, or policies are created."""
import hashlib
import io
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from review_package import ExportError, MAX_BYTES, build_review_package, read_json_bytes, require

DESCRIPTOR_MAX = 256 * 1024
LINK_SECONDS = 3600

@dataclass(frozen=True)
class StorageConfig:
    bucket: str
    endpoint: str
    region: str
    prefix: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)

    @classmethod
    def from_environment(cls, env=None):
        env = os.environ if env is None else env
        bucket = env.get("MAPCP_REVIEW_COS_BUCKET", "")
        endpoint = env.get("MAPCP_REVIEW_COS_ENDPOINT", "")
        region = env.get("MAPCP_REVIEW_COS_REGION", "")
        prefix = env.get("MAPCP_REVIEW_COS_PREFIX", "mapcp-review/")
        key = env.get("MAPCP_REVIEW_COS_ACCESS_KEY_ID", "")
        secret = env.get("MAPCP_REVIEW_COS_SECRET_ACCESS_KEY", "")
        u = urlsplit(endpoint)
        require(u.scheme == "https" and u.hostname is not None and
                re.fullmatch(r"s3\.[a-z0-9-]+\.cloud-object-storage\.appdomain\.cloud", u.hostname) and
                u.netloc == u.hostname and u.path in ("", "/") and not u.query and not u.fragment,
                "storage_not_configured", "A public HTTPS IBM COS S3 endpoint must be explicitly configured.")
        require(bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket)) and
                ".." not in bucket and not re.fullmatch(r"[0-9.]+", bucket),
                "storage_not_configured", "An approved COS bucket must be configured.")
        require(bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", region)),
                "storage_not_configured", "The bucket signing region must be explicitly configured.")
        require(bool(re.fullmatch(r"[a-z0-9][a-z0-9/-]{0,99}/", prefix)) and "//" not in prefix,
                "storage_not_configured", "A bounded object prefix must be configured.")
        require(key and secret and not any(c.isspace() for c in key+secret),
                "storage_not_configured", "COS HMAC credentials must be supplied through runtime secrets.")
        return cls(bucket, endpoint.rstrip("/"), region, prefix, key, secret)

def make_client(config):
    try:
        import ibm_boto3
        from ibm_botocore.client import Config
    except ImportError:
        raise ExportError("storage_dependency_missing", "The IBM COS Python SDK is not installed.") from None
    return ibm_boto3.client(
        "s3", endpoint_url=config.endpoint, region_name=config.region,
        aws_access_key_id=config.access_key, aws_secret_access_key=config.secret_key,
        config=Config(signature_version="s3v4", connect_timeout=10, read_timeout=60,
                      retries={"max_attempts": 0}, s3={"addressing_style": "path"}),
    )

def _package_id(value):
    try:
        valid = type(value) is str and str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        valid = False
    require(valid, "invalid_input", "Supply a canonical package UUID returned by a successful export.")
    return value

def _key(config, package_id, name):
    return f"{config.prefix}{_package_id(package_id)}/{name}"

def _head(client, config, key, allow_missing=False):
    try:
        return client.head_object(Bucket=config.bucket, Key=key)
    except Exception as exc:
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if allow_missing and (code in {"404", "NoSuchKey", "NotFound"} or status == 404):
            return None
        raise ExportError("storage_access_failed", "COS object metadata could not be read; no permissions were changed.") from None

def _get_bounded(client, config, key, limit):
    try:
        response = client.get_object(Bucket=config.bucket, Key=key)
        body = response["Body"]
        try:
            data = body.read(limit+1)
        finally:
            body.close()
        require(len(data) <= limit, "storage_integrity_failed", "Stored metadata exceeds its size limit.")
        return data
    except ExportError:
        raise
    except Exception:
        raise ExportError("storage_read_failed", "The stored object could not be read.") from None

def _verify_zip(client, config, key, size, checksum):
    info = _head(client, config, key)
    require(info.get("ContentLength") == size and info.get("Metadata", {}).get("sha256") == checksum,
            "storage_integrity_failed", "Uploaded object size or checksum metadata disagrees.")
    try:
        response = client.get_object(Bucket=config.bucket, Key=key)
        body = response["Body"]
        n, digest = 0, hashlib.sha256()
        try:
            while True:
                block = body.read(min(1024*1024, MAX_BYTES+1-n))
                if not block:
                    break
                n += len(block)
                require(n <= MAX_BYTES, "storage_integrity_failed", "Uploaded object exceeds its bounded size.")
                digest.update(block)
        finally:
            body.close()
        require(n == size and digest.hexdigest() == checksum,
                "storage_integrity_failed", "Uploaded ZIP failed a complete read-back checksum check.")
    except ExportError:
        raise
    except Exception:
        raise ExportError("storage_read_failed", "Uploaded ZIP could not be read back for verification.") from None

def _put(client, config, key, body, content_type, checksum):
    require(_head(client, config, key, allow_missing=True) is None,
            "storage_object_exists", "Export object already exists; it will not be overwritten.")
    try:
        client.put_object(Bucket=config.bucket, Key=key, Body=body,
                          ContentType=content_type, Metadata={"sha256": checksum})
    except Exception:
        raise ExportError("storage_upload_failed", "COS upload failed or its outcome is unknown; export was not automatically retried.") from None

def _link(client, config, descriptor, *, verify_contents=False):
    package_id = _package_id(descriptor.get("package_id"))
    checksum, size = descriptor.get("package_sha256"), descriptor.get("package_bytes")
    require(isinstance(checksum, str) and re.fullmatch(r"[0-9a-f]{64}", checksum) and
            type(size) is int and 0 < size <= MAX_BYTES,
            "storage_integrity_failed", "Stored package descriptor is invalid.")
    files = descriptor.get("files")
    require(isinstance(files, list) and len(files) == 9 and
            all(isinstance(n, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", n) for n in files) and
            len(set(files)) == 9,
            "storage_integrity_failed", "Stored package file list is invalid.")
    key = _key(config, package_id, "mapcp_raster_review.zip")
    if verify_contents:
        _verify_zip(client, config, key, size, checksum)
    else:
        info = _head(client, config, key)
        require(info.get("ContentLength") == size and info.get("Metadata", {}).get("sha256") == checksum,
                "storage_integrity_failed", "Stored ZIP metadata does not match the package record.")
    now = datetime.now(timezone.utc)
    try:
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": config.bucket, "Key": key,
                "ResponseContentDisposition": 'attachment; filename="mapcp_raster_review.zip"',
                "ResponseContentType": "application/zip"}, ExpiresIn=LINK_SECONDS)
    except Exception:
        raise ExportError("link_generation_failed", "A temporary download link could not be generated.") from None
    u = urlsplit(url)
    expected_path = f"/{config.bucket}/{key}"
    require(u.scheme == "https" and u.netloc == urlsplit(config.endpoint).netloc and u.path == expected_path and u.query and not u.fragment,
            "link_generation_failed", "The storage SDK returned an unexpected download URL.")
    warnings = descriptor.get("warnings", [])
    require(isinstance(warnings, list) and len(warnings) <= 35 and
            all(isinstance(w, str) and len(w) <= 500 for w in warnings),
            "storage_integrity_failed", "Stored warning metadata is invalid.")
    return {"status": "download_ready", "package_id": package_id,
            "package_scope": "preliminary_raster_review_only", "package_bytes": size,
            "package_sha256": checksum, "files": files, "download_url": url,
            "download_url_expires_at_utc": (now+timedelta(seconds=LINK_SECONDS)).isoformat(),
            "download_url_lifetime_seconds": LINK_SECONDS,
            "classification_rerun": False, "storage_uploaded": True,
            "workstation_delivery_verified": False,
            "warnings": ["Anyone holding this temporary link can download the package until it expires.",
                         "This is a raster-only package, not the complete polygon/GeoPackage deliverable.",
                         "Export does not verify professional review or independent classification accuracy."] + warnings}

def store_package(client, config, package):
    package_id = _package_id(package["package_id"])
    archive = Path(package["archive_path"])
    require(archive.stat().st_size == package["package_bytes"] <= MAX_BYTES,
            "package_changed", "Local archive size changed before upload.")
    key = _key(config, package_id, "mapcp_raster_review.zip")
    with archive.open("rb") as body:
        _put(client, config, key, body, "application/zip", package["package_sha256"])
    _verify_zip(client, config, key, package["package_bytes"], package["package_sha256"])
    descriptor = {k: package[k] for k in ("package_id", "package_bytes", "package_sha256", "files", "job_id", "crosswalk_version", "warnings")}
    descriptor["schema_version"] = "1"
    descriptor["package_scope"] = "preliminary_raster_review_only"
    raw = json.dumps(descriptor, allow_nan=False).encode("utf-8")
    require(len(raw) <= DESCRIPTOR_MAX, "size_limit", "Package descriptor exceeds its size limit.")
    desc_key = _key(config, package_id, "package_record.json")
    _put(client, config, desc_key, io.BytesIO(raw), "application/json", hashlib.sha256(raw).hexdigest())
    require(_get_bounded(client, config, desc_key, DESCRIPTOR_MAX) == raw,
            "storage_integrity_failed", "Stored package record failed read-back verification.")
    return _link(client, config, descriptor)

def renew_package(client, config, package_id):
    package_id = _package_id(package_id)
    raw = _get_bounded(client, config, _key(config, package_id, "package_record.json"), DESCRIPTOR_MAX)
    descriptor = read_json_bytes(raw)
    require(descriptor.get("package_id") == package_id and descriptor.get("schema_version") == "1" and
            descriptor.get("package_scope") == "preliminary_raster_review_only",
            "storage_integrity_failed", "Stored package identity is invalid.")
    result = _link(client, config, descriptor, verify_contents=True)
    result["storage_uploaded"] = False
    result["link_renewed"] = True
    return result

def deliver_review_package(outputs_dir, request, *, env=None, client_factory=None, builder=None):
    env = os.environ if env is None else env
    if env.get("MAPCP_REVIEW_EXPORT_ENABLED") != "true":
        return {"status": "disabled", "error_code": "export_not_enabled",
                "message": "Review export is disabled. An administrator must complete storage and host approval-control setup.",
                "classification_rerun": False}
    stage = "validate_request"
    package_id = None
    try:
        require(isinstance(request, dict) and set(request) <= {"action", "methods_filename", "package_id"},
                "invalid_input", "Unsupported export inputs.")
        action = request.get("action")
        methods, existing = request.get("methods_filename"), request.get("package_id")
        require(action in {"create", "renew"}, "invalid_input", "Action must be create or renew.")
        if action == "create":
            require(type(methods) is str and existing is None, "invalid_input", "Create requires only a methods filename.")
        else:
            require(methods is None, "invalid_input", "Renew accepts only an existing package ID.")
            _package_id(existing)
        stage = "configure_storage"
        config = StorageConfig.from_environment(env)
        client = (client_factory or make_client)(config)
        if action == "renew":
            stage = "renew_link"
            return renew_package(client, config, existing)
        stage = "validate_and_package"
        package = (builder or build_review_package)(outputs_dir, methods)
        package_id = package["package_id"]
        stage = "upload_verify_and_link"
        return store_package(client, config, package)
    except ExportError as exc:
        return {"status": "failed", "stage": stage, "error_code": exc.code,
                "message": str(exc), "package_id": package_id,
                "classification_rerun": False,
                "warning": "Failed storage operations can leave partial remote objects. No automatic retry, deletion, or permission change was attempted."}
    except Exception:
        return {"status": "failed", "stage": stage, "error_code": "unexpected_export_error",
                "message": "Export failed. Inspect protected administrator diagnostics; do not expose credentials in chat.",
                "package_id": package_id, "classification_rerun": False}
