from unittest.mock import MagicMock, patch

import numpy as np
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from .models import City, Station
from .planner import NoRouteError, plan_fuel


def st(mile, price):
    return {"name": f"S{mile}", "mile": mile, "price": price}


class PlannerTests(SimpleTestCase):
    def test_total_gallons_match_distance_and_cheapest_is_used(self):
        stops, cost = plan_fuel([st(300, 3.5), st(450, 3.0), st(800, 4.0), st(900, 3.2)], 1200)
        self.assertAlmostEqual(sum(s["gallons"] for s in stops), 120, places=1)   # 1200 mi / 10 mpg
        at450 = [s for s in stops if s["mile"] == 450][0]
        self.assertEqual(at450["gallons"], 50.0)                                   # full tank at the cheap station
        self.assertAlmostEqual(cost, sum(s["cost"] for s in stops), places=1)

    def test_short_trip_still_costs_money(self):
        stops, cost = plan_fuel([st(100, 3.0)], 300)
        self.assertGreater(cost, 0)
        self.assertAlmostEqual(sum(s["gallons"] for s in stops), 30, places=1)

    def test_no_station_in_range(self):
        with self.assertRaises(NoRouteError):
            plan_fuel([st(100, 3.0)], 1000)


class ApiTests(TestCase):
    def setUp(self):
        cache.clear()
        City.objects.create(name="dallas", state="TX", lat=32.78, lng=-96.80)
        City.objects.create(name="oklahoma city", state="OK", lat=35.47, lng=-97.52)
        for i, price in enumerate([3.4, 3.1, 3.3]):
            Station.objects.create(opis_id=i + 1, name=f"S{i}", address="x", city="c", state="TX",
                                   lat=32.78 + 0.9 * (i + 1), lng=-96.80 - 0.3 * (i + 1), price=price)

    def _osrm(self):
        n = 400
        lng = np.linspace(-96.80, -97.52, n)
        lat = np.linspace(32.78, 35.47, n)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"routes": [{
            "distance": 330 * 1609.344, "duration": 18000,
            "geometry": {"type": "LineString", "coordinates": [[float(a), float(b)] for a, b in zip(lng, lat)]},
        }]}
        return resp

    def test_route_plan_one_osrm_call_and_cache(self):
        with patch("routing.views.requests.get", return_value=self._osrm()) as m:
            r = self.client.get("/api/route/", {"start": "Dallas, TX", "finish": "Oklahoma City, OK"})
            self.assertEqual(r.status_code, 200, r.content)
            d = r.json()
            self.assertAlmostEqual(d["total_gallons"], 33.0, places=1)
            self.assertGreater(d["total_fuel_cost_usd"], 0)
            self.assertEqual(d["route"]["geometry"]["type"], "LineString")
            self.assertIn("map_url", d)
            self.client.get("/api/route/", {"start": "Dallas, TX", "finish": "Oklahoma City, OK"})
            self.assertEqual(m.call_count, 1)

    def test_validation(self):
        self.assertEqual(self.client.get("/api/route/").status_code, 400)
        self.assertEqual(self.client.get("/api/route/", {"start": "Nowhere, TX", "finish": "Dallas, TX"}).status_code, 404)