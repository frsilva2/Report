"""Cliente Serpro Datavalid — validação facial contra a base oficial do governo.

Fluxo (confirmado na documentação da API Serpro):
  1. OAuth2 client_credentials:
       POST {base}/token
       Header: Authorization: Basic base64(consumer_key:consumer_secret)
       Body:   grant_type=client_credentials
       -> access_token (Bearer), validade ~1h.
  2. Validação facial:
       POST {base}/datavalid/v4/pf-facial
       Header: Authorization: Bearer <token>
       Body:   {"key": {"cpf": "..."}, "answer": {"biometria_face": "<base64>"}}
       -> resposta é um JWS; decodificado traz `face_similaridade` (0..1),
          `sub` (CPF) e `pin`.

Observações importantes:
- O endpoint `pf-facial` já contempla o fluxo de **prova de vida** (via componente
  Bioconnect/app-provadevida na captura). O match é feito contra a base do governo.
- Datavalid é **probabilístico**: cabe ao contratante decidir o corte (threshold).
- Custo por consulta: use Datavalid no **onboarding** e em check-ins de risco —
  não em todo ponto diário (ver docs/ARCHITECTURE.md).
"""
import base64
import logging
import time
from dataclasses import dataclass, field

import httpx
from jose import jwt

from app.core.config import settings

log = logging.getLogger("wfm.datavalid")


class DatavalidError(Exception):
    pass


@dataclass
class DatavalidFaceResult:
    similaridade: float
    pin: str | None = None
    claims: dict = field(default_factory=dict)


class DatavalidClient:
    """Cliente com cache de token. `transport` permite injeção em testes."""

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._token: str | None = None
        self._token_exp: float = 0.0
        self._http = httpx.Client(
            base_url=settings.DATAVALID_BASE_URL,
            timeout=settings.DATAVALID_TIMEOUT_SECONDS,
            transport=transport,
        )

    # ---- OAuth2 ----
    def _get_token(self) -> str:
        # Reusa o token enquanto faltar >60s para expirar.
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        if not settings.DATAVALID_CONSUMER_KEY or not settings.DATAVALID_CONSUMER_SECRET:
            raise DatavalidError("Credenciais Datavalid ausentes (DATAVALID_CONSUMER_KEY/SECRET).")

        basic = base64.b64encode(
            f"{settings.DATAVALID_CONSUMER_KEY}:{settings.DATAVALID_CONSUMER_SECRET}".encode()
        ).decode()
        resp = self._http.post(
            settings.DATAVALID_TOKEN_PATH,
            headers={"Authorization": f"Basic {basic}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
        )
        if resp.status_code != 200:
            raise DatavalidError(f"Falha ao obter token ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + float(data.get("expires_in", 3600))
        return self._token

    # ---- Validação facial ----
    def validate_face(self, cpf: str, image_bytes: bytes) -> DatavalidFaceResult:
        token = self._get_token()
        b64 = base64.b64encode(image_bytes).decode()
        body = {"key": {"cpf": cpf}, "answer": {"biometria_face": b64}}
        resp = self._http.post(
            settings.DATAVALID_FACE_PATH,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
        )
        if resp.status_code != 200:
            raise DatavalidError(f"Validação facial falhou ({resp.status_code}): {resp.text[:200]}")

        claims = _decode_jws_claims(resp.text)
        sim = float(claims.get("face_similaridade", 0.0) or 0.0)
        return DatavalidFaceResult(similaridade=sim, pin=claims.get("pin"), claims=claims)


def _decode_jws_claims(raw: str) -> dict:
    """A resposta é um JWS (compact). Lemos os claims.

    PoC: usamos claims não-verificados (o transporte já é TLS direto ao gateway
    Serpro). Em produção, VERIFIQUE a assinatura com a chave pública do Serpro
    antes de confiar no resultado.
    """
    token = raw.strip().strip('"')
    try:
        return jwt.get_unverified_claims(token)
    except Exception as exc:  # noqa: BLE001
        raise DatavalidError(f"Resposta JWS ilegível: {exc}") from exc
