"""Reconhecimento facial + prova de vida (liveness).

Interface única (`LivenessProvider`) com três implementações plugáveis por config:
  - stub            -> PoC, sem dependência externa
  - serpro_datavalid-> valida o rosto contra a base OFICIAL do governo (fluxo
                       pf-facial já contempla prova de vida na captura)
  - aws_rekognition -> liveness gerenciado (documentado)

Trocar de provedor é mudar `LIVENESS_PROVIDER` no .env — nenhuma rota muda.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import settings


@dataclass
class FaceResult:
    liveness_score: float   # [0..1] confiança de prova de vida
    match_score: float      # [0..1] similaridade com a referência (base oficial ou cadastro)
    approved: bool
    reason: str | None = None


class LivenessProvider(ABC):
    @abstractmethod
    def verify(self, selfie_bytes: bytes, *, cpf: str | None = None,
               base_embedding: str | None = None) -> FaceResult:
        ...


class StubLivenessProvider(LivenessProvider):
    """PoC: aprova se recebeu uma imagem plausível. NÃO usar em produção."""

    def verify(self, selfie_bytes, *, cpf=None, base_embedding=None) -> FaceResult:
        got_image = bool(selfie_bytes) and len(selfie_bytes) > 1024
        score = 0.97 if got_image else 0.0
        return FaceResult(
            liveness_score=score,
            match_score=score if base_embedding else 0.0,
            approved=got_image and (base_embedding is not None),
            reason=None if got_image else "selfie ausente ou inválida",
        )


class SerproDatavalidProvider(LivenessProvider):
    """Valida o rosto capturado contra a base oficial do governo (Senatran) via CPF.

    O endpoint `v4/pf-facial` conduz a prova de vida na captura (Bioconnect) e
    retorna a similaridade contra a base. Aqui o `match_score` vem do governo;
    o `liveness_score` reflete a conclusão do fluxo de prova de vida do Serpro.
    """

    def __init__(self):
        # Import tardio: só exige httpx/jose quando o provider é usado.
        from app.services.datavalid import DatavalidClient
        self._client = DatavalidClient()

    def verify(self, selfie_bytes, *, cpf=None, base_embedding=None) -> FaceResult:
        from app.services.datavalid import DatavalidError
        if not cpf:
            return FaceResult(0.0, 0.0, False, "CPF ausente para validação Datavalid")
        try:
            res = self._client.validate_face(cpf, selfie_bytes)
        except DatavalidError as exc:
            return FaceResult(0.0, 0.0, False, f"Datavalid: {exc}")
        approved = res.similaridade >= settings.FACE_MATCH_THRESHOLD
        return FaceResult(
            # pf-facial só retorna com sucesso quando a prova de vida é concluída;
            # em produção, leia também o campo de resultado de liveness da resposta.
            liveness_score=1.0 if approved else 0.0,
            match_score=res.similaridade,
            approved=approved,
            reason=None if approved else "rosto não confere com a base oficial",
        )


class AwsRekognitionLivenessProvider(LivenessProvider):
    """Produção alternativa. Fluxo: create_face_liveness_session -> SDK Amplify
    conduz o desafio no cliente -> get_face_liveness_session_results (Confidence)
    -> compare_faces (Similarity). Requer boto3 + credenciais AWS.
    ATENÇÃO: Face Liveness NÃO está em sa-east-1 (dado processado fora do BR)."""

    def verify(self, selfie_bytes, *, cpf=None, base_embedding=None) -> FaceResult:  # pragma: no cover
        raise NotImplementedError(
            "Configure boto3 + credenciais AWS e implemente a chamada ao Rekognition."
        )


def get_liveness_provider() -> LivenessProvider:
    if settings.LIVENESS_PROVIDER == "serpro_datavalid":
        return SerproDatavalidProvider()
    if settings.LIVENESS_PROVIDER == "aws_rekognition":
        return AwsRekognitionLivenessProvider()
    return StubLivenessProvider()
