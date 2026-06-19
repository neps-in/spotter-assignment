from django.urls import path

from api.views import RoutePlannerView

urlpatterns = [
    path('route/', RoutePlannerView.as_view(), name='route-planner'),
]
