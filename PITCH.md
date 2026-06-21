# Fuel-Stop Route Planner — Pitch

---

## Short version (elevator pitch — ~30 seconds)

> I built a Django REST API that plans the cheapest way to fuel a 500-mile-range
> truck across the US. You give it a start and finish; it returns the route, the
> fuel stops, and the total cost at 10 MPG.
>
> The whole design is built around one constraint from the problem statement: _don't hammer
> the routing API_. So I make exactly **three external calls** — two geocodes
> (run in parallel) and a **single OSRM routing call** — and everything else is
> pure Python on data I already have. Fuel prices load once from the CSV into
> memory; no database, no per-request lookups.
>
> The interesting part is _how_ it chooses stops. Instead of refuelling on a
> rigid timer — "stop every 450 miles" — the planner asks the real question a
> driver asks: **"of every station I can still reach on this tank, which is
> cheapest?"** It refuels there. On real data that means it tops up at the last
> cheap-Kansas station before prices climb, rather than wherever the 450-mile
> mark blindly lands. Same route, lower bill, and it's all one fast pass with
> caching so a repeat request makes zero API calls.

Now lets look at the code in detail.

### The problem, restated as constraints

The brief looks like "draw a route and add gas stops," but it's really an
optimization problem wrapped in a performance budget. Three things drove every
decision:

1. **"Optimal means cost-effective."** The deliverable isn't _a_ set of stops —
   it's the _cheapest_ set.
2. **"Return results quickly."** Latency is a feature, not a nice-to-have.
3. **"One routing call is ideal, two or three acceptable."** External calls are
   the expensive, slow, rate-limited part — so I treat them as a scarce resource
   to be budgeted.

### Strategy: do the expensive work once, then stay in pure Python

I picked free, keyless services so there's nothing to provision: **Nominatim**
for geocoding and **OSRM** for routing. The flow is deliberately front-loaded —
spend the API budget early, then never touch the network again:

```
start, finish
   │
   ├── geocode(start)  ┐  2 Nominatim calls, run in PARALLEL
   ├── geocode(finish) ┘  (ThreadPoolExecutor) — ~halves this step
   │
   └── get_route()  ───── 1 OSRM call: full geometry + distance in one shot
            │
            ▼
   ── everything below is pure Python, zero network ──
   decode polyline → walk it → resolve states → look up prices → plan stops → sum cost
```

**Budget: 3 calls, and 0 on a repeat** thanks to two cache layers (geocodes 24h,
routes 1h). Two design choices keep the non-network work cheap too:

- **Fuel prices load once from the CSV into an in-memory structure**
  (`lru_cache`). 8,151 stations collapse to a cheapest-price-per-state map. No
  database, no migrations, no query at request time. I deliberately _dropped_ a
  DB model I'd sketched earlier — it was dead weight the request path never
  touched.
- **States are resolved by bounding box, not reverse-geocoding.** Calling an API
  for every point on the route would blow the call budget. A point-in-rectangle
  check is instant and, for a truck that sits inside one state for hundreds of
  miles, plenty accurate.

### The function: greedy cheapest-in-window

This is the heart of it, and it's where I made a real engineering choice. The
naive approach — **refuel every 450 miles** — has a subtle flaw: _price never
influences where you stop._ The location is decided by geometry, and you just
pay whatever price happens to be there. That's the opposite of "optimal location
to fuel up."

So `plan_fuel_stops` inverts it. It models the actual decision a driver has:

> From where I am, I can reach any station within my remaining range. **Buy where
> it's cheapest.**

Concretely:

1. **Walk the route once** into a profile of candidate nodes, each tagged with
   cumulative miles, its state, and that state's cheapest price.
2. **Rescale** those haversine-derived mile markers to OSRM's authoritative road
   distance, so the costs sum to the true trip length.
3. **Greedy loop:** from the current stop, look at every node reachable within
   the safe range (`500 − 50mi reserve = 450`), and jump to the **cheapest** one.
   Ties break toward _farther_, so we ride equally-cheap fuel as long as possible
   and minimize stop count.
4. Charge each leg's fuel at the price of the stop it departs from; sum gallons
   and dollars.

**Why this is demonstrably better** — a real run, Kansas → Missouri corridor:

```
#1 @   0mi  KS  $2.84   #2 @ 245mi  KS  $2.84   #3 @ 485mi  MO  $2.90
total: $229.01
```

Stop #2 lands at **245 miles, not 450** — because just past there the route
leaves cheap Kansas for pricier states. The planner refuels at the _last_
cheap-KS point before the climb. A fixed-450 trigger would have sailed past that
window and paid more. I wrote a regression test that encodes exactly this
scenario (a cheap pocket a rigid trigger skips) and asserts the greedy beats the
all-expensive baseline.

### Honesty about the trade-off

The greedy doesn't weigh the _cost of reaching_ a far-but-cheap station — the
fully optimal "look-ahead variable-fill" rule does, at the price of more
complexity and carrying tank state. I chose the greedy deliberately: it captures
the large majority of the savings, stays a single clean pass, and adds zero API
calls. I'd reach for the look-ahead version only if profiling against real
fuel-price spreads showed it paying off. **I'd rather ship the simpler thing
that's 95% there and is easy to reason about than the clever thing that's hard
to verify.**

### What I'd do next

- A thin Leaflet frontend to render the returned GeoJSON + stop markers (the API
  is already shaped for it).
- Swap LocMemCache → Redis so the cache is shared across Gunicorn workers in prod.
- Optional: geocode real station coordinates so stops snap to actual exits rather
  than a state-level price proxy.

### Proof it runs

Django 6.0.6, `manage.py check` clean, **6/6 tests passing**, and a live run
against the full 8,151-station CSV completes in one fast pass.
