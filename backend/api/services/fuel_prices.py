"""In-memory fuel price data loaded once from the assignment CSV.

Loading the CSV into module-level caches means zero database queries and zero
external calls when planning fuel stops at request time.
"""

import csv
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from django.conf import settings


@lru_cache(maxsize=1)
def load_stations():
    """Parse the assessment CSV once and cache every valid station row in memory.

    Rows with a missing or malformed Retail Price are silently skipped so a
    single bad entry doesn't abort the entire load.
    """
    stations = []
    with open(settings.FUEL_PRICE_CSV, newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                price = Decimal(row['Retail Price'])
            except (InvalidOperation, KeyError, TypeError):
                continue
            stations.append({
                'opis_id': int(row['OPIS Truckstop ID']),
                'name': row['Truckstop Name'].strip(),
                'address': row['Address'].strip(),
                'city': row['City'].strip(),
                'state': row['State'].strip().upper(),
                'rack_id': int(row['Rack ID']),
                'retail_price': price,
            })
    return stations


@lru_cache(maxsize=1)
def cheapest_station_by_state():
    """Return a mapping of state code -> cheapest station dict from the CSV data."""
    cheapest = {}
    for station in load_stations():
        state = station['state']
        if state not in cheapest or station['retail_price'] < cheapest[state]['retail_price']:
            cheapest[state] = station
    return cheapest


@lru_cache(maxsize=1)
def national_average_price():
    """Mean retail price across all CSV stations; used when a state has no entry.

    Falls back to $3.50 when the CSV is empty to keep the planner runnable.
    """
    stations = load_stations()
    if not stations:
        return Decimal('3.50')
    return sum(station['retail_price'] for station in stations) / Decimal(len(stations))


def station_for_state(state):
    """Return the cheapest station dict for a 2-letter state code, or None if absent."""
    return cheapest_station_by_state().get(state)
