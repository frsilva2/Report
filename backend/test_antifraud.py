"""Testes das camadas anti-fraude que rodam sem servidor.

O cruzamento GPS×IP (#5) é testado aqui com um resolver injetado. Os checks de
GPS gate (#4), janela de turno (#8) e turno concorrente (#9) são validados via
HTTP (ver README/curl) por dependerem do fluxo completo de check-in.

Rode: python test_antifraud.py
"""
from app.core.config import settings
from app.services import geoip


def test_geoip_divergence():
    settings.GEOIP_MAX_DIVERGENCE_KM = 200.0
    gps = (-23.56, -46.65)  # São Paulo

    geoip.set_resolver(lambda ip: (-23.55, -46.63))  # IP perto
    ok, div = geoip.is_ip_gps_consistent("1.2.3.4", *gps)
    assert ok and div < 50, (ok, div)

    geoip.set_resolver(lambda ip: (48.85, 2.35))     # IP em Paris
    ok, div = geoip.is_ip_gps_consistent("1.2.3.4", *gps)
    assert not ok and div > 1000, (ok, div)

    geoip.set_resolver(lambda ip: None)              # IP não resolvível -> não penaliza
    ok, div = geoip.is_ip_gps_consistent("10.0.0.1", *gps)
    assert ok and div is None

    geoip.set_resolver(None)  # restaura
    print("OK  #5 GPS×IP: perto aceita, longe rejeita, nulo não penaliza")


if __name__ == "__main__":
    test_geoip_divergence()
    print("\nTESTES ANTI-FRAUDE PASSARAM ✅")
