import asyncio
import hashlib
import json
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from mcp import Client, StdioServerParameters
from mcp.types import TextContent

PROJECT = Path(__file__).resolve().parent
SERVER = PROJECT / "server.py"


def text_of(result):
    return "\n".join(b.text for b in result.content if isinstance(b, TextContent))


def data_of(result):
    if isinstance(result.structured_content, dict):
        return result.structured_content
    for block in result.content:
        if isinstance(block, TextContent):
            try:
                value = json.loads(block.text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None


async def run_tests(report):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        cwd=str(PROJECT),
    )
    negative_cases = [
        (
            "empty_boundary_search_rejected",
            "find_bia_land_area_candidates",
            {"search_name": ""},
            "Enter a search name",
        ),
        (
            "path_argument_rejected",
            "inspect_mapping_inputs",
            {"boundary_filename": "../outside.geojson"},
            "Use the exact generated GeoJSON filename only",
        ),
        (
            "retired_tool_unavailable",
            "inspect_mapping_request",
            {},
            "Unknown tool",
        ),
    ]

    async with asyncio.timeout(120):
        async with Client(parameters) as client:
            for label, name, arguments, expected_message in negative_cases:
                started = time.perf_counter()
                result = await client.call_tool(name, arguments)
                message = text_of(result)
                passed = bool(result.is_error) and expected_message in message
                record = {
                    "test": label,
                    "tool": name,
                    "arguments": arguments,
                    "outcome": "PASS" if passed else "FAIL",
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "result": result.model_dump(mode="json"),
                }
                report["tests"].append(record)
                print(f"{record['outcome']}: {label}", flush=True)
                print(message, flush=True)
                if not passed:
                    raise RuntimeError(f"Unexpected result for {label}; stopping.")

            label = "live_public_boundary_search"
            arguments = {"search_name": "Mescalero"}
            started = time.perf_counter()
            result = await client.call_tool("find_bia_land_area_candidates", arguments)
            data = data_of(result)
            status = data.get("status") if data else None
            candidates = data.get("candidates") if data else None
            valid_candidates = (
                isinstance(candidates, list)
                and 1 <= len(candidates) <= 10
                and all(
                    isinstance(row, dict)
                    and isinstance(row.get("object_id"), int)
                    and row["object_id"] > 0
                    and isinstance(row.get("lar_name"), str)
                    and bool(row["lar_name"].strip())
                    for row in candidates
                )
                and data.get("candidate_count") == len(candidates)
                and isinstance(data.get("review_flags"), list)
                and bool(data["review_flags"])
            )
            passed = (
                not result.is_error
                and status == "candidates_found_review_required"
                and valid_candidates
            )
            outcome = "PASS" if passed else "BLOCKED" if status == "source_failed" else "FAIL"
            report["tests"].append({
                "test": label,
                "tool": "find_bia_land_area_candidates",
                "arguments": arguments,
                "outcome": outcome,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "result": result.model_dump(mode="json"),
            })
            print(f"{outcome}: {label}", flush=True)
            print(json.dumps(data, indent=2) if data else text_of(result), flush=True)


def main():
    stamp = datetime.now(timezone.utc)
    report = {
        "test_suite": "controlled_stdio_tool_calls_v1",
        "started_at_utc": stamp.isoformat(),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "mcp_sdk": version("mcp"),
        "server_file": str(SERVER),
        "server_sha256": None,
        "tests": [],
        "limitations": [
            "No raster download, LANDFIRE submission, or mapping tool execution.",
            "No accuracy evaluation or ArcGIS compatibility test.",
            "Rejected path is deliberately invalid; no external file is supplied.",
            "No simulated service failure; source failures are actual observed results.",
        ],
    }
    try:
        report["server_sha256"] = hashlib.sha256(SERVER.read_bytes()).hexdigest()
        asyncio.run(run_tests(report))
    except Exception as exc:
        report["exception"] = "".join(traceback.format_exception(exc))
        traceback.print_exception(exc)
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    outcomes = [r["outcome"] for r in report["tests"]]
    passed = len(outcomes) == 4 and all(value == "PASS" for value in outcomes) and "exception" not in report
    report["overall"] = "PASS" if passed else "INCOMPLETE_OR_FAILED"
    folder = PROJECT / "outputs" / "mcp_test_evidence"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"stdio_calls_{stamp.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print(f"\nEvidence: {path}")
    print("TOOL-CALL CHECK COMPLETE: 4/4 passed." if passed else "TOOL-CALL CHECK NOT PASSED: inspect results and evidence.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
