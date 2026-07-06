"""Telemetria periódica: bateria e status de rede do dispositivo."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import Telemetry, User
from app.schemas.schemas import TelemetryIn

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


@router.post("")
def push_telemetry(data: TelemetryIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = Telemetry(user_id=user.id, **data.model_dump())
    db.add(row)
    db.commit()
    return {"status": "ok"}
