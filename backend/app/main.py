"""Ponto de entrada da API WFM Segurança Patrimonial."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.db.session import Base, engine
from app.api.routes import auth, checkin, deadman, panic, shifts, sites, sync, telemetry
from app.services.deadman import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)  # PoC. Em produção: Alembic migrations.
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth, sites, shifts, checkin, deadman, panic, telemetry, sync):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "env": settings.ENV}


@app.get("/api/config")
def client_config():
    """Config visível ao front (o que muda o comportamento do cliente)."""
    return {
        "app_name": settings.APP_NAME,
        "require_liveness_challenge": settings.REQUIRE_LIVENESS_CHALLENGE,
    }


# Serve o webapp PoC (../webapp) em /app quando presente.
try:
    app.mount("/app", StaticFiles(directory="../webapp", html=True), name="webapp")
except Exception:  # noqa: BLE001 — diretório pode não existir em alguns deploys
    pass
