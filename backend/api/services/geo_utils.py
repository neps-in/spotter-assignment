import math

from api.services.states import STATE_BBOXES, STATE_CENTROIDS

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(point_a, point_b):
    """Great-circle distance in miles between two (lat, lon) points."""
    lat1, lon1 = point_a
    lat2, lon2 = point_b
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def point_to_state(lat, lon):
    """Resolve a (lat, lon) to a 2-letter state code via bounding boxes.

    Unique box match wins; overlapping boxes (border zones) and points that
    miss every box fall back to the nearest state centroid.
    """
    matches = [
        code for code, (min_lat, max_lat, min_lon, max_lon) in STATE_BBOXES.items()
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon
    ]
    if len(matches) == 1:
        return matches[0]
    pool = matches or STATE_CENTROIDS
    return min(pool, key=lambda code: haversine_miles((lat, lon), STATE_CENTROIDS[code]))


def is_contiguous_usa(lat, lon):
    """Rough bounding box for the lower-48 — used to reject inputs early."""
    return 24.0 <= lat <= 50.0 and -125.0 <= lon <= -66.0


def downsample_points(points, max_points=700):
    """Thin a dense polyline for the map response while keeping the endpoints."""
    if len(points) <= max_points:
        return points
    stride = math.ceil(len(points) / max_points)
    sampled = points[::stride]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled
