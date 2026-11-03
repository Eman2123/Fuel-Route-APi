from django.contrib import admin
from django.urls import include, path

from routing.views import map_page

urlpatterns = [
    path("", map_page, name="map"),
    path("admin/", admin.site.urls),
    path("api/", include("routing.urls")),
]