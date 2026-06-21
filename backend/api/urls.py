"""URL configuration for the api app.

Endpoints:
  POST /api/route/   — plan a fuel-optimised route between two US locations.
  GET  /api/verify/  — run the 5-case live verification suite once.
"""
from django.urls import path

from api.views import RoutePlannerView, VerifyView

urlpatterns = [
    path('route/', RoutePlannerView.as_view(), name='route-planner'),
    path('verify/', VerifyView.as_view(), name='verify-suite'),
]
