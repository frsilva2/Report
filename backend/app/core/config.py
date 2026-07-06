"""Configuração central da aplicação (12-factor: tudo via variáveis de ambiente)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "WFM Segurança Patrimonial"
    ENV: str = "development"

    # Banco. PoC usa SQLite; em produção use PostgreSQL + PostGIS:
    # postgresql+psycopg2://user:pass@host:5432/wfm
    DATABASE_URL: str = "sqlite:///./wfm.db"

    # JWT
    SECRET_KEY: str = "troque-isto-em-producao-use-openssl-rand-hex-32"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12

    # Geofencing
    DEFAULT_GEOFENCE_RADIUS_M: float = 100.0
    # Máx. deslocamento plausível entre dois check-ins (m/s). ~30 m/s ≈ 108 km/h.
    MAX_PLAUSIBLE_SPEED_MPS: float = 30.0

    # Homem-morto (dead man switch)
    DEADMAN_INTERVAL_MINUTES: int = 30
    DEADMAN_JITTER_MINUTES: int = 5          # variação aleatória ±5 min
    DEADMAN_RESPONSE_WINDOW_SECONDS: int = 120
    # Para testes locais, defina algo curto (ex.: 1) via env.
    DEADMAN_SCHEDULER_ENABLED: bool = True

    # Liveness / reconhecimento facial
    # "stub" (PoC, sempre aprova) | "aws_rekognition"
    LIVENESS_PROVIDER: str = "stub"
    FACE_MATCH_THRESHOLD: float = 0.90       # similaridade mínima [0..1]
    LIVENESS_THRESHOLD: float = 0.80         # confiança de prova de vida [0..1]
    AWS_REGION: str = "sa-east-1"

    # Webhook da central (homem-morto perdido, pânico)
    CENTRAL_WEBHOOK_URL: str = ""
    WEBHOOK_TIMEOUT_SECONDS: float = 10.0

    CORS_ORIGINS: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
