"""Disparo de webhook para a central (homem-morto perdido, pânico)."""
import logging

import httpx

from app.core.config import settings

log = logging.getLogger("wfm.webhook")


async def fire_webhook(event: str, payload: dict) -> bool:
    """Envia um evento para a central. Retorna True se aceito (2xx)."""
    if not settings.CENTRAL_WEBHOOK_URL:
        log.warning("CENTRAL_WEBHOOK_URL não configurada — evento '%s' apenas logado: %s", event, payload)
        return False
    body = {"event": event, "data": payload}
    try:
        async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
            resp = await client.post(settings.CENTRAL_WEBHOOK_URL, json=body)
            resp.raise_for_status()
            return True
    except httpx.HTTPError as exc:
        log.error("Falha ao disparar webhook '%s': %s", event, exc)
        return False
