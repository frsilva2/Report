"""Teste do adaptador Datavalid sem credenciais reais.

Usa httpx.MockTransport para simular:
  - POST /token          -> access_token
  - POST /datavalid/v4/pf-facial -> JWS com face_similaridade

Executa o caminho REAL do código (auth, montagem do request, decode do JWS,
decisão por threshold). Rode: python test_datavalid.py
"""
import base64
import json

import httpx
from jose import jwt

from app.core.config import settings


def _make_jws(similaridade: float) -> str:
    """Cria um JWS compact (assinatura HS256 qualquer; lemos claims sem verificar)."""
    return jwt.encode(
        {"iss": "Datavalid", "sub": "25774435016", "pin": "FC3UAXQXC",
         "face_similaridade": similaridade},
        "chave-de-teste", algorithm="HS256",
    )


def _handler_factory(similaridade: float):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == settings.DATAVALID_TOKEN_PATH:
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600})
        if request.url.path == settings.DATAVALID_FACE_PATH:
            assert request.headers["Authorization"] == "Bearer tok-123"
            body = json.loads(request.content)
            assert body["key"]["cpf"] == "25774435016"
            assert "biometria_face" in body["answer"]  # base64 da selfie
            base64.b64decode(body["answer"]["biometria_face"])  # deve ser base64 válido
            return httpx.Response(200, text=_make_jws(similaridade))
        return httpx.Response(404)
    return handler


def run():
    # Credenciais fake só para o cliente não abortar no _get_token.
    settings.DATAVALID_CONSUMER_KEY = "ck"
    settings.DATAVALID_CONSUMER_SECRET = "cs"

    from app.services.datavalid import DatavalidClient

    # 1) Similaridade alta -> aprova
    client = DatavalidClient(transport=httpx.MockTransport(_handler_factory(0.9999)))
    res = client.validate_face("25774435016", b"x" * 4096)
    assert abs(res.similaridade - 0.9999) < 1e-6, res.similaridade
    assert res.pin == "FC3UAXQXC"
    print(f"OK  match alto: face_similaridade={res.similaridade} pin={res.pin}")

    # 2) Similaridade baixa -> reprova pelo threshold do provider
    from app.services.liveness import FaceResult, SerproDatavalidProvider
    prov = SerproDatavalidProvider()
    prov._client = DatavalidClient(transport=httpx.MockTransport(_handler_factory(0.42)))
    fr: FaceResult = prov.verify(b"x" * 4096, cpf="25774435016")
    assert fr.approved is False and fr.match_score == 0.42, fr
    print(f"OK  match baixo reprovado: score={fr.match_score} reason='{fr.reason}'")

    # 3) Sem CPF -> reprova sem chamar a API
    fr2 = prov.verify(b"x" * 4096, cpf=None)
    assert fr2.approved is False and "CPF" in fr2.reason
    print(f"OK  sem CPF reprovado: reason='{fr2.reason}'")

    print("\nTODOS OS TESTES PASSARAM ✅")


if __name__ == "__main__":
    run()
