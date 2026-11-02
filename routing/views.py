import requests
from django.core.cache import cache
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import City, Station
from .planner import MPG, NoRouteError, plan_fuel, stations_on_route

OSRM_URL = ("https://router.project-osrm.org/route/v1/driving/"
            "{},{};{},{}?overview=full&geometries=geojson")


def resolve(text):
    """'Dallas, TX' -> (lat, lng) from our own cities table (no API call)."""
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Use 'City, ST' format, got '{text}'")
    name = " ".join(parts[0].lower().replace(".", "").split())
    c = City.objects.filter(name=name, state=parts[1].upper()).order_by("-population").first()
    if not c:
        raise LookupError(f"City not found: {text}")
    return c.lat, c.lng


@api_view(["GET"])
def route_plan(request):
    start, finish = request.GET.get("start"), request.GET.get("finish")
    if not start or not finish:
        return Response({"error": "start and finish are required, e.g. ?start=Dallas, TX&finish=Seattle, WA"}, status=400)

    key = f"route:{start.lower()}|{finish.lower()}"
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
    m = 0.25                                           # ~15+ miles margin around the route
    stations = list(Station.objects.filter(
        lat__range=(min(lats) - m, max(lats) + m),
        lng__range=(min(lngs) - m, max(lngs) + m),
    ).values("name", "address", "city", "state", "lat", "lng", "price"))

    on_route = stations_on_route(coords, stations, total_miles)
    try:
        stops, cost = plan_fuel(on_route, total_miles)
    except NoRouteError as e:
        return Response({"error": str(e)}, status=422)

    data = {
        "start": start, "finish": finish,
        "total_distance_miles": round(total_miles, 1),
        "total_gallons": round(total_miles / MPG, 1),
        "total_fuel_cost_usd": cost,
        "fuel_stops": stops,
        "route": {"type": "Feature", "properties": {}, "geometry": route["geometry"]},
    }
    cache.set(key, data, 3600)
    return Response(data)