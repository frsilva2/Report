"""Modelos de dados (SQLAlchemy 2.0).

Nota LGPD: `face_embedding` guarda um *vetor* biométrico, não a imagem.
As selfies de cada check-in NÃO são persistidas por padrão (minimização de
dados sensíveis, Art. 5/11 LGPD) — guardamos apenas os scores. Ver docs/ARCHITECTURE.md.
"""
from datetime import datetime, timezone
import enum

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(dt: datetime | None) -> datetime | None:
    """SQLite devolve datetimes *naive*; Postgres devolve *aware*. Para comparar
    com utcnow() (aware) sem erro, normalizamos assumindo UTC quando naive."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class Role(str, enum.Enum):
    employee = "employee"    # funcionário de campo
    operator = "operator"    # central/retaguarda
    admin = "admin"


class ShiftStatus(str, enum.Enum):
    scheduled = "scheduled"
    active = "active"
    closed = "closed"


class CheckType(str, enum.Enum):
    checkin = "checkin"
    checkout = "checkout"


class CheckStatus(str, enum.Enum):
    approved = "approved"
    rejected = "rejected"
    pending_review = "pending_review"   # aprovado offline, aguardando validação server-side


class ChallengeStatus(str, enum.Enum):
    pending = "pending"
    acknowledged = "acknowledged"
    missed = "missed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    cpf: Mapped[str | None] = mapped_column(String(14), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.employee)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Biometria facial base (embedding, não a foto). JSON serializado como texto.
    face_embedding: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Trilha de consentimento LGPD
    consent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consent_granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    shifts: Mapped[list["Shift"]] = relationship(back_populates="user")


class Site(Base):
    """Posto / local pré-cadastrado onde o funcionário deve fazer check-in."""
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float, default=100.0)  # raio "X" do geofence
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Produção PostGIS: adicionar coluna geography(Point,4326) + índice GIST.


class Shift(Base):
    """Turno de trabalho de um funcionário em um posto."""
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    status: Mapped[ShiftStatus] = mapped_column(Enum(ShiftStatus), default=ShiftStatus.scheduled)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="shifts")
    site: Mapped[Site] = relationship()


class CheckEvent(Base):
    """Registro de ponto (check-in/check-out) com evidências anti-fraude."""
    __tablename__ = "check_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True)
    type: Mapped[CheckType] = mapped_column(Enum(CheckType))
    status: Mapped[CheckStatus] = mapped_column(Enum(CheckStatus))
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # GPS
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)  # distância ao posto
    is_mock_location: Mapped[bool] = mapped_column(Boolean, default=False)
    is_rooted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Biometria (apenas scores, não a imagem)
    liveness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    face_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Origem / auditoria
    device_info: Mapped[str | None] = mapped_column(String(255), nullable=True)
    synced_from_offline: Mapped[bool] = mapped_column(Boolean, default=False)
    client_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeadManChallenge(Base):
    """Desafio periódico de 'homem-morto'. O SERVIDOR é a fonte da verdade:
    se não houver acknowledge dentro da janela, o webhook é disparado."""
    __tablename__ = "deadman_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[ChallengeStatus] = mapped_column(Enum(ChallengeStatus), default=ChallengeStatus.pending)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    webhook_fired: Mapped[bool] = mapped_column(Boolean, default=False)


class LivenessChallenge(Base):
    """Desafio de prova de vida ativa (sequência de ações). Emitido pelo servidor,
    de uso único e com prazo. O cliente executa e envia as métricas de movimento;
    o servidor valida (não confia num 'fiz sim' do cliente)."""
    __tablename__ = "liveness_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    nonce: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    actions: Mapped[str] = mapped_column(String(120))  # csv, ex.: "blink,turn_left"
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class PanicAlert(Base):
    __tablename__ = "panic_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class Telemetry(Base):
    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    battery_level: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0..100
    is_charging: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    network_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # wifi/4g/5g/offline
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
