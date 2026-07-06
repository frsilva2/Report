"""Reconhecimento facial + prova de vida (liveness).

Regra de ouro: NÃO construa liveness do zero. Use um provedor gerenciado.
Aqui definimos uma interface e um stub para o PoC; a implementação real
(AWS Rekognition Face Liveness) fica documentada para plugar sem trocar chamadas.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import settings


@dataclass
class FaceResult:
    liveness_score: float   # [0..1] confiança de prova de vida
    match_score: float      # [0..1] similaridade com a foto base
    approved: bool
    reason: str | None = None


class LivenessProvider(ABC):
    @abstractmethod
    def verify(self, selfie_bytes: bytes, base_embedding: str | None) -> FaceResult:
        ...


class StubLivenessProvider(LivenessProvider):
    """PoC: aprova se recebeu uma imagem plausível. NÃO usar em produção."""

    def verify(self, selfie_bytes: bytes, base_embedding: str | None) -> FaceResult:
        got_image = bool(selfie_bytes) and len(selfie_bytes) > 1024
        score = 0.97 if got_image else 0.0
        return FaceResult(
            liveness_score=score,
            match_score=score if base_embedding else 0.0,
            approved=got_image and (base_embedding is not None),
            reason=None if got_image else "selfie ausente ou inválida",
        )


class AwsRekognitionLivenessProvider(LivenessProvider):
    """Produção. Fluxo real:
      1. App inicia uma sessão: rekognition.create_face_liveness_session()
      2. SDK Amplify (web/mobile) conduz o desafio de liveness no cliente.
      3. Servidor lê o resultado: get_face_liveness_session_results() -> Confidence.
      4. Se aprovado, compare_faces(base, referenceImage) -> Similarity.
    Requer boto3 e credenciais AWS (região sa-east-1). Ver docs/ARCHITECTURE.md.
    """

    def verify(self, selfie_bytes: bytes, base_embedding: str | None) -> FaceResult:  # pragma: no cover
        raise NotImplementedError(
            "Configure boto3 + credenciais AWS e implemente a chamada ao Rekognition. "
            "Mantida como stub para não exigir credenciais no PoC."
        )


def get_liveness_provider() -> LivenessProvider:
    if settings.LIVENESS_PROVIDER == "aws_rekognition":
        return AwsRekognitionLivenessProvider()
    return StubLivenessProvider()
