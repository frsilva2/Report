"""Rotas do sensor de homem-morto: consultar desafio pendente e confirmar (ack)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import ChallengeStatus, DeadManChallenge, User
from app.models.models import ensure_aware, utcnow
from app.schemas.schemas import ChallengeOut, DeadManAck

router = APIRouter(prefix="/api/deadman", tags=["deadman"])


@router.get("/pending", response_model=ChallengeOut | None)
def pending(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """O app faz polling/recebe push e busca o desafio ativo a confirmar."""
    return db.scalars(
        select(DeadManChallenge)
        .where(DeadManChallenge.user_id == user.id, DeadManChallenge.status == ChallengeStatus.pending)
        .order_by(DeadManChallenge.scheduled_at.asc())
        .limit(1)
    ).first()


@router.post("/ack")
def acknowledge(data: DeadManAck, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ch = db.get(DeadManChallenge, data.challenge_id)
    if not ch or ch.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Desafio não encontrado")
    if ch.status != ChallengeStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Desafio já {ch.status.value}")
    now = utcnow()
    if now > ensure_aware(ch.deadline_at):
        # Chegou tarde — o sweep já vai/pode ter marcado como perdido.
        raise HTTPException(status.HTTP_408_REQUEST_TIMEOUT, "Janela de resposta expirada")
    ch.status = ChallengeStatus.acknowledged
    ch.responded_at = now
    db.commit()
    return {"status": "acknowledged", "responded_at": now.isoformat()}
