"""Liveness ativa por desafio de movimento — validação SERVER-SIDE.

Fluxo:
  1. GET/POST challenge -> servidor sorteia uma sequência aleatória de ações
     (ex.: ["blink", "turn_left"]) e devolve um `nonce` de uso único + prazo.
  2. O cliente (webapp com MediaPipe) guia o usuário e mede os landmarks,
     registrando os EXTREMOS de cada métrica durante a execução.
  3. No check-in o cliente envia o `nonce` + as métricas medidas. O servidor
     confere que cada ação pedida foi de fato realizada (métrica cruzou o
     limiar), dentro do prazo, e que o nonce é válido e ainda não foi usado.

Por que validar no servidor: se confiássemos num booleano "fiz sim" do cliente,
a liveness seria trivialmente burlável. As métricas cruas (EAR, yaw, sorriso)
são difíceis de forjar de forma consistente com a sequência aleatória pedida.
"""
import random
import secrets
from dataclasses import dataclass

from app.core.config import settings

VALID_ACTIONS = {"blink", "turn_left", "turn_right", "smile"}


def action_pool() -> list[str]:
    return [a.strip() for a in settings.LIVENESS_ACTIONS.split(",") if a.strip() in VALID_ACTIONS]


def new_actions() -> list[str]:
    pool = action_pool()
    n = min(settings.LIVENESS_ACTIONS_PER_CHALLENGE, len(pool))
    return random.sample(pool, n)


def new_nonce() -> str:
    return secrets.token_urlsafe(24)


@dataclass
class EvidenceCheck:
    ok: bool
    reason: str | None = None


def validate_evidence(actions: list[str], evidence: dict) -> EvidenceCheck:
    """`evidence` traz os extremos medidos pelo cliente durante o desafio, ex.:
        {"max_blink": 0.8, "min_yaw": -25.0, "max_yaw": 30.0, "max_smile": 0.7}
    (blink/smile = blendshapes MediaPipe 0..1; yaw = graus dos landmarks)
    Cada ação exigida precisa ter sua métrica cruzando o limiar configurado.
    """
    def num(key: str, default: float) -> float:
        try:
            return float(evidence.get(key, default))
        except (TypeError, ValueError):
            return default

    max_blink = num("max_blink", 0.0)
    min_yaw = num("min_yaw", 0.0)
    max_yaw = num("max_yaw", 0.0)
    max_smile = num("max_smile", 0.0)

    for action in actions:
        if action == "blink":
            if max_blink < settings.LIVENESS_BLINK_MIN:
                return EvidenceCheck(False, "não detectamos a piscada")
        elif action == "turn_left":
            if min_yaw > -settings.LIVENESS_TURN_YAW_DEG:
                return EvidenceCheck(False, "não detectamos virar à esquerda")
        elif action == "turn_right":
            if max_yaw < settings.LIVENESS_TURN_YAW_DEG:
                return EvidenceCheck(False, "não detectamos virar à direita")
        elif action == "smile":
            if max_smile < settings.LIVENESS_SMILE_MIN:
                return EvidenceCheck(False, "não detectamos o sorriso")
        else:
            return EvidenceCheck(False, f"ação desconhecida: {action}")
    return EvidenceCheck(True)
