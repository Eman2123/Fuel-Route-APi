from django.test import SimpleTestCase

from .planner import NoRouteError, plan_fuel


def st(mile, price):
    return {"name": f"S{mile}", "mile": mile, "price": price}


class PlannerTests(SimpleTestCase):
    def test_cost_and_stops(self):
        stops, cost = plan_fuel([st(300, 3.5), st(450, 3.0), st(800, 4.0), st(900, 3.2)], 1200)
        self.assertEqual([s["mile"] for s in stops], [450, 900])
        self.assertEqual(cost, 215.0)          # 45 gal * 3.0 + 25 gal * 3.2

    def test_no_station_in_range(self):
        with self.assertRaises(NoRouteError):
            plan_fuel([st(100, 3.0)], 1000)