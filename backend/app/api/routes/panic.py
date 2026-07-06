"""Botão de pânico — alerta de emergência com localização em tempo real."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import PanicAlert, User
from app.schemas.schemas import PanicRequest
from app.services.webhook import fire_webhook

router = APIRouter(prefix="/api/panic", tags=["panic"])


@router.post("")
async def trigger_panic(data: PanicRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    alert = PanicAlert(user_id=user.id, latitude=data.latitude, longitude=data.longitude)
    db.add(alert)
    db.commit()
    db.refresh(alert)
    # Dispara imediatamente para a central (webhook). Em produção: também push/SMS.
    await fire_webhook("panic", {
        "alert_id": alert.id, "user_id": user.id, "user_name": user.name,
        "latitude": data.latitude, "longitude": data.longitude,
        "created_at": alert.created_at.isoformat(),
    })
    return {"status": "alerted", "alert_id": alert.id}
