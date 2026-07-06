"""Escala de turnos. A central agenda; usado para exigir check-in na janela (#8)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_operator
from app.db.session import get_db
from app.models.models import Shift, ShiftStatus, User
from app.schemas.schemas import ShiftCreate, ShiftOut

router = APIRouter(prefix="/api/shifts", tags=["shifts"])


@router.post("", response_model=ShiftOut)
def schedule_shift(data: ShiftCreate, db: Session = Depends(get_db), _: User = Depends(require_operator)):
    shift = Shift(
        user_id=data.user_id, site_id=data.site_id, status=ShiftStatus.scheduled,
        scheduled_start=data.scheduled_start, scheduled_end=data.scheduled_end,
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


@router.get("/mine", response_model=list[ShiftOut])
def my_shifts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(
        select(Shift).where(Shift.user_id == user.id).order_by(Shift.id.desc()).limit(20)
    ).all()
