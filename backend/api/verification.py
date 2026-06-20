"""Live verification suite for the /api/route/ endpoint.

Unlike ``tests.py`` (which mocks the network for deterministic unit tests),
this suite exercises the *real* endpoint end-to-end -- serializer validation,
the view, live Nominatim geocoding and OSRM routing, and the fuel planner --
using **random US city pairs chosen fresh on every run**.

It is driven two ways:
  * the ``GET /api/verify/`` endpoint (so the frontend can execute it), and
  * the ``verify_api`` management command (CLI).

Each test returns a uniform result dict so the caller can render it:
    {"id", "name", "passed", "details", "metrics"}
"""
import json
import random
import uuid
from datetime import datetime, timezone

from django.conf import settings
from django.test import Client

# A curated pool of well-known cities spread across the contiguous USA. Random
# pairs are drawn from this list so every run plans a different real route while
# staying inside the area OSRM/Nominatim resolve reliably.
US_CITIES = [
    'Seattle, WA', 'Portland, OR', 'San Francisco, CA', 'Los Angeles, CA',
    'Las Vegas, NV', 'Phoenix, AZ', 'Denver, CO', 'Salt Lake City, UT',
    'Albuquerque, NM', 'Dallas, TX', 'Houston, TX', 'San Antonio, TX',
    'Oklahoma City, OK', 'Kansas City, MO', 'St. Louis, MO', 'Wichita, KS',
    'Minneapolis, MN', 'Chicago, IL', 'Indianapolis, IN', 'Nashville, TN',
    'Memphis, TN', 'Atlanta, GA', 'Charlotte, NC', 'Columbus, OH',
    'Detroit, MI', 'Pittsburgh, PA', 'Washington, DC', 'New York, NY',
    'Boston, MA', 'Philadelphia, PA', 'Orlando, FL', 'Miami, FL',
]

# Contiguous-USA bounding box (lon, lat) used to sanity-check route geometry.
USA_BBOX = {'min_lon': -125.0, 'max_lon': -66.0, 'min_lat': 24.0, 'max_lat': 50.0}

REQUIRED_KEYS = (
    'total_distance_miles', 'estimated_duration_hours', 'total_gallons',
    'total_fuel_cost', 'fuel_stops', 'route_geojson',
)


def _safe_range_miles():
    return settings.VEHICLE_MAX_RANGE_MILES - settings.FUEL_SAFETY_BUFFER_MILES


def random_city_pair():
    """Two distinct random cities -> (start, finish)."""
    return tuple(random.sample(US_CITIES, 2))


def _post_route(start, finish):
    """Drive the real POST /api/route/ through Django's test client.

    Returns (status_code, parsed_body). Goes through the full stack: serializer,
    view, live geocode + route, and the fuel planner.
    """
    # SERVER_NAME pins the request host to an entry in ALLOWED_HOSTS; the test
    # client otherwise defaults to "testserver", which is only auto-allowed
    # under the test runner, not when driven from a view/command.
    client = Client()
    response = client.post(
        '/api/route/',
        data=json.dumps({'start': start, 'finish': finish}),
        content_type='application/json',
        SERVER_NAME='localhost',
    )
    try:
        body = response.json()
    except ValueError:
        body = {'detail': response.content.decode('utf-8', 'replace')[:200]}
    return response.status_code, body


def _result(test_id, name, passed, details, metrics=None):
    return {
        'id': test_id,
        'name': name,
        'passed': bool(passed),
        'details': details,
        'metrics': metrics or {},
    }


# --------------------------------------------------------------------------- #
# The 5 test cases. Each takes the (start, finish, status, body) under test so
# tests 1-4 share a single live route call (one external round-trip per run,
# in the spirit of the assignment's tight call budget) while still operating on
# a randomly chosen route. Test 5 uses its own random city.
# --------------------------------------------------------------------------- #

def test_response_contract(start, finish, status, body):
    """1. A valid random route returns 200 with every contract field present."""
    if status != 200:
        return _result(1, 'Response contract', False,
                       f'Expected HTTP 200, got {status}: {body.get("detail", body)}')
    missing = [k for k in REQUIRED_KEYS if k not in body]
    if missing:
        return _result(1, 'Response contract', False,
                       f'Response missing required keys: {missing}')
    if not isinstance(body['fuel_stops'], list) or not body['fuel_stops']:
        return _result(1, 'Response contract', False,
                       'fuel_stops must be a non-empty list')
    return _result(
        1, 'Response contract', True,
        f'200 OK with all {len(REQUIRED_KEYS)} contract fields for '
        f'{start} -> {finish}.',
        {'distance_miles': body['total_distance_miles'],
         'fuel_stops': len(body['fuel_stops'])},
    )


def test_range_constraint(start, finish, status, body):
    """2. No driving leg exceeds the safe range (range - buffer = 450 mi),
    and the stops together cover the whole trip (vehicle never strands)."""
    if status != 200:
        return _result(2, 'Range constraint (<=450 mi/leg)', False,
                       f'No route to check (HTTP {status}).')
    safe = _safe_range_miles()
    legs = [s['miles_covered'] for s in body['fuel_stops']]
    longest = max(legs) if legs else 0.0
    covered = round(sum(legs), 2)
    total = body['total_distance_miles']

    # 1 mile of slack absorbs rounding at the ~5-mile route sampling resolution.
    over = [round(m, 2) for m in legs if m > safe + 1.0]
    coverage_ok = abs(covered - total) <= max(2.0, total * 0.01)

    passed = not over and coverage_ok
    if over:
        details = f'Leg(s) exceed the {safe:.0f}-mi safe range: {over}'
    elif not coverage_ok:
        details = f'Legs cover {covered} mi but trip is {total} mi (gap too large)'
    else:
        details = (f'All {len(legs)} legs <= {safe:.0f} mi (longest {longest:.1f}); '
                   f'legs cover {covered}/{total} mi.')
    return _result(2, 'Range constraint (<=450 mi/leg)', passed, details,
                   {'longest_leg_miles': round(longest, 1), 'safe_range': safe,
                    'covered_miles': covered, 'total_miles': total})


def test_cost_math(start, finish, status, body):
    """3. The cost arithmetic is internally consistent:
    gallons == distance / MPG, and sum(segment_cost) == total_fuel_cost."""
    if status != 200:
        return _result(3, 'Cost math consistency', False,
                       f'No route to check (HTTP {status}).')
    mpg = settings.VEHICLE_MPG
    total_distance = body['total_distance_miles']
    total_gallons = body['total_gallons']
    total_cost = body['total_fuel_cost']

    expected_gallons = total_distance / mpg
    gallons_ok = abs(total_gallons - expected_gallons) <= max(0.5, expected_gallons * 0.01)

    stops = body['fuel_stops']
    summed_cost = round(sum(s['segment_cost'] for s in stops), 2)
    # Each stop's cost is rounded to the cent before summing, so the sum may
    # differ from the separately-rounded total by up to half a cent per stop.
    cost_sum_ok = abs(summed_cost - total_cost) <= 0.01 * len(stops) + 0.01

    # Per-stop: segment_cost ~= gallons_purchased * price_per_gallon. price is
    # *displayed* rounded to the cent while the real charge uses full CSV
    # precision, so allow half a cent of slack per gallon plus a small base.
    per_stop_ok = all(
        abs(s['segment_cost'] - s['gallons_purchased'] * s['price_per_gallon'])
        <= 0.005 * s['gallons_purchased'] + 0.05
        for s in stops
    )

    passed = gallons_ok and cost_sum_ok and per_stop_ok
    problems = []
    if not gallons_ok:
        problems.append(f'gallons {total_gallons} != distance/MPG {expected_gallons:.2f}')
    if not cost_sum_ok:
        problems.append(f'sum(segment_cost) {summed_cost} != total {total_cost}')
    if not per_stop_ok:
        problems.append('a stop\'s segment_cost != gallons * price')
    details = ('; '.join(problems) if problems
               else f'gallons={total_gallons} (=distance/{mpg}); '
                    f'segment costs sum to total ${total_cost}.')
    return _result(3, 'Cost math consistency', passed, details,
                   {'total_gallons': total_gallons, 'total_fuel_cost': total_cost,
                    'expected_gallons': round(expected_gallons, 2)})


def test_geojson_in_usa(start, finish, status, body):
    """4. route_geojson is a LineString of >=2 points, all inside the USA box."""
    if status != 200:
        return _result(4, 'GeoJSON validity (USA LineString)', False,
                       f'No route to check (HTTP {status}).')
    geo = body['route_geojson']
    coords = geo.get('coordinates', []) if isinstance(geo, dict) else []
    if geo.get('type') != 'LineString' or len(coords) < 2:
        return _result(4, 'GeoJSON validity (USA LineString)', False,
                       'route_geojson is not a LineString with >=2 points')
    outside = [
        [lon, lat] for lon, lat in coords
        if not (USA_BBOX['min_lon'] <= lon <= USA_BBOX['max_lon']
                and USA_BBOX['min_lat'] <= lat <= USA_BBOX['max_lat'])
    ]
    passed = not outside
    details = (f'{len(coords)} coordinates, all within the contiguous-USA box.'
               if passed else
               f'{len(outside)} coordinate(s) fall outside the USA box, e.g. {outside[0]}')
    return _result(4, 'GeoJSON validity (USA LineString)', passed, details,
                   {'points': len(coords)})


def test_identical_rejected(city):
    """5. Posting identical start and finish is rejected with HTTP 400."""
    status, body = _post_route(city, city.lower())
    passed = status == 400
    details = (f'Identical "{city}" correctly rejected with HTTP 400.'
               if passed else
               f'Expected HTTP 400 for identical locations, got {status}.')
    return _result(5, 'Identical locations rejected', passed, details,
                   {'status': status})


def run_suite():
    """Run all 5 testcases with fresh random cities and return a report dict."""
    start, finish = random_city_pair()
    status, body = _post_route(start, finish)

    tests = [
        test_response_contract(start, finish, status, body),
        test_range_constraint(start, finish, status, body),
        test_cost_math(start, finish, status, body),
        test_geojson_in_usa(start, finish, status, body),
        test_identical_rejected(random.choice(US_CITIES)),
    ]
    passed = sum(1 for t in tests if t['passed'])
    return {
        'run_id': uuid.uuid4().hex[:8],
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'route_under_test': {'start': start, 'finish': finish},
        'summary': {'total': len(tests), 'passed': passed,
                    'failed': len(tests) - passed,
                    'all_passed': passed == len(tests)},
        'tests': tests,
    }
