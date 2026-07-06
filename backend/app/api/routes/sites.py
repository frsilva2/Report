"""Cadastro de postos (geofences). Restrito à central/admin."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_operator
from app.db.session import get_db
from app.models.models import Site, User
from app.schemas.schemas import SiteCreate, SiteOut

router = APIRouter(prefix="/api/sites", tags=["sites"])


@router.post("", response_model=SiteOut)
def create_site(data: SiteCreate, db: Session = Depends(get_db), _: User = Depends(require_operator)):
    site = Site(**data.model_dump())
    db.add(site)
    db.commit()
    db.refresh(site)
    return site


@router.get("", response_model=list[SiteOut])
def list_sites(db: Session = Depends(get_db)):
    return db.scalars(select(Site).where(Site.is_active.is_(True))).all()
