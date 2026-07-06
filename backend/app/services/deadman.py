"""Sensor de Homem-Morto (dead man switch).

Princípio: o cliente pode falhar (bateria, background morto pelo SO, sem rede).
Portanto quem decide se o desafio foi perdido é o SERVIDOR. O app só precisa
enviar o `acknowledge` a tempo; o agendador aqui detecta a ausência e dispara
o webhook para a central.

O intervalo tem jitter aleatório (30 ± 5 min por padrão) para não virar hábito
automático, como pedido.
"""
import logging
import random
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import (
    ChallengeStatus, DeadManChallenge, Shift, ShiftStatus,
)
from app.models.models import utcnow
from app.services.webhook import fire_webhook

log = logging.getLogger("wfm.deadman")
scheduler = AsyncIOScheduler()


def _next_interval() -> timedelta:
    jitter = settings.DEADMAN_JITTER_MINUTES
    delta_min = settings.DEADMAN_INTERVAL_MINUTES + random.uniform(-jitter, jitter)
    return timedelta(minutes=max(1.0, delta_min))


def schedule_next_challenge(db, shift_id: int, user_id: int) -> DeadManChallenge:
    """Cria o próximo desafio pendente para um turno ativo."""
    scheduled_at = utcnow() + _next_interval()
    deadline_at = scheduled_at + timedelta(seconds=settings.DEADMAN_RESPONSE_WINDOW_SECONDS)
    challenge = DeadManChallenge(
        shift_id=shift_id, user_id=user_id,
        scheduled_at=scheduled_at, deadline_at=deadline_at,
        status=ChallengeStatus.pending,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    log.info("Homem-morto agendado: shift=%s às %s (deadline %s)", shift_id, scheduled_at, deadline_at)
    return challenge


async def _sweep() -> None:
    """Roda periodicamente: marca perdidos e reagenda para turnos ativos."""
    db = SessionLocal()
    try:
        now = utcnow()
        # 1) Desafios pendentes que estouraram o deadline -> perdido + webhook.
        overdue = db.scalars(
            select(DeadManChallenge).where(
                DeadManChallenge.status == ChallengeStatus.pending,
                DeadManChallenge.deadline_at < now,
            )
        ).all()
        for ch in overdue:
            ch.status = ChallengeStatus.missed
            ch.webhook_fired = True
            db.commit()
            await fire_webhook("deadman_missed", {
                "challenge_id": ch.id, "shift_id": ch.shift_id, "user_id": ch.user_id,
                "scheduled_at": ch.scheduled_at.isoformat(), "deadline_at": ch.deadline_at.isoformat(),
            })
            log.warning("HOMEM-MORTO PERDIDO: shift=%s user=%s", ch.shift_id, ch.user_id)

        # 2) Garante um próximo desafio para cada turno ativo sem pendência futura.
        active = db.scalars(select(Shift).where(Shift.status == ShiftStatus.active)).all()
        for shift in active:
            has_open = db.scalar(
                select(DeadManChallenge.id).where(
                    DeadManChallenge.shift_id == shift.id,
                    DeadManChallenge.status == ChallengeStatus.pending,
                )
            )
            if not has_open:
                schedule_next_challenge(db, shift.id, shift.user_id)
    except Exception:  # noqa: BLE001 — sweep nunca deve derrubar o scheduler
        log.exception("Erro no sweep do homem-morto")
    finally:
        db.close()


def start_scheduler() -> None:
    if not settings.DEADMAN_SCHEDULER_ENABLED:
        log.info("Scheduler do homem-morto desabilitado por config.")
        return
    # `_sweep` é corrotina: o AsyncIOScheduler a executa no próprio event loop
    # (registrar uma função sync a jogaria num threadpool sem loop -> quebra o await).
    # Sweep a cada 30s. Em produção, prefira Celery beat + Redis para escala/HA.
    scheduler.add_job(_sweep, "interval", seconds=30, id="deadman_sweep", replace_existing=True)
    scheduler.start()
    log.info("Scheduler do homem-morto iniciado.")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
