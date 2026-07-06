"""Sincronização de check-ins feitos offline.

O app guarda check-ins localmente (criptografados) quando não há rede e os
reenvia aqui em lote. O servidor REVALIDA cada evento (geofence, plausibilidade)
— nunca confia cegamente no que o cliente aprovou offline. Eventos que passam
a revalidação viram 'approved'; os demais ficam 'pending_review' para a central.
"""
import base64

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.models import (
    CheckEvent, CheckStatus, CheckType, Site, User,
)
from app.schemas.schemas import OfflineSyncRequest
from app.services import geofencing
from app.services.liveness import get_liveness_provider

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.post("/offline")
def sync_offline(payload: OfflineSyncRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    results = []
    provider = get_liveness_provider()
    for item in payload.events:
        site = db.get(Site, item.site_id)
        if not site:
            results.append({"status": "rejected", "reason": "posto inexistente"})
            continue

        dist = geofencing.haversine_m(item.latitude, item.longitude, site.latitude, site.longitude)
        status_ = CheckStatus.approved
        reason = None

        if item.signals.is_mock_location or item.signals.is_rooted:
            status_, reason = CheckStatus.rejected, "device comprometido (mock/root)"
        elif dist > site.radius_m:
            status_, reason = CheckStatus.rejected, f"fora do raio ({dist:.0f}m)"
        else:
            # Revalida liveness se a selfie veio no lote; senão marca p/ revisão humana.
            if item.selfie_base64:
                try:
                    face = provider.verify(base64.b64decode(item.selfie_base64),
                                           cpf=user.cpf, base_embedding=user.face_embedding)
                    if (face.liveness_score < settings.LIVENESS_THRESHOLD
                            or face.match_score < settings.FACE_MATCH_THRESHOLD):
                        status_, reason = CheckStatus.rejected, "biometria reprovada"
                except Exception:  # noqa: BLE001
                    status_, reason = CheckStatus.pending_review, "selfie ilegível"
            else:
                status_, reason = CheckStatus.pending_review, "sem selfie para revalidar"

        ev = CheckEvent(
            user_id=user.id, site_id=site.id,
            type=CheckType.checkin if item.type == "checkin" else CheckType.checkout,
            status=status_, rejection_reason=reason,
            latitude=item.latitude, longitude=item.longitude, accuracy_m=item.accuracy_m,
            distance_m=dist, is_mock_location=item.signals.is_mock_location,
            is_rooted=item.signals.is_rooted, device_info=item.signals.device_info,
            liveness_score=item.liveness_score, face_match_score=item.face_match_score,
            synced_from_offline=True, client_timestamp=item.client_timestamp,
        )
        db.add(ev)
        db.flush()
        results.append({"status": status_.value, "check_event_id": ev.id, "reason": reason})

    db.commit()
    return {"synced": len(results), "results": results}
