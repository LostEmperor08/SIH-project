"""
Chakravyuh SETU — FastAPI backend.

    uvicorn main:app --reload --port 8000

Mounts:
  GET  /health
  POST /trace
  POST /threat-intel/sync
  POST /dossier/review
  GET  /graph/{chain}/{address}
  /ml/*   (when the chakravyuh-aiml package is importable)
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import get_settings
from app.routers import misc, trace

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
log = logging.getLogger("chakravyuh")

cfg = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("%s v%s starting in %s mode", cfg.app_name, cfg.version, cfg.environment)
    log.info("CORS origins: %s", cfg.cors_list)
    log.info("service-key auth: %s", "enabled" if cfg.has_service_key else "disabled")
    log.info("ML service: %s", cfg.ml_api_url or "not configured (rules-only scoring)")
    if not cfg.supabase_service_role_key:
        log.warning("SUPABASE_SERVICE_ROLE_KEY unset — persistence disabled")
    if not cfg.etherscan_api_key:
        log.warning("ETHERSCAN_API_KEY unset — BSC traces will fail with guidance")

    # Mount the ML router if the sibling package is on the path. Optional by
    # design: the gateway must run without the ML stack installed.
    try:
        from serving.inference import load_models          # type: ignore
        from serving.ml_router import router as ml_router  # type: ignore
        import os

        load_models(os.getenv("ARTIFACTS_DIR", "artifacts"))
        app.state.verify_officer = _verify_for_ml_router
        app.include_router(ml_router)
        log.info("ML router mounted at /ml")
    except ImportError:
        log.info("ML package not importable — /ml routes not mounted")
    except Exception as e:                                  # noqa: BLE001
        log.error("ML router failed to mount: %s", e)

    yield
    log.info("shutting down")


async def _verify_for_ml_router(request: Request):
    """Bridge: hands the ML router this app's own auth dependency."""
    from app.security import get_current_officer
    from fastapi.security import HTTPAuthorizationCredentials

    auth = request.headers.get("authorization", "")
    creds = (HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth[7:])
             if auth.lower().startswith("bearer ") else None)
    officer = await get_current_officer(request, creds, cfg)
    request.state.officer_id = officer.id
    request.state.officer_role = officer.role
    return officer


app = FastAPI(
    title=cfg.app_name,
    version=cfg.version,
    description="Live cryptocurrency fraud attribution and investigation platform",
    lifespan=lifespan,
    # No interactive docs in production: the schema enumerates every route
    # and field, which is a map for anyone probing the service.
    docs_url=None if cfg.environment == "production" else "/docs",
    redoc_url=None if cfg.environment == "production" else "/redoc",
    openapi_url=None if cfg.environment == "production" else "/openapi.json",
)

# ---- Control 6: restricted, configurable CORS ------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "x-api-key"],
    max_age=600,
)

if cfg.environment == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*.onrender.com", "*.fly.dev"])


# ---- request id + timing + security headers --------------------------
@app.middleware("http")
async def _observability(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.request_id = rid
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("[%s] unhandled error on %s %s", rid, request.method, request.url.path)
        raise
    ms = (time.perf_counter() - t0) * 1000
    response.headers["X-Request-ID"] = rid
    response.headers["X-Response-Time-ms"] = f"{ms:.1f}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if cfg.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if hasattr(request.state, "rate_remaining"):
        response.headers["X-RateLimit-Remaining"] = str(request.state.rate_remaining)
    log.info("[%s] %s %s -> %s (%.1fms)",
             rid, request.method, request.url.path, response.status_code, ms)
    return response


# ---- error handlers --------------------------------------------------
@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    """Readable validation errors — a rejected address should say why."""
    return JSONResponse(
        # literal 422: Starlette renamed the constant and deprecated the old
        # name, so either spelling warns on some versions
        status_code=422,
        content={
            "ok": False, "error": "validation_failed",
            "detail": [{"field": ".".join(str(x) for x in e["loc"][1:]),
                        "message": e["msg"]} for e in exc.errors()],
            "requestId": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """
    Never leak an internal traceback to a client. The request id ties the
    client's report back to the full detail in the server log.
    """
    rid = getattr(request.state, "request_id", None)
    log.exception("[%s] unhandled: %s", rid, exc)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": "internal_error", "requestId": rid},
    )


from app.routers import alerts, cases, evidence, integrations, misc, monitoring, reports, trace

app.include_router(misc.router)
app.include_router(trace.router)
app.include_router(alerts.router)
app.include_router(monitoring.router)
app.include_router(cases.router)
app.include_router(evidence.router)
app.include_router(reports.router)
app.include_router(integrations.router)


@app.get("/", include_in_schema=False)
async def root():
    return {"service": cfg.app_name, "version": cfg.version,
            "docs": "/docs" if cfg.environment != "production" else None}
