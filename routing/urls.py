from django.urls import path

from .views import route_plan

urlpatterns = [
    path("route/", route_plan),
]