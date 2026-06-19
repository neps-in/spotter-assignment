# Fuel-Stop Route Planner API — Detailed Implementation Plan

## Project Overview

A Django REST API that accepts a start and finish location (both within the USA), returns:
- A map of the optimal driving route
- Optimal (cost-effective) fuel stops along the route (vehicle max range: 500 miles)
- Total fuel cost (vehicle: 10 MPG)

---

## Tech Stack Decisions

| Concern | Choice | Reason |
|---|---|---|
| Framework | Django 5.x + Django REST Framework | Requirement |
| Routing API | OSRM public demo server (`router.project-osrm.org`) | Free, no key needed, 1 call returns full route geometry + distance |
| Geocoding | Nominatim (`nominatim.openstreetmap.org`) | Free, no key, converts city/address → lat/lon |
| Map rendering | Leaflet.js (embedded HTML response) or static GeoJSON | Client renders; server stays stateless |
| Fuel price data | Loaded once from uploaded CSV into DB / in-memory dict | Zero external calls at runtime |
| Caching | Django's cache framework (LocMemCache dev / Redis prod) | Avoid repeat OSRM calls for same routes |
| DB | SQLite (dev) / PostgreSQL (prod) | Stores fuel price table |

---

## Architecture: One OSRM Call Strategy

```
Client Request (start, finish)
        │
        ▼
[Step 1] Geocode start & finish → (lat, lon) pairs       ← 2 Nominatim calls (fast, cacheable)
        │
        ▼
[Step 2] Call OSRM /route/v1/driving/{coords}            ← THE SINGLE ROUTING CALL
         Returns: total distance, full polyline (encoded geometry)
        │
        ▼
[Step 3] Decode polyline → list of (lat, lon) points
         Sample points every ~400 miles along route       ← Pure Python, no API call
        │
        ▼
[Step 4] For each sampled "fuel zone", find nearest      ← Pure Python lookup against
         gas station state from route → cheapest price     in-memory fuel price dict
        │
        ▼
[Step 5] Calculate total fuel cost                        ← Pure arithmetic
        │
        ▼
[Step 6] Return JSON response with:
         - route GeoJSON polyline
         - fuel stop list (location, price/gal, amount to fill)
         - total cost
```

**Result: 1 OSRM call + 2 Nominatim calls = 3 external API calls max, most cached after first use.**

---

## Detailed Step-by-Step Tasks

---

### PHASE 1 — Project Setup

#### Task 1.1 — Create Django project
```
django-admin startproject fuel_route_project
cd fuel_route_project
python manage.py startapp route_planner
```

#### Task 1.2 — Install dependencies
```
pip install django djangorestframework requests polyline
```
- `polyline` — decode OSRM's encoded geometry into lat/lon list
- `requests` — HTTP calls to OSRM and Nominatim

#### Task 1.3 — settings.py configuration
- Add `rest_framework` and `route_planner` to `INSTALLED_APPS`
- Configure `CACHES` with `LocMemCache` (swap to Redis in prod)
- Add constants:
  ```python
  VEHICLE_MAX_RANGE_MILES = 500
  VEHICLE_MPG = 10
  FUEL_STOP_TRIGGER_MILES = 450  # stop before hitting empty; 50mi buffer
  OSRM_BASE_URL = "http://router.project-osrm.org"
  NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"
  ```

---

### PHASE 2 — Fuel Price Data

#### Task 2.1 — Define model `StateFuelPrice`
```python
# route_planner/models.py
class StateFuelPrice(models.Model):
    state_code = models.CharField(max_length=2, unique=True)  # e.g. "TX"
    state_name = models.CharField(max_length=100)
    price_per_gallon = models.DecimalField(max_digits=5, decimal_places=3)
    updated_at = models.DateTimeField(auto_now=True)
```

#### Task 2.2 — Write management command `load_fuel_prices`
```
route_planner/management/commands/load_fuel_prices.py
```
- Reads the uploaded CSV (columns: state_code, state_name, price_per_gallon)
- Upserts into `StateFuelPrice` via `update_or_create`
- Run once: `python manage.py load_fuel_prices --file fuel_prices.csv`

#### Task 2.3 — In-memory price cache on startup
```python
# route_planner/apps.py → ready() hook
# Loads all StateFuelPrice rows into a module-level dict:
# FUEL_PRICES = {"TX": 3.12, "CA": 4.87, ...}
```
This means zero DB queries at request time for price lookups.

---

### PHASE 3 — Core Services (Business Logic)

#### Task 3.1 — Geocoding service `services/geocoder.py`
```python
def geocode(location_string: str) -> tuple[float, float]:
    """
    Calls Nominatim once per unique location string.
    Returns (latitude, longitude).
    Raises ValueError if location not found or outside USA.
    Uses Django cache with key = f"geocode:{location_string.lower()}"
    TTL: 24 hours
    """
```
- Validate result is within approximate USA bounding box:
  `lat: 24–50, lon: -125 to -66`
- Cache key prevents repeat calls for same city

#### Task 3.2 — OSRM routing service `services/router.py`
```python
def get_route(origin: tuple, destination: tuple) -> dict:
    """
    Makes ONE call to OSRM /route/v1/driving/{lon1},{lat1};{lon2},{lat2}
    ?overview=full&geometries=polyline&annotations=false
    
    Returns:
    {
        "distance_miles": float,
        "duration_seconds": int,
        "encoded_polyline": str,
        "decoded_points": [(lat, lon), ...]  # full route geometry
    }
    Cache key: f"route:{lat1:.4f},{lon1:.4f}:{lat2:.4f},{lon2:.4f}"
    TTL: 1 hour
    """
```
- Decodes OSRM's encoded polyline using the `polyline` library
- Converts meters → miles

#### Task 3.3 — Route point state resolver `services/geo_utils.py`

This is a key piece: given a (lat, lon) point on the route, determine which US state it's in — **without an API call**.

```python
# Use a lightweight approach: preloaded state bounding boxes (rectangles)
# Stored as a Python dict of approximate bounding boxes per state
# For a road trip planner, bbox approximation is accurate enough
# because the vehicle will be clearly inside one state for hundreds of miles

STATE_BBOXES = {
    "TX": {"min_lat": 25.8, "max_lat": 36.5, "min_lon": -106.6, "max_lon": -93.5},
    "CA": {"min_lat": 32.5, "max_lat": 42.0, "min_lon": -124.4, "max_lon": -114.1},
    # ... all 48 contiguous states
}

def point_to_state(lat: float, lon: float) -> str:
    """
    Returns 2-letter state code for a given lat/lon.
    Uses bounding box lookup — no API call.
    Falls back to nearest centroid if ambiguous (border zones).
    """
```

> **Why not reverse geocoding?** Calling Nominatim for every fuel stop point would be
> 1–4 additional API calls. The bbox approach is instant, zero-dependency, and accurate
> enough for inter-state fuel price differences.

#### Task 3.4 — Fuel stop planner `services/fuel_planner.py`
```python
def plan_fuel_stops(
    decoded_points: list[tuple],
    total_distance_miles: float,
    fuel_prices: dict,  # {"TX": 3.12, ...}
    max_range: int = 500,
    trigger_miles: int = 450,
    mpg: int = 10
) -> dict:
    """
    Algorithm:
    1. Walk the decoded_points list, accumulating distance between consecutive points
       using the Haversine formula.
    2. When accumulated distance >= trigger_miles (450), mark a fuel stop.
    3. For the fuel stop point, determine the state using point_to_state().
    4. Look up price_per_gallon for that state from fuel_prices dict.
    5. Calculate gallons needed = trigger_miles / mpg (to refill tank).
    6. Record: {lat, lon, state, price_per_gallon, gallons, stop_cost}.
    7. Reset accumulated distance counter.
    8. Repeat until destination.
    
    Returns:
    {
        "fuel_stops": [...],
        "total_gallons": float,
        "total_fuel_cost": float,
        "total_distance_miles": float
    }
    """
```

**Haversine helper** (pure Python, no library):
```python
def haversine_miles(p1: tuple, p2: tuple) -> float:
    # Returns great-circle distance in miles between two (lat, lon) points
```

---

### PHASE 4 — API View & Serializer

#### Task 4.1 — Request serializer `serializers.py`
```python
class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200)   # e.g. "Austin, TX"
    finish = serializers.CharField(max_length=200)  # e.g. "Seattle, WA"
```

#### Task 4.2 — Response structure
```json
{
  "start": "Austin, TX",
  "finish": "Seattle, WA",
  "total_distance_miles": 2142.3,
  "estimated_duration_hours": 31.5,
  "fuel_stops": [
    {
      "stop_number": 1,
      "lat": 35.46,
      "lon": -97.51,
      "state": "OK",
      "price_per_gallon": 3.08,
      "gallons_to_fill": 45.0,
      "stop_cost": 138.60,
      "miles_from_last_stop": 450
    }
  ],
  "total_gallons": 214.2,
  "total_fuel_cost": 682.50,
  "route_geojson": {
    "type": "LineString",
    "coordinates": [[-97.74, 30.26], [-97.60, 31.10], ...]
  }
}
```

#### Task 4.3 — API View `views.py`
```python
class RoutePlannerView(APIView):
    """
    POST /api/route/
    Body: {"start": "Austin, TX", "finish": "Seattle, WA"}
    
    Flow:
    1. Validate with RouteRequestSerializer
    2. geocode(start) → origin coords
    3. geocode(finish) → destination coords
    4. get_route(origin, destination) → route data (cached)
    5. plan_fuel_stops(route_data, FUEL_PRICES) → stops + cost
    6. Build and return response
    """
```

#### Task 4.4 — URL routing `urls.py`
```python
urlpatterns = [
    path("api/route/", RoutePlannerView.as_view(), name="route-planner"),
]
```

---

### PHASE 5 — Performance Optimizations

#### Task 5.1 — Cache layers
| Cache Key | TTL | What it stores |
|---|---|---|
| `geocode:{location}` | 24h | (lat, lon) for a city string |
| `route:{origin}:{dest}` | 1h | Full OSRM response + decoded points |
| `fuel_prices_loaded` | App startup | In-memory dict loaded once |

With caching, **repeat requests for the same route = zero external API calls**.

#### Task 5.2 — Polyline point downsampling
OSRM returns thousands of points for long routes. For fuel stop calculation we only need enough resolution to track state crossings — sample every Nth point (e.g., every 10th point) to reduce Haversine iterations. For GeoJSON response, keep every ~50th point (still visually smooth on a map).

#### Task 5.3 — Async-ready design
Each service function is pure and stateless → easy to wrap with `asyncio` or `concurrent.futures` for parallel geocoding of start + finish:
```python
with ThreadPoolExecutor() as ex:
    origin_future = ex.submit(geocode, start)
    dest_future = ex.submit(geocode, finish)
    origin = origin_future.result()
    destination = dest_future.result()
```
This makes the 2 Nominatim calls happen in parallel → saves ~200–400ms.

---

### PHASE 6 — Error Handling

#### Task 6.1 — Custom exceptions
```python
class LocationNotInUSAError(APIException): ...
class LocationNotFoundError(APIException): ...
class RoutingServiceError(APIException): ...
```

#### Task 6.2 — Graceful fallbacks
- If a state isn't found in fuel_prices dict → use national average price
- If OSRM returns no route → return 400 with clear message
- Nominatim rate limit (1 req/sec) → add `time.sleep(1)` between calls if not cached

---

### PHASE 7 — Testing

#### Task 7.1 — Unit tests
- `test_haversine`: Known city pairs, verify distance ±5%
- `test_point_to_state`: Spot-check 10 known coordinates
- `test_fuel_stop_planner`: Mock route of 1200 miles, verify 2 stops generated
- `test_fuel_cost_calculation`: 100 miles at 10 MPG @ $3.00/gal = $30.00

#### Task 7.2 — Integration test
- `test_route_api_end_to_end`: POST to `/api/route/` with real cities, mock OSRM response, assert response structure

#### Task 7.3 — Manual test cases
```
Austin TX → Seattle WA     (~2142 miles, ~4–5 stops)
New York NY → Los Angeles CA (~2800 miles, ~6 stops)
Boston MA → Washington DC   (~440 miles, 0–1 stops)
```

---

### PHASE 8 — Deployment Considerations

#### Task 8.1 — Environment variables
```
OSRM_BASE_URL=http://router.project-osrm.org
NOMINATIM_BASE_URL=https://nominatim.openstreetmap.org
DJANGO_CACHE_BACKEND=django.core.cache.backends.redis.RedisCache
REDIS_URL=redis://localhost:6379/1
```

#### Task 8.2 — Production swap-outs
- Replace LocMemCache → Redis (shared across Gunicorn workers)
- Add rate-limiter middleware for the `/api/route/` endpoint
- Consider switching to `openrouteservice.org` free API if OSRM demo gets slow (2,500 req/day free)

---

## File Structure

```
fuel_route_project/
├── manage.py
├── config/
│   ├── settings.py
│   └── urls.py
|
|---| api/
|
└ apps/route_planner/
    ├── models.py               # StateFuelPrice
    ├── serializers.py          # RouteRequestSerializer
    ├── views.py                # RoutePlannerView
    ├── urls.py
    ├── apps.py                 # ready() → load FUEL_PRICES dict
    ├── management/
    │   └── commands/
    │       └── load_fuel_prices.py
    ├── services/
    │   ├── __init__.py
    │   ├── geocoder.py         # Nominatim wrapper + cache
    │   ├── router.py           # OSRM wrapper + cache
    │   ├── geo_utils.py        # point_to_state, haversine
    │   └── fuel_planner.py     # core algorithm
    ├── data/
    │   └── state_bboxes.py     # static dict, all 48 states
    └── tests/
        ├── test_geo_utils.py
        ├── test_fuel_planner.py
        └── test_api.py
```

---

## Summary: API Call Count Per Request

| Call | Count | Cached after first? |
|---|---|---|
| Nominatim geocode (start) | 1 | ✅ Yes, 24h |
| Nominatim geocode (finish) | 1 | ✅ Yes, 24h |
| OSRM route | 1 | ✅ Yes, 1h |
| State lookup (fuel stops) | 0 (local bbox dict) | N/A |
| Fuel price lookup | 0 (in-memory dict) | N/A |
| **Total** | **3 max, 0 after cache** | |

---

Fuel price ./fuel-prices-for-be-assessment.csv
