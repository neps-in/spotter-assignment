from rest_framework.exceptions import APIException


class LocationNotFoundError(APIException):
    status_code = 400
    default_detail = 'Location was not found.'
    default_code = 'location_not_found'


class LocationOutsideUSAError(APIException):
    status_code = 400
    default_detail = 'Location must be within the contiguous United States.'
    default_code = 'location_outside_usa'


class RoutingServiceError(APIException):
    status_code = 502
    default_detail = 'Routing service failed.'
    default_code = 'routing_service_error'
