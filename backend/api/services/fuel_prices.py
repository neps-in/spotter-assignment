"""In-memory fuel price data loaded once from the assessment CSV.

Loading the CSV into module-level caches means zero database queries and zero
external calls when planning fuel stops at request time.
"""

import csv
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from django.conf import settings


@lru_cache(maxsize=1)
def load_stations():
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
    cheapest = {}
    for station in load_stations():
        state = station['state']
        if state not in cheapest or station['retail_price'] < cheapest[state]['retail_price']:
            cheapest[state] = station
    return cheapest


@lru_cache(maxsize=1)
def national_average_price():
    stations = load_stations()
    if not stations:
        return Decimal('3.50')
    return sum(station['retail_price'] for station in stations) / Decimal(len(stations))


def station_for_state(state):
    return cheapest_station_by_state().get(state)
