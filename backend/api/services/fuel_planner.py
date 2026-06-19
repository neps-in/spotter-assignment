from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings

from api.services.fuel_prices import national_average_price, station_for_state
from api.services.geo_utils import haversine_miles, point_to_state

# Emit a candidate fuel node at least this often (miles) while walking the
# route, plus whenever the state changes. Fine enough that the reachable
# window is resolved accurately; coarse enough that the candidate list stays
# small (a few hundred nodes even on a cross-country route).
SAMPLE_INTERVAL_MILES = 5.0


def money(value):
    return float(Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def quantity(value):
    return float(Decimal(value).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP))


def _price_for_state(state):
    """Cheapest known price for a state, falling back to the national average."""
    station = station_for_state(state)
    if station:
        return station['retail_price'], station
    return national_average_price(), None


def build_route_profile(decoded_points):
    """Walk the route once and produce candidate fuel-buying nodes.

    Each node is a point on the route annotated with cumulative miles from the
    start, its US state, the cheapest station in that state, and that price.
    Nodes are emitted at most every ``SAMPLE_INTERVAL_MILES``, whenever the
    state changes, and always at the final point.

    Returns ``(profile, profile_distance_miles)``.
    """
    if not decoded_points:
        raise ValueError('Route has no geometry points.')

    def make_node(mile, point, state):
        price, station = _price_for_state(state)
        return {
            'mile': mile,
            'lat': point[0],
            'lon': point[1],
            'state': state,
            'price': price,
            'station': station,
        }

    origin = decoded_points[0]
    profile = [make_node(0.0, origin, point_to_state(origin[0], origin[1]))]

    cumulative = 0.0
    last_emitted = 0.0
    previous = origin
    for point in decoded_points[1:]:
        cumulative += haversine_miles(previous, point)
        previous = point
        state = point_to_state(point[0], point[1])
        if cumulative - last_emitted >= SAMPLE_INTERVAL_MILES or state != profile[-1]['state']:
            profile.append(make_node(cumulative, point, state))
            last_emitted = cumulative

    if profile[-1]['mile'] < cumulative:
        profile.append(make_node(cumulative, previous, point_to_state(previous[0], previous[1])))

    return profile, cumulative


def plan_fuel_stops(decoded_points, total_distance_miles):
    """Greedy cheapest-in-window fuel planner.

    Starting at the origin, each refuel hop targets the *cheapest* station
    reachable within the safely-drivable range (vehicle max range minus a
    safety reserve). Ties are broken by distance so we go as far as possible
    on equally cheap fuel, minimising the number of stops. Fuel for each leg
    is purchased at the stop it departs from, at that stop's price.

    This makes price — not a fixed mileage trigger — decide where to stop, so
    the planner exploits a cheaper state that lies anywhere inside the window
    instead of refuelling at whatever point a rigid 450-mile mark happens to
    land on.
    """
    max_range = float(settings.VEHICLE_MAX_RANGE_MILES)
    safety_buffer = float(getattr(settings, 'FUEL_SAFETY_BUFFER_MILES', 0))
    usable_range = max(max_range - safety_buffer, 1.0)
    mpg = Decimal(str(settings.VEHICLE_MPG))

    profile, profile_distance = build_route_profile(decoded_points)

    # OSRM's road distance is authoritative; rescale the haversine-derived
    # node markers so the legs sum to the real trip length.
    if profile_distance > 0:
        scale = total_distance_miles / profile_distance
        for node in profile:
            node['mile'] *= scale
    total_distance = float(total_distance_miles)

    stops = []
    total_cost = Decimal('0')
    total_gallons = Decimal('0')
    index = 0
    stop_number = 1

    while True:
        node = profile[index]
        remaining = total_distance - node['mile']

        if remaining <= usable_range:
            leg_miles = max(remaining, 0.0)
            next_index = None
        else:
            window_end = node['mile'] + usable_range
            reachable = [j for j in range(index + 1, len(profile)) if profile[j]['mile'] <= window_end]
            if reachable:
                next_index = min(reachable, key=lambda j: (profile[j]['price'], -profile[j]['mile']))
            else:
                next_index = index + 1
            leg_miles = max(profile[next_index]['mile'] - node['mile'], 0.0)

        leg = Decimal(str(leg_miles))
        gallons = leg / mpg
        cost = gallons * node['price']
        total_gallons += gallons
        total_cost += cost

        stop = {
            'stop_number': stop_number,
            'distance_from_start_miles': round(node['mile'], 2),
            'lat': round(node['lat'], 6),
            'lon': round(node['lon'], 6),
            'state': node['state'],
            'price_per_gallon': money(node['price']),
            'gallons_purchased': quantity(gallons),
            'miles_covered': round(leg_miles, 2),
            'segment_cost': money(cost),
        }
        if node['station']:
            stop['station'] = {
                key: node['station'][key]
                for key in ('opis_id', 'name', 'address', 'city', 'state')
            }
        else:
            stop['station'] = None
            stop['price_source'] = 'national_average'
        stops.append(stop)
        stop_number += 1

        if next_index is None:
            break
        index = next_index

    return {
        'fuel_stops': stops,
        'total_gallons': quantity(total_gallons),
        'total_fuel_cost': money(total_cost),
    }
