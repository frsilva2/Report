"""Schemas de entrada/saída (Pydantic v2)."""
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ---- Auth ----
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str

    class Config:
        from_attributes = True


# ---- Sites ----
class SiteCreate(BaseModel):
    name: str
    latitude: float
    longitude: float
    radius_m: float = 100.0


class SiteOut(SiteCreate):
    id: int
    is_active: bool

    class Config:
        from_attributes = True


# ---- Sinais do dispositivo (anti-fraude) ----
class DeviceSignals(BaseModel):
    """Sinais que o cliente reporta. No app nativo vêm de Play Integrity /
    isFromMockProvider / safe_device. No webapp são limitados (ver docs)."""
    is_mock_location: bool = False
    is_rooted: bool = False
    device_info: str | None = None


# ---- Check-in ----
class CheckinRequest(BaseModel):
    site_id: int
    type: str = Field(default="checkin", pattern="^(checkin|checkout)$")
    latitude: float
    longitude: float
    accuracy_m: float | None = None
    client_timestamp: datetime | None = None
    signals: DeviceSignals = DeviceSignals()
    # selfie enviada como multipart (arquivo), não aqui — ver rota.


class LivenessChallengeOut(BaseModel):
    nonce: str
    actions: list[str]      # ex.: ["blink", "turn_left"]
    deadline_at: datetime
    window_seconds: int


class CheckinResult(BaseModel):
    status: str                 # approved | rejected | pending_review
    check_event_id: int | None = None
    distance_m: float | None = None
    liveness_score: float | None = None
    face_match_score: float | None = None
    reason: str | None = None
    shift_id: int | None = None


# ---- Homem-morto ----
class DeadManAck(BaseModel):
    challenge_id: int


class ChallengeOut(BaseModel):
    id: int
    scheduled_at: datetime
    deadline_at: datetime
    status: str

    class Config:
        from_attributes = True


# ---- Pânico ----
class PanicRequest(BaseModel):
    latitude: float
    longitude: float


# ---- Telemetria ----
class TelemetryIn(BaseModel):
    battery_level: int | None = Field(default=None, ge=0, le=100)
    is_charging: bool | None = None
    network_type: str | None = None


# ---- Sync offline ----
class OfflineCheckin(CheckinRequest):
    """Check-in feito offline. A selfie vai como base64 no lote de sync."""
    selfie_base64: str | None = None
    liveness_score: float | None = None   # validado no cliente/no re-envio
    face_match_score: float | None = None


class OfflineSyncRequest(BaseModel):
    events: list[OfflineCheckin]
