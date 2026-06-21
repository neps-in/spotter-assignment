import requests
from django.conf import settings
from django.core.cache import cache

from api.exceptions import LocationNotFoundError, LocationOutsideUSAError
from api.services.geo_utils import is_contiguous_usa

GEOCODE_CACHE_TTL = 60 * 60 * 24  # 24 hours


def geocode(location):
    """Resolve a free-text US location to coordinates via Nominatim.

    Cached for 24h per normalized query, so repeat lookups make no call.
    Raises if the location is unknown or outside the contiguous USA.
    """
    # Collapse runs of whitespace so "New  York" and "New York" share a cache key.
    normalized = ' '.join(location.strip().split())
    cache_key = f'geocode:{normalized.casefold()}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    response = requests.get(
        f'{settings.NOMINATIM_BASE_URL}/search',
        params={'q': normalized, 'format': 'jsonv2', 'limit': 1, 'countrycodes': 'us'},
        headers={'User-Agent': 'spotter-fuel-route-api/1.0'},
        timeout=8,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        raise LocationNotFoundError(f'Location not found: {location}')

    lat = float(results[0]['lat'])
    lon = float(results[0]['lon'])
    # Bounding-box check keeps Alaska/Hawaii out even though countrycodes=us would include them.
    if not is_contiguous_usa(lat, lon):
        raise LocationOutsideUSAError(f'Location must be in the contiguous USA: {location}')

    value = {'lat': lat, 'lon': lon, 'display_name': results[0].get('display_name', normalized)}
    cache.set(cache_key, value, GEOCODE_CACHE_TTL)
    return value
