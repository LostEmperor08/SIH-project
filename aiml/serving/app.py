"""
Standalone FastAPI microservice for Chakravyuh SETU ML engine.
Run with:
    cd aiml
    python -m uvicorn serving.app:app --port 8001
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .inference import load_models
from .ml_router import router as ml_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load all 4 ML models from artifacts/
    artifacts_dir = os.getenv("ARTIFACTS_DIR", "artifacts")
    load_models(artifacts_dir)
    # Configure auth verifier: allow gateway service calls
    async def allow_service_calls(request):
        return True
    app.state.verify_officer = allow_service_calls
    yield


app = FastAPI(
    title="Chakravyuh SETU AI/ML Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ml_router)


@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Chakravyuh SETU AI/ML Model Engine",
        "docs": "/docs",
        "health": "/health",
        "ml_health": "/ml/health",
    }


@app.get("/health")
async def health():
    return {"ok": True, "service": "chakravyuh-aiml"}
