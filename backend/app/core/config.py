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

    # #4 Gate de qualidade do GPS
    MAX_GPS_ACCURACY_M: float = 100.0        # rejeita fix impreciso demais
    MAX_FIX_AGE_SECONDS: int = 120           # rejeita posição "velha"/cacheada

    # #5 Cruzamento GPS × IP (opcional; requer geoip2 + base GeoLite2)
    GEOIP_ENABLED: bool = False
    GEOIP_DB_PATH: str = ""
    GEOIP_MAX_DIVERGENCE_KM: float = 200.0   # divergência acima disso = rejeita/flag

    # #8 Janela de turno
    REQUIRE_SHIFT_WINDOW: bool = False       # exige check-in dentro da escala
    SHIFT_GRACE_MINUTES: int = 30            # tolerância antes/depois do horário

    # Homem-morto (dead man switch)
    DEADMAN_INTERVAL_MINUTES: int = 30
    DEADMAN_JITTER_MINUTES: int = 5          # variação aleatória ±5 min
    DEADMAN_RESPONSE_WINDOW_SECONDS: int = 120
    # Para testes locais, defina algo curto (ex.: 1) via env.
    DEADMAN_SCHEDULER_ENABLED: bool = True

    # Liveness / reconhecimento facial
    # "stub" (PoC) | "deepface" | "serpro_datavalid" | "aws_rekognition"
    LIVENESS_PROVIDER: str = "stub"
    FACE_MATCH_THRESHOLD: float = 0.90       # similaridade mínima [0..1]
    LIVENESS_THRESHOLD: float = 0.80         # confiança de prova de vida [0..1]
    AWS_REGION: str = "sa-east-1"

    # DeepFace (matcher self-hosted, custo R$0/consulta)
    DEEPFACE_MODEL: str = "ArcFace"
    DEEPFACE_DETECTOR: str = "opencv"

    # Liveness ATIVA por desafio de movimento (validada no servidor)
    REQUIRE_LIVENESS_CHALLENGE: bool = True
    # Pool de ações e quantas sortear por desafio.
    LIVENESS_ACTIONS: str = "blink,turn_left,turn_right,smile"
    LIVENESS_ACTIONS_PER_CHALLENGE: int = 2
    LIVENESS_CHALLENGE_WINDOW_SECONDS: int = 30
    # Limiares das métricas (blendshapes/landmarks MediaPipe) que provam cada ação.
    # blink/smile usam blendshapes do MediaPipe (0..1); yaw vem dos landmarks (graus).
    LIVENESS_BLINK_MIN: float = 0.45         # score de olho fechado acima disso = piscou
    LIVENESS_TURN_YAW_DEG: float = 18.0      # |yaw| acima disso = virou a cabeça
    LIVENESS_SMILE_MIN: float = 0.55         # score de sorriso mínimo

    # Serpro Datavalid (validação facial contra a base oficial do governo)
    # Credenciais na Área do Cliente do Serpro. NÃO versione.
    DATAVALID_BASE_URL: str = "https://gateway.apiserpro.serpro.gov.br"
    DATAVALID_TOKEN_PATH: str = "/token"
    DATAVALID_FACE_PATH: str = "/datavalid/v4/pf-facial"  # confirme no seu contrato
    DATAVALID_CONSUMER_KEY: str = ""
    DATAVALID_CONSUMER_SECRET: str = ""
    DATAVALID_TIMEOUT_SECONDS: float = 20.0

    # Webhook da central (homem-morto perdido, pânico)
    CENTRAL_WEBHOOK_URL: str = ""
    WEBHOOK_TIMEOUT_SECONDS: float = 10.0

    CORS_ORIGINS: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
