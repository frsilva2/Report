"""#5 Cruzamento GPS × IP — detecta divergência grosseira (VPN, desktop, spoof).

O IP geolocaliza de forma grosseira (nível cidade; em operadora móvel pode até
errar por NAT), então isto é um **sinal de flag**, não prova. Use para rejeitar
divergências GRANDES (ex.: GPS em SP, IP na Europa).

Requer geoip2 + base GeoLite2-City (MaxMind, gratuita) apontada por GEOIP_DB_PATH.
Se não configurado, o cruzamento é ignorado silenciosamente.

`_resolver` é um ponto de injeção para testes (recebe IP, devolve (lat, lon) ou None).
"""
import logging
from typing import Callable

from app.core.config import settings
from app.services.geofencing import haversine_m

log = logging.getLogger("wfm.geoip")

# Resolver injetável: ip -> (lat, lon) | None. Default usa geoip2 se configurado.
_resolver: Callable[[str], tuple[float, float] | None] | None = None


def _default_resolver(ip: str) -> tuple[float, float] | None:
    if not settings.GEOIP_ENABLED or not settings.GEOIP_DB_PATH:
        return None
    try:
        import geoip2.database  # type: ignore
    except ImportError:
        log.warning("geoip2 não instalado — cruzamento GPS×IP desativado.")
        return None
    try:
        with geoip2.database.Reader(settings.GEOIP_DB_PATH) as reader:
            r = reader.city(ip)
            if r.location.latitude is None:
                return None
            return (r.location.latitude, r.location.longitude)
    except Exception as exc:  # noqa: BLE001 — IP privado/não encontrado etc.
        log.debug("geoip falhou para %s: %s", ip, exc)
        return None


def set_resolver(fn: Callable[[str], tuple[float, float] | None] | None) -> None:
    """Injeta um resolver (usado em testes)."""
    global _resolver
    _resolver = fn


def divergence_km(ip: str, gps_lat: float, gps_lon: float) -> float | None:
    """Distância (km) entre o IP e o GPS. None se não foi possível resolver."""
    resolver = _resolver or _default_resolver
    loc = resolver(ip)
    if loc is None:
        return None
    return haversine_m(gps_lat, gps_lon, loc[0], loc[1]) / 1000.0


def is_ip_gps_consistent(ip: str, gps_lat: float, gps_lon: float) -> tuple[bool, float | None]:
    """Retorna (consistente, divergência_km). Consistente se não deu p/ resolver
    (não penaliza o usuário por falta de dado) ou se abaixo do limiar."""
    div = divergence_km(ip, gps_lat, gps_lon)
    if div is None:
        return (True, None)
    return (div <= settings.GEOIP_MAX_DIVERGENCE_KM, div)
