from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.api.auth import require_admin
from src.api.state import AppStateManager

router = APIRouter(tags=["Settings & Branding"])

ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
ALLOWED_LOGO_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}
MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB


class BrandingUpdatePayload(BaseModel):
    institution_name: Optional[str] = None
    semester_title: Optional[str] = None


def _get_manager(request: Request) -> AppStateManager:
    return request.app.state.manager


@router.get("/api/settings")
def get_settings(
    request: Request,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    manager = _get_manager(request)
    return manager.get_settings()


@router.put("/api/settings/branding")
def update_settings_branding(
    payload: BrandingUpdatePayload,
    request: Request,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    manager = _get_manager(request)
    updates: Dict[str, Any] = {}
    if payload.institution_name is not None:
        name = payload.institution_name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="institution_name cannot be empty.",
            )
        updates["institution_name"] = name
    if payload.semester_title is not None:
        sem = payload.semester_title.strip()
        if not sem:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="semester_title cannot be empty.",
            )
        updates["semester_title"] = sem

    branding = manager.update_branding(updates)
    return {"status": "updated", "branding": branding}


@router.post("/api/settings/logo")
async def upload_logo(
    request: Request,
    file: UploadFile = File(...),
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    manager = _get_manager(request)
    orig_name = file.filename or ""
    ext = Path(orig_name).suffix.lower()
    if ext not in ALLOWED_LOGO_EXTENSIONS:
        ext = ALLOWED_LOGO_CONTENT_TYPES.get((file.content_type or "").lower(), "")
    if ext not in ALLOWED_LOGO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported logo format. Allowed formats: PNG, JPG, SVG, WEBP.",
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded logo file is empty.",
        )
    if len(content) > MAX_LOGO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Logo exceeds maximum allowed size of 2 MB ({len(content)} bytes received).",
        )

    manager.uploads_dir.mkdir(parents=True, exist_ok=True)
    # Remove any previous logo.* files so there is only one active logo file
    for old_ext in ALLOWED_LOGO_EXTENSIONS:
        old_path = manager.uploads_dir / f"logo{old_ext}"
        if old_path.exists():
            old_path.unlink()

    saved_name = f"logo{ext}"
    dest = manager.uploads_dir / saved_name
    dest.write_bytes(content)

    branding = manager.set_logo(saved_name)
    return {"status": "uploaded", "filename": saved_name, "branding": branding}


@router.get("/api/public/logo")
def get_public_logo(request: Request) -> FileResponse:
    manager = _get_manager(request)
    logo_path = manager.get_logo_path()
    if logo_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No institution logo has been uploaded.",
        )
    return FileResponse(path=str(logo_path))


@router.put("/api/settings/schema")
async def update_schema_config(
    request: Request,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    manager = _get_manager(request)
    try:
        raw_body = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed JSON body: {exc}",
        ) from exc

    if not isinstance(raw_body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be a JSON object.",
        )

    # Support either {"schema_config": {...}} wrapper or direct schema object
    schema_payload = (
        raw_body["schema_config"]
        if "schema_config" in raw_body and isinstance(raw_body["schema_config"], dict)
        else raw_body
    )

    try:
        updated = manager.replace_schema(schema_payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {"status": "updated", "schema_config": updated}


@router.post("/api/settings/schema/reset")
def reset_schema_config(
    request: Request,
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    manager = _get_manager(request)
    restored = manager.reset_schema_to_default()
    return {"status": "reset", "schema_config": restored}
