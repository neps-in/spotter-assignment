from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.services.fuel_planner import plan_fuel_stops
from api.services.geo_utils import haversine_miles, point_to_state


def _station(state, price):
    return {
        'opis_id': 1,
        'name': f'{state} TRUCKSTOP',
        'address': 'I-X EXIT 1',
        'city': 'Town',
        'state': state,
        'retail_price': Decimal(price),
    }


class GeoUtilsTests(TestCase):
    def test_haversine_known_distance(self):
        # Austin, TX -> Dallas, TX is ~182 miles great-circle.
        distance = haversine_miles((30.2672, -97.7431), (32.7767, -96.7970))
        self.assertAlmostEqual(distance, 182, delta=15)

    def test_point_to_state(self):
        self.assertEqual(point_to_state(30.2672, -97.7431), 'TX')
        self.assertEqual(point_to_state(47.6062, -122.3321), 'WA')


@override_settings(VEHICLE_MAX_RANGE_MILES=500, FUEL_SAFETY_BUFFER_MILES=50, VEHICLE_MPG=10)
class FuelPlannerTests(TestCase):
    @patch('api.services.fuel_planner.station_for_state')
    def test_uniform_price_total_cost_is_distance_independent_of_stops(self, station_for_state):
        # With one flat price everywhere, total cost must equal
        # distance / mpg * price regardless of how stops are placed.
        station_for_state.return_value = _station('TX', '3.00')
        route = [(39.0, -100.0 + i * 0.2) for i in range(40)]  # long east-west line

        result = plan_fuel_stops(route, 900.0)

        self.assertEqual(result['total_gallons'], 90.0)        # 900 / 10
        self.assertEqual(result['total_fuel_cost'], 270.0)     # 90 * 3.00
        self.assertGreaterEqual(len(result['fuel_stops']), 2)  # 900mi > 450 window

    def test_greedy_picks_cheaper_state_inside_the_window(self):
        # A cheap pocket sits ~100-215mi in (lon -98..-96); everything else is
        # expensive. A fixed 450-mile trigger would skip the pocket and only
        # ever pay the expensive price. The window planner must use the cheap one.
        def fake_state(lat, lon):
            return 'CHEAP' if -98.0 <= lon <= -96.0 else 'EXP'

        def fake_station(state):
            return _station(state, '3.00' if state == 'CHEAP' else '5.00')

        route = [(39.0, -100.0 + i * 0.1) for i in range(151)]  # ~800mi west->east

        with patch('api.services.fuel_planner.point_to_state', side_effect=fake_state), \
             patch('api.services.fuel_planner.station_for_state', side_effect=fake_station):
            result = plan_fuel_stops(route, 800.0)

        used_cheap = any(
            stop['state'] == 'CHEAP' and stop['price_per_gallon'] == 3.0
            for stop in result['fuel_stops']
        )
        self.assertTrue(used_cheap, 'planner should refuel in the cheap state inside the window')
        # All-expensive baseline would be 800/10*5 = $400; using cheap fuel beats it.
        self.assertLess(result['total_fuel_cost'], 400.0)


@override_settings(VEHICLE_MAX_RANGE_MILES=500, FUEL_SAFETY_BUFFER_MILES=50, VEHICLE_MPG=10)
class RoutePlannerApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch('api.views.geocode')
    @patch('api.views.get_route')
    @patch('api.services.fuel_planner.station_for_state')
    def test_route_api_response_shape(self, station_for_state, get_route, geocode):
        station_for_state.return_value = _station('OK', '3.00')
        geocode.side_effect = [
            {'lat': 30.2672, 'lon': -97.7431, 'display_name': 'Austin, TX'},
            {'lat': 47.6062, 'lon': -122.3321, 'display_name': 'Seattle, WA'},
        ]
        get_route.return_value = {
            'distance_miles': 900.0,
            'duration_seconds': 36000,
            'encoded_polyline': '',
            'decoded_points': [(30.0, -97.0), (35.0, -105.0), (47.0, -122.0)],
        }

        response = self.client.post(
            '/api/route/',
            {'start': 'Austin, TX', 'finish': 'Seattle, WA'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['total_distance_miles'], 900.0)
        self.assertEqual(body['total_gallons'], 90.0)
        self.assertEqual(body['route_geojson']['type'], 'LineString')
        self.assertGreaterEqual(len(body['fuel_stops']), 2)
        first = body['fuel_stops'][0]
        self.assertIn('distance_from_start_miles', first)
        self.assertIn('miles_covered', first)
        self.assertIn('segment_cost', first)

    def test_rejects_identical_start_and_finish(self):
        response = self.client.post(
            '/api/route/',
            {'start': 'Austin, TX', 'finish': 'austin, tx'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
