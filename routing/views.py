import hashlib
import re
from urllib.parse import urlencode

import requests
from django.core.cache import cache
from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import City, Station
from .planner import MAX_OFF_ROUTE_MI as CORRIDOR_MILES, MPG, RANGE_MI as MAX_RANGE_MILES, NoRouteError, plan_fuel, stations_on_route

OSRM_URL = ("https://router.project-osrm.org/route/v1/driving/"
            "{},{};{},{}?overview=full&geometries=geojson")


def resolve(text):
    """'Dallas, TX' -> (lat, lng) from our own cities table (no API call). 'lat,lng' also works."""
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", text)
    if m:
        return float(m.group(1)), float(m.group(2))
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Use 'City, ST' format, got '{text}'")
    name = " ".join(parts[0].lower().replace(".", "").split())
    c = City.objects.filter(name=name, state=parts[1].upper()).order_by("-population").first()
    if not c:
        raise LookupError(f"City not found: {text}")
    return c.lat, c.lng


def downsample(coords, max_points=2000):
    """Cross-country routes have 50k+ points; ~2000 is plenty to draw on a map and keeps responses fast."""
    step = max(1, -(-len(coords) // max_points))
    out = [[round(c[0], 5), round(c[1], 5)] for c in coords[::step]]
    last = [round(coords[-1][0], 5), round(coords[-1][1], 5)]
    if out[-1] != last:
        out.append(last)
    return out


def map_page(request):
    """Browser map UI (Leaflet) that calls /api/route/."""
    return render(request, "routing/map.html",
                  {"start": request.GET.get("start", ""), "finish": request.GET.get("finish", "")})


@api_view(["GET"])
def route_plan(request):
    start, finish = request.GET.get("start"), request.GET.get("finish")
    if not start or not finish:
        return Response({"error": "start and finish are required, e.g. ?start=Dallas, TX&finish=Seattle, WA"}, status=400)

    key = "route:" + hashlib.md5(f"{start.lower()}|{finish.lower()}".encode()).hexdigest()
    if (hit := cache.get(key)):
        return Response(hit)

    try:
        (lat1, lng1), (lat2, lng2) = resolve(start), resolve(finish)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except LookupError as e:
        return Response({"error": str(e)}, status=404)

    # the ONLY external call
    try:
        resp = requests.get(OSRM_URL.format(lng1, lat1, lng2, lat2), timeout=20)
        resp.raise_for_status()
        route = resp.json()["routes"][0]
    except (requests.RequestException, KeyError, IndexError):
        return Response({"error": "Routing service failed or no route found"}, status=502)

    coords = route["geometry"]["coordinates"]
    total_miles = route["distance"] / 1609.344

    lats, lngs = [c[1] for c in coords], [c[0] for c in coords]
    stops = None
    # Widen the corridor only if a narrower one leaves a gap longer than the vehicle's range.
    for corridor in (CORRIDOR_MILES, 25, 50):
        m = corridor / 69.0 + 0.1                      # bbox margin in degrees
        stations = list(Station.objects.filter(
            lat__range=(min(lats) - m, max(lats) + m),
            lng__range=(min(lngs) - m * 1.5, max(lngs) + m * 1.5),
        ).values("name", "address", "city", "state", "lat", "lng", "price"))
        on_route = stations_on_route(coords, stations, total_miles, max_off=corridor)
        try:
            stops, cost = plan_fuel(on_route, total_miles)
            break
        except NoRouteError as e:
            last_error = e
    if stops is None:
        return Response({"error": str(last_error)}, status=422)

    data = {
        "start": start, "finish": finish,
        "total_distance_miles": round(total_miles, 1),
        "duration_hours": round(route["duration"] / 3600, 2),
        "total_gallons": round(total_miles / MPG, 1),
        "total_fuel_cost_usd": cost,
        "fuel_stops": stops,
        "map_url": request.build_absolute_uri("/?" + urlencode({"start": start, "finish": finish})),
        "route": {"type": "Feature", "properties": {"distance_miles": round(total_miles, 1)},
                  "geometry": {"type": "LineString", "coordinates": downsample(coords)}},
        "assumptions": [
            f"Tank starts empty; max range {MAX_RANGE_MILES} miles, {MPG} mpg.",
            "Total cost = all fuel burned on the trip at the price paid where it was bought.",
            "Stations sit at their city centroid; those within the corridor of the route are candidates.",
        ],
    }
    cache.set(key, data, 3600)
    return Response(data)