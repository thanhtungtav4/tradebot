"""Health, liveness and readiness endpoints (01 §6, 09 §4)."""

import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.db.session import get_db
from app.services.health import collect_health

router = APIRouter()


@router.get("/live")
def live() -> dict:
    return {"status": "OK"}


@router.get("/api/v1/health/live")
def api_live() -> dict:
    return {"status": "OK"}


@router.get("/api/v1/health/ready")
def ready(db: Session = Depends(get_db)) -> JSONResponse:
    components: dict[str, dict] = {}
    overall = "OK"

    start = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        components["db"] = {
            "status": "OK",
            "latencyMs": round((time.perf_counter() - start) * 1000, 1),
        }
    except Exception as exc:  # noqa: BLE001
        components["db"] = {"status": "DOWN", "error": str(exc)[:200]}
        overall = "DOWN"

    start = time.perf_counter()
    try:
        Redis.from_url(get_settings().redis_url).ping()
        components["redis"] = {
            "status": "OK",
            "latencyMs": round((time.perf_counter() - start) * 1000, 1),
        }
    except Exception as exc:  # noqa: BLE001
        components["redis"] = {"status": "DOWN", "error": str(exc)[:200]}
        overall = "DOWN"

    return JSONResponse(
        status_code=200 if overall == "OK" else 503,
        content={"status": overall, "components": components},
    )


@router.get("/api/v1/health")
def health(db: Session = Depends(get_db)) -> JSONResponse:
    overall, components = collect_health(db, persist=True)
    status_code = 200 if overall == "OK" else 503
    return JSONResponse(status_code=status_code, content={"status": overall, "components": components})
