"""Validação geográfica server-side.

O cliente NUNCA é confiável para decidir se está dentro do geofence — ele apenas
envia coordenadas. Aqui recalculamos a distância e checamos plausibilidade.

Em produção com PostGIS, substitua `haversine_m` por uma query:
    SELECT ST_DWithin(site.geom, ST_MakePoint(:lon,:lat)::geography, site.radius_m)
"""
import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em metros entre dois pontos (lat/lon em graus)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass
class GeoCheck:
    inside: bool
    distance_m: float


def check_geofence(lat: float, lon: float, site_lat: float, site_lon: float, radius_m: float) -> GeoCheck:
    d = haversine_m(lat, lon, site_lat, site_lon)
    return GeoCheck(inside=d <= radius_m, distance_m=d)


def is_speed_plausible(prev_lat, prev_lon, prev_time, lat, lon, now, max_speed_mps: float) -> bool:
    """Detecta 'teletransporte' (fake GPS / troca de coordenada) entre dois eventos.

    Retorna False se a velocidade implícita for fisicamente impossível.
    """
    if prev_lat is None or prev_time is None:
        return True
    dt = (now - prev_time).total_seconds()
    if dt <= 0:
        return False
    dist = haversine_m(prev_lat, prev_lon, lat, lon)
    return (dist / dt) <= max_speed_mps
