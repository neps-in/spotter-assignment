from concurrent.futures import ThreadPoolExecutor

import requests
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.exceptions import RoutingServiceError
from api.serializers import RouteRequestSerializer
from api.services.fuel_planner import plan_fuel_stops
from api.services.geo_utils import downsample_points
from api.services.geocoder import geocode
from api.services.router import get_route
from api.verification import run_suite


class RoutePlannerView(APIView):
    """POST /api/route/  -> route geometry + cost-optimal fuel stops + total cost.

    External calls per request: 2 Nominatim (geocode start/finish, run in
    parallel) + 1 OSRM (route) = 3 max, all cached after first use.
    """

    def post(self, request):
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        start = serializer.validated_data['start']
        finish = serializer.validated_data['finish']

        try:
            # Geocode start and finish in parallel to halve the Nominatim wait time.
            with ThreadPoolExecutor(max_workers=2) as executor:
                origin_future = executor.submit(geocode, start)
                destination_future = executor.submit(geocode, finish)
                origin = origin_future.result()
                destination = destination_future.result()
            route = get_route(origin, destination)
        except requests.RequestException as exc:
            raise RoutingServiceError(f'External routing/geocoding service failed: {exc}') from exc

        fuel_plan = plan_fuel_stops(route['decoded_points'], route['distance_miles'])
        # Thin the polyline before sending — the frontend only needs ~700 points for rendering.
        geojson_points = downsample_points(route['decoded_points'])

        return Response({
            'start': start,
            'finish': finish,
            'origin': origin,
            'destination': destination,
            'total_distance_miles': round(route['distance_miles'], 2),
            'estimated_duration_hours': round(route['duration_seconds'] / 3600, 2),
            'fuel_stops': fuel_plan['fuel_stops'],
            'total_gallons': fuel_plan['total_gallons'],
            'total_fuel_cost': fuel_plan['total_fuel_cost'],
            'route_geojson': {
                'type': 'LineString',
                # GeoJSON spec requires [lon, lat] order — the opposite of OSRM's (lat, lon) tuples.
                'coordinates': [[round(lon, 6), round(lat, 6)] for lat, lon in geojson_points],
            },
        }, status=status.HTTP_200_OK)


class VerifyView(APIView):
    """GET /api/verify/ -> run the 5-case live verification suite once.

    Picks a fresh random US city pair on every call and reports per-test
    pass/fail. Lets the frontend "Verify" console execute the testcases.
    """

    def get(self, request):
        try:
            report = run_suite()
        except requests.RequestException as exc:
            return Response(
                {'detail': f'Verification could not reach external services: {exc}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(report, status=status.HTTP_200_OK)
