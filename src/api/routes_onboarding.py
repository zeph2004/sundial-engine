from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response

from src.api.auth import require_admin
from src.api.state import AppStateManager

router = APIRouter(tags=["Data Onboarding & Validation"])

ALLOWED_ENTITIES = ("venues", "lecturers", "sessions")

CSV_TEMPLATES: Dict[str, Tuple[List[str], List[List[str]]]] = {
    "venues": (
        ["venue_id", "name", "capacity", "venue_type", "department_prefix"],
        [
            ["101", "Lecture Hall A1", "120", "Theory / Lecture Room", "GEN"],
            ["102", "Computer Lab R42", "45", "Computer / Digital Lab", "CS"],
        ],
    ),
    "lecturers": (
        ["lecturer_id", "name", "department"],
        [
            ["L001", "Dr. Amina K. Hassan", "Computer Science"],
            ["L002", "Eng. Joseph M. Mollel", "Civil Engineering"],
        ],
    ),
    "sessions": (
        [
            "session_id",
            "module_code",
            "module_name",
            "session_type",
            "duration_periods",
            "cohorts",
            "lecturers",
            "is_evening_stream",
            "preferred_venue",
        ],
        [
            [
                "S0001",
                "CSU 07101",
                "Data Structures & Algorithms",
                "Theory",
                "2",
                "L7-1CS;L7-1IT",
                "Dr. Amina K. Hassan",
                "false",
                "Lecture Hall A1",
            ],
            [
                "S0002",
                "CSU 07102",
                "Database Systems Practical",
                "Lab",
                "4",
                "L7-1CS",
                "Dr. Amina K. Hassan;Eng. Joseph M. Mollel",
                "false",
                "Computer Lab R42",
            ],
        ],
    ),
}

VENUE_TYPE_TO_CATEGORY: Dict[str, str] = {
    "theory": "Theory / Lecture Room",
    "lecture": "Theory / Lecture Room",
    "lecture room": "Theory / Lecture Room",
    "theory / lecture room": "Theory / Lecture Room",
    "computer lab": "Computer / Digital Lab",
    "digital lab": "Computer / Digital Lab",
    "computer / digital lab": "Computer / Digital Lab",
    "lab": "Engineering / Science Lab",
    "science lab": "Engineering / Science Lab",
    "engineering lab": "Engineering / Science Lab",
    "engineering / science lab": "Engineering / Science Lab",
    "workshop": "Workshop",
    "field": "Field / Site",
    "site": "Field / Site",
    "field / site": "Field / Site",
    "studio": "Studio",
}


def _get_manager(request: Request) -> AppStateManager:
    return request.app.state.manager


def _parse_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    s = str(raw or "").strip().lower()
    return s in ("true", "1", "yes", "y")


def _split_semicolon(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [part.strip() for part in str(raw or "").split(";") if part.strip()]


def _normalize_venue_category(raw_type: str) -> str:
    cleaned = raw_type.strip()
    if not cleaned:
        return "Theory / Lecture Room"
    return VENUE_TYPE_TO_CATEGORY.get(cleaned.lower(), cleaned)


def _infer_required_category(session_type: str, raw_category: str = "") -> str:
    if raw_category.strip():
        return _normalize_venue_category(raw_category)
    st = session_type.strip().lower()
    if st in ("theory", "lecture", "tutorial"):
        return "Theory / Lecture Room"
    if "comp" in st or "digital" in st:
        return "Computer / Digital Lab"
    if "workshop" in st:
        return "Workshop"
    if "studio" in st:
        return "Studio"
    if "field" in st or "site" in st:
        return "Field / Site"
    return "Engineering / Science Lab"


def _parse_venues_rows(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    normalized: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for idx, row in enumerate(rows, start=1):
        vid_raw = row.get("venue_id", row.get("venueId"))
        name = str(row.get("name", "")).strip()
        if vid_raw is None or str(vid_raw).strip() == "":
            raise ValueError(f"venues row {idx}: missing required field 'venue_id'.")
        if not name:
            raise ValueError(f"venues row {idx}: missing required field 'name'.")

        vid_str = str(vid_raw).strip()
        vid: int | str = int(vid_str) if vid_str.isdigit() else vid_str

        cap_raw = row.get("capacity")
        cap: int | None = None
        if cap_raw is not None and str(cap_raw).strip() != "":
            try:
                cap = int(float(str(cap_raw).strip()))
            except ValueError as exc:
                raise ValueError(
                    f"venues row {idx}: invalid capacity '{cap_raw}' (must be an integer)."
                ) from exc

        vtype = str(row.get("venue_type", row.get("category", "Theory / Lecture Room"))).strip()
        cat = _normalize_venue_category(vtype)
        dept_pref = str(row.get("department_prefix", row.get("departmentPrefix", ""))).strip().upper()

        normalized.append(
            {
                "venueId": vid,
                "name": name,
                "rawName": name,
                "category": cat,
                "upstreamType": "Theory" if cat == "Theory / Lecture Room" else "Lab",
                "capacity": cap,
                "departmentPrefix": dept_pref,
                "location": str(row.get("location", "")).strip(),
            }
        )
    return normalized, warnings


def _parse_lecturers_rows(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    normalized: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for idx, row in enumerate(rows, start=1):
        lid = str(row.get("lecturer_id", row.get("lecturerId", ""))).strip()
        name = str(row.get("name", "")).strip()
        if not lid:
            raise ValueError(f"lecturers row {idx}: missing required field 'lecturer_id'.")
        if not name:
            raise ValueError(f"lecturers row {idx}: missing required field 'name'.")
        dept = str(row.get("department", "")).strip()
        normalized.append(
            {
                "lecturerId": lid,
                "name": name,
                "department": dept,
            }
        )
    return normalized, warnings


def _parse_sessions_rows(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    normalized: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for idx, row in enumerate(rows, start=1):
        sid = str(row.get("session_id", row.get("sessionId", ""))).strip()
        mod_code = str(row.get("module_code", row.get("moduleCode", ""))).strip()
        if not sid:
            raise ValueError(f"sessions row {idx}: missing required field 'session_id'.")
        if not mod_code:
            raise ValueError(f"sessions row {idx}: missing required field 'module_code'.")

        dur_raw = row.get("duration_periods", row.get("durationPeriods"))
        if dur_raw is None or str(dur_raw).strip() == "":
            raise ValueError(f"sessions row {idx}: missing required field 'duration_periods'.")
        try:
            dur = int(str(dur_raw).strip())
            if dur < 1:
                raise ValueError("must be >= 1")
        except ValueError as exc:
            raise ValueError(
                f"sessions row {idx}: invalid duration_periods '{dur_raw}' (must be a positive integer)."
            ) from exc

        mod_name = str(row.get("module_name", row.get("moduleName", mod_code))).strip()
        stype = str(row.get("session_type", row.get("sessionType", "Theory"))).strip() or "Theory"
        cohorts = _split_semicolon(row.get("cohorts", row.get("targetCohorts", [])))
        lecturers = _split_semicolon(row.get("lecturers", []))
        is_eve = _parse_bool(row.get("is_evening_stream", row.get("isEveningStream", False)))
        pref_venue = str(row.get("preferred_venue", row.get("preferredVenue", ""))).strip() or None
        req_cat = _infer_required_category(
            stype, str(row.get("required_venue_category", row.get("requiredVenueCategory", "")))
        )

        if not cohorts:
            warnings.append(f"Session '{sid}' (row {idx}) has no cohorts assigned.")
        if not lecturers:
            warnings.append(f"Session '{sid}' (row {idx}) has no lecturers assigned.")

        normalized.append(
            {
                "sessionId": sid,
                "moduleCode": mod_code,
                "moduleCodes": [mod_code],
                "moduleName": mod_name,
                "sessionType": stype,
                "requiredVenueCategory": req_cat,
                "durationPeriods": dur,
                "targetCohorts": cohorts,
                "cohortRaw": " + ".join(cohorts),
                "cohortLevel": str(row.get("cohortLevel", "")),
                "lecturers": lecturers,
                "isEveningStream": is_eve,
                "preferredVenue": pref_venue,
                "groundTruth": row.get("groundTruth")
                or {
                    "scheduledDay": "MONDAY",
                    "startPeriod": 1,
                    "endPeriod": dur,
                    "venueId": None,
                    "venueName": pref_venue or "",
                },
            }
        )
    return normalized, warnings


def _read_uploaded_records(entity: str, filename: str, raw_bytes: bytes) -> List[Dict[str, Any]]:
    ext = Path(filename).suffix.lower()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"File '{filename}' is not valid UTF-8 text: {exc}") from exc

    if ext == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON in '{filename}': {exc}") from exc
        if isinstance(data, dict) and entity in data and isinstance(data[entity], list):
            records = data[entity]
        elif isinstance(data, list):
            records = data
        else:
            raise ValueError(
                f"JSON upload for '{entity}' must be a JSON array or an object containing a '{entity}' array."
            )
        if not records:
            raise ValueError(f"Uploaded JSON for '{entity}' contains 0 records.")
        if not all(isinstance(r, dict) for r in records):
            raise ValueError(f"Every item in '{entity}' JSON array must be an object.")
        return records

    if ext == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError(f"CSV file '{filename}' is missing a header row.")
        headers = {h.strip() for h in reader.fieldnames if h}
        required_cols = set(CSV_TEMPLATES[entity][0])
        # Allow preferred_venue / department_prefix / department to be omitted as optional columns
        optional_cols = {"preferred_venue", "department_prefix", "department", "module_name"}
        missing = sorted((required_cols - optional_cols) - headers)
        if missing:
            raise ValueError(
                f"CSV file '{filename}' is missing required column(s) for '{entity}': {missing}. "
                f"Found columns: {sorted(headers)}."
            )
        records = [
            {k.strip(): v for k, v in row.items() if k is not None}
            for row in reader
            if any(str(v or "").strip() for v in row.values())
        ]
        if not records:
            raise ValueError(f"CSV file '{filename}' contains header only and 0 data rows.")
        return records

    raise ValueError(
        f"Unsupported file extension '{ext or '(none)'}'. Please upload a .csv or .json file."
    )


@router.get("/api/onboarding/status")
def get_onboarding_status(
    request: Request,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    manager = _get_manager(request)
    sources = manager.state.get("onboarding_sources", {})
    return {
        "dataset_mode": manager.state.get("dataset_mode", "1233_clean"),
        "entities": sources,
    }


@router.get("/api/onboarding/templates/{entity}")
def download_onboarding_template(
    entity: str,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Response:
    if entity not in CSV_TEMPLATES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown entity '{entity}'. Valid entities: {list(ALLOWED_ENTITIES)}.",
        )

    headers, sample_rows = CSV_TEMPLATES[entity]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in sample_rows:
        writer.writerow(row)

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{entity}_template.csv"'
        },
    )


@router.post("/api/onboarding/upload/{entity}")
async def upload_onboarding_entity(
    entity: str,
    request: Request,
    file: UploadFile = File(...),
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    if entity not in ALLOWED_ENTITIES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown entity '{entity}'. Valid entities: {list(ALLOWED_ENTITIES)}.",
        )

    manager = _get_manager(request)
    filename = file.filename or f"{entity}.csv"
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Uploaded file '{filename}' is empty.",
        )

    try:
        raw_records = _read_uploaded_records(entity, filename, raw_bytes)
        if entity == "venues":
            normalized, warnings = _parse_venues_rows(raw_records)
        elif entity == "lecturers":
            normalized, warnings = _parse_lecturers_rows(raw_records)
        else:
            normalized, warnings = _parse_sessions_rows(raw_records)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Save normalized JSON to data/uploads/{entity}.json
    manager.uploads_dir.mkdir(parents=True, exist_ok=True)
    out_file = manager.uploads_dir / f"{entity}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2)
        f.write("\n")

    manager.update_entity_data(entity=entity, rows=normalized, filename=filename)
    return {
        "entity": entity,
        "rows_loaded": len(normalized),
        "warnings": warnings,
    }


@router.post("/api/onboarding/validate")
def validate_onboarding_data(
    request: Request,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    manager = _get_manager(request)
    return manager.validate_active_dataset()
