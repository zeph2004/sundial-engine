from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.api.auth import (
    TOKEN_EXPIRY_SECONDS,
    create_access_token,
    require_admin,
    verify_admin_credentials,
)
from src.api.routes_onboarding import router as onboarding_router
from src.api.routes_public import router as public_router
from src.api.routes_settings import router as settings_router
from src.api.routes_solve import router as solve_router
from src.api.state import AppStateManager


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = TOKEN_EXPIRY_SECONDS


class BrandingUpdateRequest(BaseModel):
    institution_name: Optional[str] = None
    semester_title: Optional[str] = None
    logo_url: Optional[str] = None


class PinSlotRequest(BaseModel):
    day: int | str = Field(..., description="Day index (0..5) or day name ('MONDAY'..'SATURDAY')")
    start_period: int = Field(..., ge=1, le=18)
    venue_id: int | str


class PinSessionRequest(PinSlotRequest):
    session_id: str


def create_app(state_manager: Optional[AppStateManager] = None) -> FastAPI:
    app = FastAPI(
        title="Sundial Engine — Academic Timetabling CSP & SA Optimizer API",
        version="1.1.0",
        description="Single-institution academic timetable solver with onboarding, settings, session pinning, and simulated annealing optimization.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    manager = state_manager or AppStateManager()
    app.state.manager = manager

    # Mount Sprint 2 modular routers
    app.include_router(settings_router)
    app.include_router(onboarding_router)
    app.include_router(solve_router)
    app.include_router(public_router)

    @app.get("/api/health", tags=["System"])
    def health_check() -> Dict[str, Any]:
        return {
            "status": "ok",
            "dataset_mode": manager.state.get("dataset_mode", "1233_clean"),
            "sessions": len(manager.state.get("sessions", [])),
            "pinned": len(manager.state.get("pinned_assignments", {})),
        }

    @app.post("/api/auth/login", response_model=TokenResponse, tags=["Authentication"])
    def login(req: LoginRequest) -> TokenResponse:
        if not verify_admin_credentials(req.username, req.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid admin username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = create_access_token(username=req.username)
        return TokenResponse(access_token=token)

    @app.get("/api/auth/me", tags=["Authentication"])
    def auth_me(claims: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
        return {"authenticated": True, "admin": claims}

    @app.get("/api/state", tags=["Workspace State"])
    def get_state_summary() -> Dict[str, Any]:
        return manager.get_summary()

    @app.get("/api/state/full", tags=["Workspace State"])
    def get_full_state(_admin: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
        return manager.state

    @app.put("/api/branding", tags=["Settings & Branding"])
    def update_branding_compat(
        req: BrandingUpdateRequest,
        _admin: Dict[str, Any] = Depends(require_admin),
    ) -> Dict[str, Any]:
        updates = {k: v for k, v in req.model_dump().items() if v is not None or k == "logo_url"}
        return manager.update_branding(updates)

    @app.get("/api/pins", tags=["Session Pinning"])
    def list_pins() -> Dict[str, Any]:
        return {
            "pinned_count": len(manager.state.get("pinned_assignments", {})),
            "pinned_assignments": manager.state.get("pinned_assignments", {}),
        }

    @app.put("/api/pins/{session_id}", tags=["Session Pinning"])
    def upsert_pin_session(
        session_id: str,
        req: PinSlotRequest,
        _admin: Dict[str, Any] = Depends(require_admin),
    ) -> Dict[str, Any]:
        try:
            pin_entry = manager.set_pin(
                session_id=session_id,
                day=req.day,
                start_period=req.start_period,
                venue_id=req.venue_id,
            )
            return {"status": "pinned", "pin": pin_entry}
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.post("/api/pins", tags=["Session Pinning"])
    def pin_session(
        req: PinSessionRequest,
        _admin: Dict[str, Any] = Depends(require_admin),
    ) -> Dict[str, Any]:
        try:
            pin_entry = manager.set_pin(
                session_id=req.session_id,
                day=req.day,
                start_period=req.start_period,
                venue_id=req.venue_id,
            )
            return {"status": "pinned", "pin": pin_entry}
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.delete("/api/pins/{session_id}", tags=["Session Pinning"])
    def unpin_session(
        session_id: str,
        _admin: Dict[str, Any] = Depends(require_admin),
    ) -> Dict[str, Any]:
        removed = manager.remove_pin(session_id)
        return {"status": "unpinned" if removed else "not_found", "session_id": session_id}

    @app.delete("/api/pins", tags=["Session Pinning"])
    def clear_all_pins(
        _admin: Dict[str, Any] = Depends(require_admin),
    ) -> Dict[str, Any]:
        cleared = manager.clear_pins()
        return {"status": "cleared", "cleared_count": cleared}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.main:app", host="127.0.0.1", port=8000, reload=True)
