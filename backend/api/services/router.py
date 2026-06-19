import polyline
import requests
from django.conf import settings
from django.core.cache import cache

from api.exceptions import RoutingServiceError

METERS_PER_MILE = 1609.344
ROUTE_CACHE_TTL = 60 * 60  # 1 hour


def get_route(origin, destination):
    """The single routing call: one OSRM request returns the whole route.

    Returns distance, duration, and the decoded geometry. Cached for 1h keyed
    on rounded coordinates so identical routes never re-hit OSRM.
    """
    cache_key = (
        f"route:{origin['lat']:.4f},{origin['lon']:.4f}:"
        f"{destination['lat']:.4f},{destination['lon']:.4f}"
    )
    cached = cache.get(cache_key)
    if cached:
        return cached

    coords = f"{origin['lon']},{origin['lat']};{destination['lon']},{destination['lat']}"
    response = requests.get(
        f'{settings.OSRM_BASE_URL}/route/v1/driving/{coords}',
        params={'overview': 'full', 'geometries': 'polyline', 'annotations': 'false'},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get('code') != 'Ok' or not payload.get('routes'):
        raise RoutingServiceError('No driving route found for the requested locations.')

    route = payload['routes'][0]
    value = {
        'distance_miles': route['distance'] / METERS_PER_MILE,
        'duration_seconds': route['duration'],
        'encoded_polyline': route['geometry'],
        'decoded_points': polyline.decode(route['geometry']),
    }
    cache.set(cache_key, value, ROUTE_CACHE_TTL)
    return value
