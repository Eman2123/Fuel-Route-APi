import numpy as np
from scipy.spatial import cKDTree

RANGE_MI = 500
MPG = 10
MAX_OFF_ROUTE_MI = 10
MI_PER_DEG = 69.0
EARTH_R_MI = 3958.8


class NoRouteError(Exception):
    pass


def cumulative_miles(coords):
    """coords = [[lng, lat], ...] -> miles from start at every route point."""
    a = np.radians(np.asarray(coords, dtype=float))
    lng, lat = a[:, 0], a[:, 1]
    dlat, dlng = np.diff(lat), np.diff(lng)
    h = np.sin(dlat / 2) ** 2 + np.cos(lat[:-1]) * np.cos(lat[1:]) * np.sin(dlng / 2) ** 2
    seg = 2 * EARTH_R_MI * np.arcsin(np.sqrt(h))
    return np.concatenate([[0.0], np.cumsum(seg)])


def stations_on_route(coords, stations, total_miles):
    """Keep stations within MAX_OFF_ROUTE_MI of the route and give each a 'mile' marker."""
    if not stations:
        return []
    miles = cumulative_miles(coords)
    scale = total_miles / miles[-1] if miles[-1] else 1.0   # match the routing API distance
    pts = np.asarray(coords, dtype=float)
    k = np.cos(np.radians(pts[:, 1].mean()))                # shrink longitude to ~equal-distance units
    tree = cKDTree(np.column_stack([pts[:, 0] * k, pts[:, 1]]))
    sp = np.array([[s["lng"] * k, s["lat"]] for s in stations])
    dist, idx = tree.query(sp)

    out = []
    for s, d, i in zip(stations, dist, idx):
        off = float(d) * MI_PER_DEG
        if off <= MAX_OFF_ROUTE_MI:
            out.append({**s, "mile": float(miles[i]) * scale, "off_route_mi": round(off, 1)})
    out.sort(key=lambda s: s["mile"])
    return out


def plan_fuel(stations, total_miles):
    """Greedy: buy just enough to reach a cheaper station, else fill up and go to the cheapest in range.
    Assumes the trip starts with a full tank. Returns (stops, total_cost)."""
    dest = {"name": "Destination", "mile": total_miles, "price": 0.0}
    nodes = stations + [dest]
    cur = {"name": "Start", "mile": 0.0, "price": float("inf")}
    fuel = float(RANGE_MI)                                   # tank, measured in miles of range
    stops, cost = [], 0.0

    while cur["mile"] < total_miles:
        reach = [n for n in nodes if cur["mile"] < n["mile"] <= cur["mile"] + RANGE_MI]
        if not reach:
            raise NoRouteError(f"No fuel station within {RANGE_MI} miles after mile {cur['mile']:.0f}")

        cheaper = next((n for n in reach if n["price"] < cur["price"]), None)
        if cheaper:
            nxt = cheaper
            buy = max(0.0, (nxt["mile"] - cur["mile"]) - fuel)
        else:
            nxt = min(reach, key=lambda n: n["price"])
            buy = RANGE_MI - fuel

        if buy > 0:
            gallons = buy / MPG
            spent = gallons * cur["price"]
            cost += spent
            stops.append({
                "name": cur["name"], "address": cur.get("address"),
                "city": cur.get("city"), "state": cur.get("state"),
                "lat": cur.get("lat"), "lng": cur.get("lng"),
                "mile": round(cur["mile"], 1), "price_per_gallon": cur["price"],
                "gallons": round(gallons, 2), "cost": round(spent, 2),
            })
            fuel += buy
        fuel -= nxt["mile"] - cur["mile"]
        cur = nxt

    return stops, round(cost, 2)