"""Endpoints da central/retaguarda (painel). Somente operador/admin.

Alimenta o dashboard: resumo, feed de eventos de ponto, alertas de pânico e
homem-morto perdido, lista de usuários e postos. O painel faz polling em
/live para atualização quase em tempo real (simples e robusto; WebSocket pode
entrar depois).
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_operator
from app.db.session import get_db
from app.models.models import (
    ChallengeStatus, CheckEvent, CheckStatus, DeadManChallenge, PanicAlert,
    Shift, ShiftStatus, Site, Telemetry, User,
)
from app.models.models import ensure_aware, utcnow

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_operator)])


def _names(db: Session) -> dict[int, str]:
    return {u.id: u.name for u in db.scalars(select(User)).all()}


def _site_names(db: Session) -> dict[int, str]:
    return {s.id: s.name for s in db.scalars(select(Site)).all()}


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    since = utcnow() - timedelta(hours=24)
    active_shifts = db.scalar(select(func.count(Shift.id)).where(Shift.status == ShiftStatus.active))
    open_panics = db.scalar(select(func.count(PanicAlert.id)).where(PanicAlert.resolved.is_(False)))
    missed = db.scalar(select(func.count(DeadManChallenge.id)).where(
        DeadManChallenge.status == ChallengeStatus.missed))
    approved = db.scalar(select(func.count(CheckEvent.id)).where(
        CheckEvent.status == CheckStatus.approved, CheckEvent.server_timestamp >= since))
    rejected = db.scalar(select(func.count(CheckEvent.id)).where(
        CheckEvent.status == CheckStatus.rejected, CheckEvent.server_timestamp >= since))
    return {
        "active_shifts": active_shifts or 0,
        "open_panics": open_panics or 0,
        "missed_deadman": missed or 0,
        "checkins_24h": {"approved": approved or 0, "rejected": rejected or 0},
    }


@router.get("/events")
def events(db: Session = Depends(get_db),
           status_: str | None = Query(None, alias="status"),
           limit: int = Query(30, le=200)):
    q = select(CheckEvent).order_by(CheckEvent.server_timestamp.desc()).limit(limit)
    if status_ in ("approved", "rejected", "pending_review"):
        q = q.where(CheckEvent.status == CheckStatus(status_))
    users, sites = _names(db), _site_names(db)
    out = []
    for e in db.scalars(q):
        out.append({
            "id": e.id, "user": users.get(e.user_id, f"#{e.user_id}"),
            "site": sites.get(e.site_id, f"#{e.site_id}"),
            "type": e.type.value, "status": e.status.value, "reason": e.rejection_reason,
            "distance_m": round(e.distance_m, 1) if e.distance_m is not None else None,
            "latitude": e.latitude, "longitude": e.longitude,
            "liveness": e.liveness_score, "match": e.face_match_score,
            "is_mock": e.is_mock_location, "ip": e.client_ip,
            "at": ensure_aware(e.server_timestamp).isoformat(),
        })
    return out


@router.get("/live")
def live(db: Session = Depends(get_db)):
    """Alertas ativos para o feed em tempo real: pânicos abertos + homem-morto perdido."""
    users = _names(db)
    panics = [{
        "id": p.id, "user": users.get(p.user_id, f"#{p.user_id}"),
        "latitude": p.latitude, "longitude": p.longitude,
        "at": ensure_aware(p.created_at).isoformat(),
    } for p in db.scalars(select(PanicAlert).where(PanicAlert.resolved.is_(False))
                          .order_by(PanicAlert.created_at.desc()).limit(50))]
    missed = [{
        "id": c.id, "user": users.get(c.user_id, f"#{c.user_id}"), "shift_id": c.shift_id,
        "deadline_at": ensure_aware(c.deadline_at).isoformat(),
    } for c in db.scalars(select(DeadManChallenge).where(
        DeadManChallenge.status == ChallengeStatus.missed)
        .order_by(DeadManChallenge.deadline_at.desc()).limit(50))]
    return {"panics": panics, "missed_deadman": missed}


@router.post("/panics/{panic_id}/resolve")
def resolve_panic(panic_id: int, db: Session = Depends(get_db)):
    p = db.get(PanicAlert, panic_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerta não encontrado")
    p.resolved = True
    db.commit()
    return {"status": "resolved", "id": panic_id}


@router.get("/users")
def users(db: Session = Depends(get_db)):
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role.value}
            for u in db.scalars(select(User).order_by(User.name))]


@router.get("/telemetry/latest")
def telemetry_latest(db: Session = Depends(get_db)):
    """Última telemetria por usuário (bateria/rede) para o painel."""
    users = _names(db)
    rows = db.scalars(select(Telemetry).order_by(Telemetry.created_at.desc()).limit(200)).all()
    seen, out = set(), []
    for t in rows:
        if t.user_id in seen:
            continue
        seen.add(t.user_id)
        out.append({"user": users.get(t.user_id, f"#{t.user_id}"),
                    "battery_level": t.battery_level, "is_charging": t.is_charging,
                    "network_type": t.network_type, "at": ensure_aware(t.created_at).isoformat()})
    return out
