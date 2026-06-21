from rest_framework.exceptions import APIException


class LocationNotFoundError(APIException):
    """Raised when Nominatim returns no results for the supplied location string."""

    status_code = 400
    default_detail = 'Location was not found.'
    default_code = 'location_not_found'


class LocationOutsideUSAError(APIException):
    """Raised when geocoding succeeds but the coordinates fall outside the contiguous USA."""

    status_code = 400
    default_detail = 'Location must be within the contiguous United States.'
    default_code = 'location_outside_usa'


class RoutingServiceError(APIException):
    """Raised when OSRM returns a non-OK status code or an empty route list."""

    status_code = 502
    default_detail = 'Routing service failed.'
    default_code = 'routing_service_error'
