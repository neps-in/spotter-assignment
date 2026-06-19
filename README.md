# Fuel-Stop Route Planner API

A Django REST API that, given a start and finish in the USA, returns the driving
route, the **cost-optimal** fuel stops for a 500-mile-range vehicle, and the
total fuel cost at 10 MPG. Built for speed and a tight external-call budget.

---

## Quick start

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate          # sessions/admin only — no app models
python manage.py runserver
```

### Request

```bash
curl -X POST http://127.0.0.1:8000/api/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Wichita, KS", "finish": "St. Louis, MO"}'
```

### Response (abridged)

```json
{
  "total_distance_miles": 439.2,
  "estimated_duration_hours": 6.7,
  "total_gallons": 43.9,
  "total_fuel_cost": 126.3,
  "fuel_stops": [
    {"stop_number": 1, "distance_from_start_miles": 0.0, "state": "KS",
     "price_per_gallon": 2.84, "gallons_purchased": 24.5, "miles_covered": 245.0,
     "segment_cost": 69.65, "station": {"name": "...", "city": "...", "state": "KS"}}
  ],
  "route_geojson": {"type": "LineString", "coordinates": [[-97.33, 37.69], "..."]}
}
```

---

## Design in one page

**The brief is an optimization problem on a performance budget.** Three
constraints drove every decision: *optimal = cheapest*, *respond fast*, and *make
as few routing calls as possible*.

**Front-load the network, then stay in pure Python.** Free, keyless services —
**Nominatim** (geocoding) and **OSRM** (routing) — keep setup to zero. Per
request:

```
geocode(start) ┐  2 Nominatim calls in PARALLEL (ThreadPoolExecutor)
geocode(finish)┘
get_route()     1 OSRM call — full geometry + distance in one shot
   └── decode polyline → resolve states → look up prices → plan stops → sum cost   (no network)
```

**Total: 3 external calls, 0 on a repeat** (geocodes cached 24h, routes 1h). Two
choices keep the rest cheap: fuel prices load **once from the CSV into memory**
(`lru_cache`, no DB), and route points map to states via **bounding boxes**, not
per-point reverse-geocoding.

**The core function — greedy cheapest-in-window.** A fixed "stop every 450 miles"
trigger has a flaw: price never influences *where* you stop. So `plan_fuel_stops`
inverts it — at each stop it scans every station reachable within the safe range
(`500 − 50mi reserve`) and jumps to the **cheapest**, breaking ties toward
*farther* to minimize stops. Fuel for each leg is charged at its departure price.

A real Kansas → Missouri run shows why it matters:

```
#1 @ 0mi KS $2.84   #2 @ 245mi KS $2.84   #3 @ 485mi MO $2.90   → $229.01
```

Stop #2 lands at **245mi, not 450** — it refuels at the last cheap-Kansas point
before prices climb, which a rigid trigger would sail past. A regression test
encodes exactly this and asserts the greedy beats the all-expensive baseline.

**Known trade-off:** the greedy doesn't weigh the *cost of reaching* a far cheap
station (the look-ahead variable-fill rule would, with more complexity and tank
state). Chosen deliberately — it captures most of the savings in one clean pass
with zero extra calls.

---

## Project layout

```
backend/api/
├── views.py          RoutePlannerView — POST /api/route/
├── serializers.py    request validation
├── services/
│   ├── geocoder.py   Nominatim + cache
│   ├── router.py     OSRM (the single routing call) + cache
│   ├── fuel_prices.py CSV → cheapest-per-state, in memory
│   ├── geo_utils.py  haversine, point→state, downsample
│   ├── states.py     48-state bounding boxes
│   └── fuel_planner.py  greedy cheapest-in-window
└── tests.py          6 tests
```

## Tests

```bash
python manage.py test        # 6/6 passing — Django 6.0.6
```

Covers haversine accuracy, state resolution, uniform-price cost invariance, the
greedy-beats-fixed-trigger scenario, and API response shape.

## Configuration (`config/settings.py`)

| Setting | Default | Meaning |
|---|---|---|
| `VEHICLE_MAX_RANGE_MILES` | 500 | Tank range |
| `FUEL_SAFETY_BUFFER_MILES` | 50 | Reserve; planning window = range − buffer |
| `VEHICLE_MPG` | 10 | Fuel economy |
| `OSRM_BASE_URL` / `NOMINATIM_BASE_URL` | public demos | Swap for self-hosted in prod |

**Production notes:** swap LocMemCache → Redis (shared across workers); a thin
Leaflet frontend can render the returned GeoJSON + stop markers.
