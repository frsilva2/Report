"""PoC — Check-in com validação de GPS + Câmera (reconhecimento facial/liveness).

Pipeline de validação (tudo server-side; o cliente não decide nada):

    1. Anti-Fake GPS   -> rejeita se mock/root reportado pelo device
    2. Geofence        -> recalcula distância ao posto; rejeita se fora do raio X
    3. Plausibilidade  -> rejeita 'teletransporte' vs. último evento (fake GPS server-side)
    4. Liveness+Face   -> selfie precisa passar prova de vida e bater com a foto base
    5. Persiste + (se check-in) ativa o turno e agenda o homem-morto
"""
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.models import (
    CheckEvent, CheckStatus, CheckType, Shift, ShiftStatus, Site, User,
)
from app.models.models import ensure_aware, utcnow
from app.schemas.schemas import CheckinResult
from app.services import geofencing
from app.services.deadman import schedule_next_challenge
from app.services.liveness import get_liveness_provider

router = APIRouter(prefix="/api/checkin", tags=["checkin"])


def _last_event(db: Session, user_id: int) -> CheckEvent | None:
    return db.scalars(
        select(CheckEvent)
        .where(CheckEvent.user_id == user_id, CheckEvent.status == CheckStatus.approved)
        .order_by(CheckEvent.server_timestamp.desc())
        .limit(1)
    ).first()


def _reject(db, user, site, ctype, lat, lon, acc, dist, is_mock, is_rooted, reason, dev) -> CheckinResult:
    """Persiste a tentativa rejeitada (auditoria) e retorna o resultado."""
    ev = CheckEvent(
        user_id=user.id, site_id=site.id, type=ctype, status=CheckStatus.rejected,
        rejection_reason=reason, latitude=lat, longitude=lon, accuracy_m=acc,
        distance_m=dist, is_mock_location=is_mock, is_rooted=is_rooted, device_info=dev,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return CheckinResult(status="rejected", check_event_id=ev.id, distance_m=dist, reason=reason)


@router.post("", response_model=CheckinResult)
async def check_in(
    site_id: int = Form(...),
    type: str = Form("checkin"),
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy_m: float | None = Form(None),
    client_timestamp: datetime | None = Form(None),
    is_mock_location: bool = Form(False),
    is_rooted: bool = Form(False),
    device_info: str | None = Form(None),
    selfie: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ctype = CheckType.checkin if type == "checkin" else CheckType.checkout
    site = db.get(Site, site_id)
    if not site or not site.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Posto não encontrado")

    dist = geofencing.haversine_m(latitude, longitude, site.latitude, site.longitude)

    # 1) Anti-Fake GPS (sinais do device). No webapp esses sinais são fracos/ausentes;
    #    por isso o passo 3 (plausibilidade) é a defesa real no navegador.
    if is_mock_location:
        return _reject(db, user, site, ctype, latitude, longitude, accuracy_m, dist,
                       is_mock_location, is_rooted, "Localização falsa (mock) detectada", device_info)
    if is_rooted:
        return _reject(db, user, site, ctype, latitude, longitude, accuracy_m, dist,
                       is_mock_location, is_rooted, "Dispositivo comprometido (root/jailbreak)", device_info)

    # 2) Geofence — recalculado no servidor.
    if dist > site.radius_m:
        return _reject(db, user, site, ctype, latitude, longitude, accuracy_m, dist,
                       is_mock_location, is_rooted,
                       f"Fora do raio permitido ({dist:.0f} m > {site.radius_m:.0f} m)", device_info)

    # 3) Plausibilidade de deslocamento vs. último evento aprovado.
    last = _last_event(db, user.id)
    now = utcnow()
    if last and not geofencing.is_speed_plausible(
        last.latitude, last.longitude, ensure_aware(last.server_timestamp),
        latitude, longitude, now, settings.MAX_PLAUSIBLE_SPEED_MPS,
    ):
        return _reject(db, user, site, ctype, latitude, longitude, accuracy_m, dist,
                       is_mock_location, is_rooted,
                       "Deslocamento fisicamente impossível desde o último registro", device_info)

    # 4) Liveness + reconhecimento facial.
    selfie_bytes = await selfie.read()
    face = get_liveness_provider().verify(selfie_bytes, cpf=user.cpf, base_embedding=user.face_embedding)
    if face.liveness_score < settings.LIVENESS_THRESHOLD:
        return _reject(db, user, site, ctype, latitude, longitude, accuracy_m, dist,
                       is_mock_location, is_rooted,
                       f"Prova de vida falhou ({face.reason or 'liveness baixo'})", device_info)
    if face.match_score < settings.FACE_MATCH_THRESHOLD:
        return _reject(db, user, site, ctype, latitude, longitude, accuracy_m, dist,
                       is_mock_location, is_rooted, "Rosto não confere com o cadastro", device_info)

    # 5) Aprovado — persiste. NÃO guardamos a selfie (minimização LGPD), só os scores.
    ev = CheckEvent(
        user_id=user.id, site_id=site.id, type=ctype, status=CheckStatus.approved,
        latitude=latitude, longitude=longitude, accuracy_m=accuracy_m, distance_m=dist,
        is_mock_location=False, is_rooted=False,
        liveness_score=face.liveness_score, face_match_score=face.match_score,
        device_info=device_info, client_timestamp=client_timestamp,
    )
    db.add(ev)
    db.flush()

    shift_id = None
    if ctype == CheckType.checkin:
        shift = Shift(user_id=user.id, site_id=site.id, status=ShiftStatus.active, started_at=now)
        db.add(shift)
        db.flush()
        ev.shift_id = shift.id
        shift_id = shift.id
        schedule_next_challenge(db, shift.id, user.id)  # inicia o homem-morto
    else:  # checkout encerra turnos ativos do usuário
        for s in db.scalars(select(Shift).where(Shift.user_id == user.id, Shift.status == ShiftStatus.active)):
            s.status = ShiftStatus.closed
            s.ended_at = now
            ev.shift_id = s.id
            shift_id = s.id

    db.commit()
    db.refresh(ev)
    return CheckinResult(
        status="approved", check_event_id=ev.id, distance_m=dist,
        liveness_score=face.liveness_score, face_match_score=face.match_score, shift_id=shift_id,
    )
