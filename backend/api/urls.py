from django.urls import path

from api.views import RoutePlannerView, VerifyView

urlpatterns = [
    path('route/', RoutePlannerView.as_view(), name='route-planner'),
    path('verify/', VerifyView.as_view(), name='verify-suite'),
]
