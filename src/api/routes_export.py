from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response

from src.api.auth import require_admin
from src.api.pdf_export import (
    VALID_LENSES,
    render_master_timetable_pdf,
    render_single_timetable_pdf,
    sanitize_filename,
)
from src.api.state import AppStateManager

router = APIRouter(tags=["PDF Exports"])


def _get_manager(request: Request) -> AppStateManager:
    return request.app.state.manager


@router.get("/api/public/export/pdf")
def export_public_single_pdf(
    request: Request,
    lens: str = Query(..., description="Entity lens: cohort, lecturer, or venue"),
    id: str = Query(..., description="Entity identifier (e.g., CS7-2)"),
) -> Response:
    if lens.strip().lower() not in VALID_LENSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid lens '{lens}'. Valid lenses: {list(VALID_LENSES)}.",
        )

    manager = _get_manager(request)
    try:
        pdf_bytes = render_single_timetable_pdf(
            state=manager.state,
            lens=lens,
            entity_id=id,
            logo_path=manager.get_logo_path(),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc.args[0] if exc.args else exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    safe_id = sanitize_filename(id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_id}_timetable.pdf"'
        },
    )


@router.get("/api/export/master-pdf")
def export_master_pdf(
    request: Request,
    lens: str = Query("cohort", description="Entity lens: cohort, lecturer, or venue"),
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Response:
    lens_norm = lens.strip().lower()
    if lens_norm not in VALID_LENSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid lens '{lens}'. Valid lenses: {list(VALID_LENSES)}.",
        )

    manager = _get_manager(request)
    try:
        pdf_bytes = render_master_timetable_pdf(
            state=manager.state,
            lens=lens_norm,
            logo_path=manager.get_logo_path(),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc.args[0] if exc.args else exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="master_{lens_norm}_timetables.pdf"'
        },
    )
