"""
Automated Sprint 2 API Smoke Verification Script.
Starts uvicorn on an ephemeral/target port (or hits a running server) and verifies:
  1. GET /api/public/timetable returns 200 without auth with branding + grid config + entities.
  2. GET /api/onboarding/templates/sessions returns valid CSV headers.
  3. POST /api/onboarding/validate returns passed=True on the preloaded ATC dataset.
  4. POST /api/solve runs Phase 3 + Phase 4 in < 2s with 0 hard violations, Before/After scorecard,
     and non-empty saturday_explanations.
  5. PUT /api/settings/schema rejects malformed JSON/schema with 400 and
     POST /api/settings/schema/reset restores defaults.
  6. PUT /api/settings/branding updates the institution name and is immediately reflected
     in GET /api/public/timetable (then restores original ATC branding).
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


BASE_URL = "http://127.0.0.1:8000"


def _http_request(
    method: str,
    path: str,
    body: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, Dict[str, str], bytes]:
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers.items()), err.read()


def _wait_for_server(timeout_s: float = 15.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            code, _, _ = _http_request("GET", "/api/health")
            if code == 200:
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("Timed out waiting for uvicorn server on 127.0.0.1:8000")


def run_smoke_tests() -> None:
    # 1. Public timetable without auth
    code, _, raw = _http_request("GET", "/api/public/timetable")
    assert code == 200, f"Expected 200 from /api/public/timetable, got {code}"
    pub = json.loads(raw.decode("utf-8"))
    assert "branding" in pub and pub["branding"]["institution_name"], "Missing branding"
    assert "grid_config" in pub and len(pub["grid_config"]["days"]) == 6, "Missing grid_config"
    assert len(pub["entities"]["cohorts"]) > 0, "Missing cohort entities"
    assert len(pub["entities"]["lecturers"]) > 0, "Missing lecturer entities"
    assert len(pub["entities"]["venues"]) > 0, "Missing venue entities"
    original_branding = dict(pub["branding"])
    print(
        f"[PASS] 1. GET /api/public/timetable -> 200 "
        f"(cohorts={len(pub['entities']['cohorts'])}, lecturers={len(pub['entities']['lecturers'])}, "
        f"venues={len(pub['entities']['venues'])}, sessions={len(pub['sessions'])})"
    )

    # Authenticate as admin
    login_body = json.dumps({"username": "admin", "password": "sundial-admin"}).encode("utf-8")
    code, _, raw = _http_request(
        "POST", "/api/auth/login", body=login_body, headers={"Content-Type": "application/json"}
    )
    assert code == 200, f"Admin login failed with {code}: {raw}"
    token = json.loads(raw.decode("utf-8"))["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # 2. Onboarding CSV template for sessions
    code, hdrs, raw = _http_request("GET", "/api/onboarding/templates/sessions", headers=auth_headers)
    assert code == 200, f"Expected 200 from templates/sessions, got {code}"
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    expected_headers = [
        "session_id",
        "module_code",
        "module_name",
        "session_type",
        "duration_periods",
        "cohorts",
        "lecturers",
        "is_evening_stream",
        "preferred_venue",
    ]
    assert rows[0] == expected_headers, f"Unexpected CSV headers: {rows[0]}"
    assert len(rows) == 3, f"Expected header + 2 example rows, got {len(rows)}"
    print(f"[PASS] 2. GET /api/onboarding/templates/sessions -> 200 (valid CSV headers + 2 example rows)")

    # 3. Onboarding validate on preloaded ATC dataset
    code, _, raw = _http_request("POST", "/api/onboarding/validate", headers=auth_headers)
    assert code == 200, f"Expected 200 from /api/onboarding/validate, got {code}: {raw}"
    val_report = json.loads(raw.decode("utf-8"))
    assert val_report["passed"] is True, f"Validation failed: {val_report['errors']}"
    assert val_report["summary"]["sessions"] == 1233
    print(
        f"[PASS] 3. POST /api/onboarding/validate -> passed=True "
        f"(summary={val_report['summary']})"
    )

    # 4. Solve endpoint (Phase 3 + Phase 4)
    t0 = time.perf_counter()
    solve_body = json.dumps({"use_pins": True}).encode("utf-8")
    code, _, raw = _http_request(
        "POST",
        "/api/solve",
        body=solve_body,
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    wall_s = time.perf_counter() - t0
    assert code == 200, f"Expected 200 from /api/solve, got {code}: {raw}"
    solve_res = json.loads(raw.decode("utf-8"))
    assert solve_res["status"] == "SOLVED"
    assert solve_res["hard_violations"] == 0, f"Hard violations: {solve_res['hard_violations']}"
    assert "scorecard" in solve_res and solve_res["scorecard"].get("enabled") is True
    assert len(solve_res["saturday_explanations"]) > 0, "Expected non-empty saturday_explanations"
    total_engine_s = (solve_res["solve_ms"] + solve_res["optimize_ms"]) / 1000.0
    assert total_engine_s < 2.0, f"Engine solve+optimize took {total_engine_s:.2f}s (>= 2.0s)"
    print(
        f"[PASS] 4. POST /api/solve -> SOLVED in {total_engine_s:.2f}s "
        f"(solve={solve_res['solve_ms']}ms, opt={solve_res['optimize_ms']}ms, wall={wall_s:.2f}s, "
        f"hard_violations=0, improvement=-{solve_res['scorecard']['improvementPct']}%, "
        f"sat_explanations={len(solve_res['saturday_explanations'])})"
    )

    # 5. Schema validation rejects malformed JSON/schema with 400, reset restores defaults
    code, _, _ = _http_request(
        "PUT",
        "/api/settings/schema",
        body=b"{not valid json",
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert code == 400, f"Expected 400 for malformed JSON, got {code}"

    code, _, _ = _http_request(
        "PUT",
        "/api/settings/schema",
        body=json.dumps({"calendar_grid": {"active_days": []}}).encode("utf-8"),
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert code == 400, f"Expected 400 for invalid schema structure, got {code}"

    code, _, raw = _http_request("POST", "/api/settings/schema/reset", headers=auth_headers)
    assert code == 200, f"Expected 200 from schema reset, got {code}"
    reset_res = json.loads(raw.decode("utf-8"))
    assert reset_res["schema_config"]["institution"]["code"] == "ATC"
    print("[PASS] 5. PUT /api/settings/schema -> 400 on invalid payloads & POST /api/settings/schema/reset -> 200")

    # 6. Update branding and verify immediate reflection in GET /api/public/timetable
    new_name = "Arusha Technical College — Sprint 2 Verified"
    code, _, raw = _http_request(
        "PUT",
        "/api/settings/branding",
        body=json.dumps({"institution_name": new_name}).encode("utf-8"),
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert code == 200, f"Expected 200 from branding update, got {code}"

    code, _, raw = _http_request("GET", "/api/public/timetable")
    assert code == 200
    pub_after = json.loads(raw.decode("utf-8"))
    assert pub_after["branding"]["institution_name"] == new_name, (
        f"Expected updated institution_name '{new_name}', got '{pub_after['branding']['institution_name']}'"
    )
    print("[PASS] 6. PUT /api/settings/branding -> immediately reflected in GET /api/public/timetable")

    # Restore original ATC branding so app_state.json stays clean
    _http_request(
        "PUT",
        "/api/settings/branding",
        body=json.dumps(
            {
                "institution_name": original_branding["institution_name"],
                "semester_title": original_branding["semester_title"],
            }
        ).encode("utf-8"),
        headers={**auth_headers, "Content-Type": "application/json"},
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.api.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_server(timeout_s=15.0)
        run_smoke_tests()
        print("\nALL SPRINT 2 SMOKE CHECKS PASSED!")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
