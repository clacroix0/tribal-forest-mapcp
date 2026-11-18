"""Single-operator browser approval. Disabled by default; no approval MCP tool.

Local SQLite and project_data require approved persistent storage before live use.
Approval authorizes configuration saving, not mapping or export.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

import crosswalk_configuration_save as local
from source_configuration_workflow import SourceReviewRequest, review_source_configuration

ID = re.compile(r"cr_[0-9a-f]{32}\Z")
SCHEMA = "mapcp_browser_configuration_approval_v1"
MAX_BYTES = 4_000_000
MAX_REVIEWS = 64
TTL_SECONDS = 1800
HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
_rate_lock = threading.Lock()
_failures = {}


class ReviewError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReviewError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class Settings:
    origin: str
    username: str
    password: str = field(repr=False)
    signing_key: str = field(repr=False)
    state_dir: Path

    @classmethod
    def from_env(cls):
        require(os.environ.get("MAPCP_CONFIG_REVIEW_ENABLED") == "true",
                "Configuration review is disabled.")
        require(os.environ.get("MAPCP_CONFIG_STORAGE_APPROVED") == "true",
                "Configuration storage has not been approved.")
        origin = os.environ.get("MAPCP_CONFIG_REVIEW_ORIGIN", "")
        u = urlsplit(origin)
        require(u.scheme == "https" and u.netloc and not u.username
                and not u.password and u.path == "" and not u.query
                and not u.fragment, "An exact HTTPS review origin is required.")
        username = os.environ.get("MAPCP_CONFIG_REVIEW_USER", "")
        password = os.environ.get("MAPCP_CONFIG_REVIEW_PASSWORD", "")
        key = os.environ.get("MAPCP_CONFIG_SIGNING_KEY", "")
        api = os.environ.get("MAPCP_API_TOKEN", "")
        require(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", username),
                "A controlled operator username is required.")
        require(all(len(x) >= 32 and x.isascii() and not any(c.isspace() for c in x)
                    for x in (password, key)), "Separate strong runtime secrets are required.")
        require(len({password, key, api}) == 3,
                "Operator, signing, and MCP credentials must be different.")
        state = os.environ.get("MAPCP_CONFIG_STATE_DIR", "")
        require(state and Path(state).is_absolute(), "An approved absolute state directory is required.")
        return cls(origin, username, password, key, Path(state))


class ReviewService:
    def __init__(self, outputs_root, project_data_root, settings):
        self.outputs = Path(outputs_root).resolve()
        self.data = Path(project_data_root).resolve()
        self.settings = settings

    def _db(self, create=False):
        directory = self.settings.state_dir
        if create:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(directory.is_dir() and not directory.is_symlink(),
                "Review state storage is unavailable.")
        path = directory / "configuration_reviews.sqlite3"
        require(not path.is_symlink(), "Review state must not be a symlink.")
        if not create:
            require(path.is_file(), "Review state is unavailable.")
        db = sqlite3.connect(path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        if create:
            db.execute("""CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, result TEXT NOT NULL,
                result_digest TEXT NOT NULL, expires REAL NOT NULL,
                state TEXT NOT NULL, configuration_id TEXT,
                crosswalk_digest TEXT, record_digest TEXT)""")
        return db

    def _review(self, payload):
        request = SourceReviewRequest.model_validate(payload)
        result = review_source_configuration(self.outputs, self.data, request)
        require(result.get("status") == "draft_review_complete_requires_human_review",
                "Source review failed; no configuration saved.")
        require(len(canonical(result).encode()) <= MAX_BYTES,
                "Review exceeds the size limit.")
        return result

    def request_review(self, payload):
        request = SourceReviewRequest.model_validate(payload)
        payload = request.model_dump(mode="json")
        require(len(canonical(payload).encode()) <= MAX_BYTES, "Request too large.")
        result = self._review(payload)
        review_id = "cr_" + secrets.token_hex(16)
        expires = time.time() + TTL_SECONDS
        db = self._db(create=True)
        try:
            db.execute("BEGIN IMMEDIATE")
            require(db.execute("SELECT count(*) FROM reviews").fetchone()[0] < MAX_REVIEWS,
                    "Review capacity reached; administrator review required. Nothing pruned.")
            db.execute("INSERT INTO reviews VALUES (?,?,?,?,?,'pending',NULL,NULL,NULL)",
                       (review_id, canonical(payload), canonical(result), digest(result), expires))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return {"status": "human_browser_review_required", "review_id": review_id,
                "review_url": self.settings.origin + "/configuration-review/" + review_id,
                "expires_at_utc": datetime.fromtimestamp(expires, timezone.utc).isoformat(),
                "review_sha256": result["review"]["review_sha256"],
                "configuration_saved": False,
                "warnings": ["Operator authentication is required; the link does not authorize approval.",
                             "Approval saves only this crosswalk; it does not authorize mapping."]}

    def row(self, review_id):
        require(isinstance(review_id, str) and ID.fullmatch(review_id), "Invalid review ID.")
        db = self._db()
        try:
            row = db.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
            require(row is not None, "Review not found.")
            value = dict(row)
            require(digest(json.loads(value["result"])) == value["result_digest"],
                    "Stored review changed.")
            return value
        finally:
            db.close()

    def status(self, review_id):
        row = self.row(review_id)
        state = row["state"]
        if state == "pending" and time.time() >= row["expires"]:
            state = "expired"
        answer = {"status": state, "review_id": review_id,
                  "configuration_saved": state == "approved"}
        if state == "approved":
            crosswalk = local._read(self.data / "run_crosswalks" / row["configuration_id"])
            record = local._read(self.data / "approvals" / crosswalk["approval_record_filename"])
            self.validate(crosswalk, record)
            answer.update(configuration_id=row["configuration_id"],
                          crosswalk_filename=row["configuration_id"],
                          acquisition_directory=json.loads(row["payload"])["acquisition_directory"],
                          classification_performed=False)
        return answer

    def csrf(self, row):
        message = "csrf:" + row["id"] + ":" + row["result_digest"]
        return hmac.new(self.settings.signing_key.encode(), message.encode(), hashlib.sha256).hexdigest()

    def _signature(self, record):
        payload = {k: v for k, v in record.items() if k != "browser_signature"}
        return hmac.new(self.settings.signing_key.encode(), canonical(payload).encode(), hashlib.sha256).hexdigest()

    def decide(self, review_id, choice, csrf):
        require(choice in {"approve", "reject"}, "Explicit approve or reject required.")
        initial = self.row(review_id)
        require(isinstance(csrf, str) and hmac.compare_digest(csrf, self.csrf(initial)), "Invalid form token.")
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = dict(db.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone())
            require(row["state"] == "pending", "Review already decided; replay refused.")
            require(time.time() < row["expires"], "Review expired; request a new review.")
            if choice == "reject":
                db.execute("UPDATE reviews SET state='rejected' WHERE id=?", (review_id,))
                db.commit()
                return {"status": "rejected", "configuration_saved": False}
            result = self._review(json.loads(row["payload"]))
            require(digest(result) == row["result_digest"],
                    "Inputs or review changed; request a new review. No configuration saved.")
            require(time.time() < row["expires"], "Review expired during validation.")
            for dirname in ("run_crosswalks", "approvals"):
                target_dir = self.data / dirname
                require(not target_dir.is_symlink() and target_dir.resolve().parent == self.data,
                        "Configuration directory is not controlled.")
            key = "review_" + review_id[3:]
            name, cw, record_name, record = local._build_documents(result, key, "v1")
            cw.pop("approval_record_sha256", None)
            cw["crosswalk_approval_note"] = (
                "Exact project-specific review accepted by the configured prototype operator "
                "through the authenticated browser. Not Tribal approval or legal authority.")
            record["schema"] = SCHEMA
            record.pop("operator_confirmation_recorded", None)
            record.pop("identity_authenticated", None)
            record["approval_method"] = "separate_operator_authenticated_browser"
            record["browser_review_id"] = review_id
            record["browser_review_digest"] = row["result_digest"]
            record["browser_operator"] = self.settings.username
            record["accepted_at_utc"] = datetime.now(timezone.utc).isoformat()
            record["crosswalk_payload_sha256"] = digest(cw)
            record["browser_signature"] = self._signature(record)
            cw["approval_record_sha256"] = digest(record)
            # The approved DB marker is committed only after both files read back.
            # A storage failure can leave files, but never an approved marker.
            try:
                local._write_documents(self.data, name, cw, record_name, record)
                require(local._read(self.data / "run_crosswalks" / name) == cw
                        and local._read(self.data / "approvals" / record_name) == record,
                        "Configuration read-back failed.")
            except Exception:
                db.execute("UPDATE reviews SET state='failed_storage' WHERE id=?", (review_id,))
                db.commit()
                raise ReviewError("Storage failed; incomplete files may remain. Administrator review required.") from None
            db.execute("""UPDATE reviews SET state='approved', configuration_id=?,
                          crosswalk_digest=?, record_digest=? WHERE id=?""",
                       (name, digest(cw), digest(record), review_id))
            db.commit()
            return {"status": "approved", "configuration_saved": True,
                    "configuration_id": name, "crosswalk_filename": name,
                    "classification_performed": False}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def validate(self, crosswalk, record):
        require(record.get("schema") == SCHEMA, "Unsupported browser approval schema.")
        signature = record.get("browser_signature")
        require(isinstance(signature, str) and hmac.compare_digest(signature, self._signature(record)),
                "Browser approval signature invalid.")
        row = self.row(record.get("browser_review_id"))
        require(row["state"] == "approved", "Browser approval is not committed.")
        require(row["configuration_id"] == record.get("crosswalk_filename")
                and row["crosswalk_digest"] == digest(crosswalk)
                and row["record_digest"] == digest(record)
                and row["result_digest"] == record.get("browser_review_digest"),
                "Browser-approved configuration changed.")


def runtime_service(outputs_root=None, project_data_root=None):
    root = Path(__file__).resolve().parent
    return ReviewService(outputs_root or root / "outputs",
                         project_data_root or root / "project_data", Settings.from_env())


def validate_browser_approval(project_data_root, crosswalk, record):
    runtime_service(project_data_root=project_data_root).validate(crosswalk, record)


def _auth(request, settings):
    # Browser endpoints use independent HTTP Basic credentials over HTTPS only.
    if request.url.scheme != "https" or str(request.url).split("/configuration-review/", 1)[0] != settings.origin:
        return Response("HTTPS review origin mismatch.", status_code=403, headers=HEADERS)
    now = time.monotonic()
    peer = request.client.host if request.client else "unknown"
    with _rate_lock:
        for key in list(_failures):
            if now - _failures[key][0] >= 300:
                del _failures[key]
        entry = _failures.get(peer, (now, 0))
        if entry[1] >= 10 or (peer not in _failures and len(_failures) >= 1024):
            return Response("Too many authentication attempts.", status_code=429, headers=HEADERS)
    values = request.headers.getlist("authorization")
    expected = base64.b64encode((settings.username + ":" + settings.password).encode()).decode()
    valid = len(values) == 1 and hmac.compare_digest(values[0].encode(), ("Basic " + expected).encode())
    if not valid:
        with _rate_lock:
            _failures[peer] = (entry[0], entry[1] + 1)
        return Response("Operator authentication required.", status_code=401,
                        headers={**HEADERS, "WWW-Authenticate": 'Basic realm="MapCP configuration review", charset="UTF-8"'})
    return None


def _page(service, row):
    result = json.loads(row["result"])
    e = lambda x: html.escape(str(x), quote=True)
    proposal = result["proposal"]
    classes = {x["output_code"]: x["label"] for x in proposal["classes"]}
    names = {x["source_evt_code"]: x.get("official_name", "Unknown")
             for x in result["source_configuration"]["entries"]}
    rows = []
    for x in proposal["decisions"]:
        rows.append("<tr>" + "".join("<td>" + e(v) + "</td>" for v in (
            x["source_evt_code"], names.get(x["source_evt_code"], "Unknown"),
            x["output_code"], classes[x["output_code"]],
            {True: "true", False: "false", None: "unknown"}[x["proposed_forest_land"]],
            x["rationale"], "; ".join(x["unresolved"]))) + "</tr>")
    state = row["state"] if time.time() < row["expires"] else (
        "expired" if row["state"] == "pending" else row["state"])
    form = ""
    if state == "pending":
        form = ('<form method="post"><input type="hidden" name="csrf" value="'
                + e(service.csrf(row)) + '"><p>No option is selected by default.</p>'
                '<button name="decision" value="approve" type="submit">Approve and save this exact crosswalk</button> '
                '<button name="decision" value="reject" type="submit">Reject without saving a configuration</button></form>')
    return ('<!doctype html><html><head><meta charset="utf-8"><title>MapCP crosswalk review</title></head><body>'
            '<h1>Project-specific crosswalk review</h1><p>Preliminary planning only. '
            'Approval is not Tribal approval, geographic authority, or permission to run mapping.</p>'
            '<p>Close this page or cancel authentication if you do not wish to proceed. '
            'Use a private browser window on a trusted workstation; close it when finished.</p>'
            '<p>Review: ' + e(row["id"]) + ' | State: ' + e(state) + '</p>'
            '<p>Acquisition: ' + e(result["acquisition_directory"]) + '</p>'
            '<p>Review digest: ' + e(result["review"]["review_sha256"]) + '</p>'
            '<h2>Assignments</h2><table border="1"><thead><tr>'
            '<th>EVT</th><th>Official source label</th><th>Output code</th><th>Candidate class</th>'
            '<th>Forest land</th><th>Rationale</th><th>Unresolved</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table><h2>Complete reviewed evidence</h2>'
            '<p>Includes acreage, run binding, source evidence, and limitations. '
            'Unknown is not nonforest. NoData is not nonforest.</p><pre>'
            + e(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
            + '</pre>' + form + '</body></html>')


async def browser_review(request, outputs_root=None, project_data_root=None):
    if os.environ.get("MAPCP_CONFIG_REVIEW_ENABLED") != "true":
        return Response("Not found", status_code=404, headers=HEADERS)
    try:
        service = runtime_service(outputs_root, project_data_root)
    except Exception:
        return Response("Review service unavailable; administrator configuration required.",
                        status_code=503, headers=HEADERS)
    denied = _auth(request, service.settings)
    if denied is not None:
        return denied
    review_id = request.path_params["review_id"]
    try:
        if request.method in {"GET", "HEAD"}:
            row = await run_in_threadpool(service.row, review_id)
            return HTMLResponse(_page(service, row), headers=HEADERS)
        require(request.headers.get("origin") == service.settings.origin,
                "Approval origin mismatch.")
        require(request.headers.get("content-type", "").split(";", 1)[0]
                == "application/x-www-form-urlencoded", "Unsupported form content type.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            require(len(body) <= 2048, "Form too large.")
        form = parse_qs(body.decode("ascii"), strict_parsing=True, max_num_fields=2)
        require(set(form) == {"csrf", "decision"} and all(len(v) == 1 for v in form.values()),
                "Invalid approval form.")
        result = await run_in_threadpool(service.decide, review_id,
                                        form["decision"][0], form["csrf"][0])
        return HTMLResponse('<!doctype html><html><body><h1>MapCP review result</h1><pre>'
                            + html.escape(json.dumps(result, indent=2))
                            + '</pre><p>Return to Orchestrate and ask it to check the review status. '
                            'No mapping was performed.</p></body></html>', headers=HEADERS)
    except ReviewError:
        return Response("Review refused or unavailable. Check status in Orchestrate. "
                        "Storage failures may require administrator review; do not retry blindly.",
                        status_code=409, headers=HEADERS)
    except Exception:
        return Response("Review failed. Do not assume a configuration was saved; "
                        "administrator review may be required.", status_code=503, headers=HEADERS)


def browser_routes(outputs_root=None, project_data_root=None):
    async def endpoint(request):
        return await browser_review(request, outputs_root, project_data_root)
    return [Route("/configuration-review/{review_id}", endpoint, methods=["GET", "POST"])]
