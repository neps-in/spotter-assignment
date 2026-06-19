# Discussion Log — Fuel-Stop Route Planner Review

This document captures the full working conversation reviewing the codebase against the
problem statement and plan, and the decision around improving fuel-stop optimization.

---

## 1. Greeting & setup note

**User:** hi

**Assistant:** Introduced itself as Claude Code working in `/home/ubuntu/spotter-assi`.

Raised an honest caveat about the global `CLAUDE.md` "Model Switcher Agent" spec: it asks
for model-load banners, live token/cost meters, and per-step savings reports. Those can't be
done reliably — within a session it runs as a single model and doesn't switch models mid-task,
and it has no access to real-time token counts or billing, so any cost/savings numbers printed
would be fabricated. Declined to show made-up dashboards.

Noted the directory was not yet a git repo and that a Django toolchain was available.

---

## 2. Request: review codebase vs problem statement and plan

**User:** read `@problem-statement.md` and review the codebase if it matches or solves the
problem; also read `@plan.md` — is that the right plan?

### Problem statement (summary)

- Build an API taking start and finish locations, both within the USA.
- Return a map of the route plus the optimal (cost-effective, based on fuel prices) place(s)
  to fuel up along the route.
- Vehicle max range: 500 miles → multiple fuel-ups may be needed.
- Return total money spent on fuel, assuming 10 miles per gallon.
- Use the attached CSV for fuel prices.
- Find a free routing/map API.
- Requirements: latest stable Django; fast responses; minimize calls to the
  map/routing API (1 ideal, 2–3 acceptable).

### plan.md (summary)

A detailed plan: Django 5.x + DRF, OSRM public demo for routing, Nominatim for geocoding,
Leaflet/GeoJSON for map rendering, fuel prices loaded once from CSV, caching to avoid repeat
OSRM calls. Architecture targets **1 OSRM call + 2 Nominatim calls = 3 external calls max**,
cached after first use. Includes phases for setup, fuel data, services (geocoder, router,
geo_utils, fuel_planner), API view/serializer, performance, error handling, testing, and
deployment.

### Codebase exploration

Actual layout found:

```
backend/
  config/ (settings.py, urls.py, wsgi.py, asgi.py)
  api/
    models.py            # FuelStation (per-station rows)
    serializers.py       # RouteRequestSerializer
    views.py             # RoutePlannerView (POST /api/route/)
    urls.py
    exceptions.py        # LocationNotFound / OutsideUSA / RoutingService
    tests.py
    migrations/0001_initial.py
    management/commands/load_fuel_prices.py
    services/
      geocoder.py        # Nominatim wrapper + 24h cache + USA bbox check
      router.py          # OSRM wrapper + 1h cache, polyline decode
      geo_utils.py       # haversine, point_to_state, interpolate, downsample
      fuel_planner.py    # core fuel-stop algorithm
      fuel_prices.py     # CSV loader via lru_cache, cheapest-per-state
      states.py          # STATE_BBOXES + derived STATE_CENTROIDS
frontend/                # empty
fuel-prices-for-be-assessment.csv   # 8151 station rows
```

CSV header: `OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID, Retail Price`
— matches the field names used in `fuel_prices.py` and `load_fuel_prices.py`.

### Assessment — does it solve the problem?

**Yes, substantially.** Requirement mapping:

| Requirement | Status | Where |
|---|---|---|
| API: start + finish in USA | Done | `RoutePlannerView` + serializer, USA bbox check in `geocoder.py` |
| Route + map | Done | OSRM call → `route_geojson` LineString (client renders) |
| Optimal cost-effective fuel stops | Partial | `cheapest_station_by_state()` picks cheapest per state, not route-optimal |
| Max range 500mi, multiple fuel-ups | Done | `FUEL_STOP_TRIGGER_MILES=450` loop in `fuel_planner.py` |
| Total fuel cost @ 10 MPG | Done | `plan_fuel_stops`, Decimal math |
| Uses provided CSV | Done | `fuel_prices.py` reads it directly; columns match |
| Latest stable Django | Done | settings reference Django 6.0.6 |
| Fast / minimal external calls | Done | 2 Nominatim (parallel) + 1 OSRM = 3 calls, all cached |

**Insights raised:**

- **Two CSV-loading paths coexist.** `fuel_prices.py` reads the CSV directly via `lru_cache`
  (used at request time), while `models.FuelStation` + the `load_fuel_prices` command load it
  into SQLite. The runtime path never queries the DB — so the model/migration/command are
  effectively dead code for the request flow. Fine for speed, but redundant.
- The geocode `ThreadPoolExecutor` runs before the OSRM call, so the two Nominatim lookups are
  genuinely parallel — a real latency win matching the plan's Phase 5.3.

### Real correctness concerns

1. **"Optimal" is weaker than the problem asks.** The code refuels at a fixed 450-mile cadence
   and, at each forced stop, takes the cheapest station in whatever state the interpolated point
   lands in. It does not look ahead to choose where fuel is cheapest within range, and never
   anchors stops to actual station coordinates near the route — it uses a state-level price.
2. **`miles_from_last_stop` is mislabeled.** It's the distance of the upcoming segment being
   fueled for, not miles since the previous stop.
3. **State bboxes overlap and are coarse.** `point_to_state` breaks ties by nearest centroid;
   near borders this can pick the wrong state and thus the wrong price.
4. **`frontend/` is empty.** The API returns GeoJSON (a valid "client renders" interpretation),
   but there is no actual map UI. If a visual map was expected, it's missing.

### Is plan.md the right plan?

**Mostly yes — solid and appropriate, and the code clearly follows it.** It is slightly out of
sync with what got built:

- Plan proposed model `StateFuelPrice` (state → single price). Code uses `FuelStation`
  (per-station rows) and computes cheapest-per-state — a better fit for the real per-truckstop CSV.
- Plan's Phase 2.3 loads prices into a dict via `apps.py ready()`. Code uses `lru_cache` in
  `fuel_prices.py` — functionally equivalent, arguably cleaner.
- Plan's file-structure diagram is rough/garbled; the actual layout (`backend/api/...`) differs.

The plan's one genuine conceptual weakness, inherited by the code: it equates "optimal fuel
stop" with "cheapest price in the state at a fixed-distance trigger point," rather than
"cheapest reachable station within range."

**Options offered:** (1) run the test suite; (2) tighten optimization to cheapest reachable
station within the 500-mi window; (3) reconcile the dead code; (4) build the missing map frontend.

---

## 3. Why the window approach beats the fixed trigger

**User:** refuel by choosing the cheapest reachable station within the 500-mi window rather
than a fixed 450-mile trigger — give the reason why this is a better choice.

### The core problem with the fixed 450-mile trigger

`plan_fuel_stops` walks to the 450-mile mark, interpolates the route point there, finds the
state there, and pays that state's cheapest price. **Price never influences where the stop is
placed.** The location is decided purely by geometry (distance + where a state border falls),
and price is read off afterward.

But the problem statement asks for the *"optimal location to fuel up ... cost effective."* So the
assignment is asking you to **choose the location to minimize cost** — and the fixed trigger does
the opposite: it fixes the location first and lets cost fall out as an accident.

**Insights:**

- This is the known **"gas station problem"**: given a max tank range and prices along a route,
  minimize fuel spend. The fixed-trigger heuristic is the one approach that provably ignores the
  price signal in its decision variable (where to stop), so it can't be optimal except by luck.
- The 450 number is a 50-mile safety buffer under the 500 range. That buffer is a *constraint*
  (don't run dry), but the current code mistakes it for the *decision* (stop exactly here).

### Why the window approach is better

1. **It optimizes the variable the problem asks you to optimize.** From the current position you
   can stop at any station within ~500 miles; the window searches that reachable set and buys
   where it's cheapest — the definition of a cost-effective location.

2. **It decouples price from an arbitrary geometric coincidence.** Concrete example:

   ```
   mile 410  ->  cheap state, $3.00/gal   (reachable)
   mile 450  ->  just crossed border, $4.50/gal   <- fixed trigger fires HERE
   mile 480  ->  still expensive state, $4.40/gal  (reachable)
   ```

   - Fixed-450: pays $4.50/gal → ~45 gal refill → ~$202.
   - Window (0–500mi): picks the $3.00 station at mile 410 → ~$135.

   ~$67 saved on a single stop, compounding over every stop on a multi-day route. The fixed
   trigger got unlucky because the 450 mark landed 40 miles inside an expensive state.

3. **It produces real stops, not state-level abstractions.** The window naturally pairs with
   picking an actual station near the route (real lat/lon, real price), instead of "cheapest
   price anywhere in the state" — which might be hundreds of miles off the path.

4. **It can reduce unnecessary stops.** A rigid 450 cadence can force a stop right before a much
   cheaper station still in range. The window lets you push on when worthwhile or top up early
   when fuel is cheap — better stop count and placement.

5. **It respects the safety constraint without being enslaved to it.** 500 miles becomes the hard
   reachability bound; 450 stays available as a conservative cap. The window honors the constraint
   while optimizing inside it.

### Honest caveat

"Cheapest reachable station in the window" is itself still a **greedy heuristic**, not provably
optimal. The fully optimal gas-station rule adds look-ahead: *if a cheaper station is reachable,
buy only enough to reach it; if not, fill the tank and drive to the cheapest station within range.*
That variable-fill rule beats both. So there's an implementation choice:

- **Greedy "cheapest-in-window"** — simple, big improvement over fixed-trigger, ~optimal in practice.
- **Look-ahead variable-fill** — closer to true optimum, more code, needs station price data
  indexed along the route.

It also costs more: you need stations spatially near the route within range (a route-corridor
filter over the ~8k-row CSV), not just a per-state minimum.

**Recommendation:** implement the **greedy cheapest-in-window** variant — it captures ~all the
savings while keeping the one-pass, no-extra-API-call design intact.

---

## Open next steps

- Implement the chosen optimization variant (greedy cheapest-in-window recommended).
- Optionally: run the test suite, reconcile the dead DB code path, fix the
  `miles_from_last_stop` label, and build the map frontend.
