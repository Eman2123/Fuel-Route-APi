import numpy as np
from scipy.spatial import KDTree

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


def stations_on_route(coords, stations, total_miles, max_off=MAX_OFF_ROUTE_MI):
    """Keep stations within MAX_OFF_ROUTE_MI of the route and give each a 'mile' marker."""
    if not stations:
        return []
    miles = cumulative_miles(coords)
    scale = total_miles / miles[-1] if miles[-1] else 1.0   # match the routing API distance
    pts = np.asarray(coords, dtype=float)
    k = np.cos(np.radians(pts[:, 1].mean()))                # shrink longitude to ~equal-distance units
    tree = KDTree(np.column_stack([pts[:, 0] * k, pts[:, 1]]))
    sp = np.array([[s["lng"] * k, s["lat"]] for s in stations])
    dist, idx = tree.query(sp)

    out = []
    for s, d, i in zip(stations, dist.tolist(), idx.tolist()): # type: ignore
        off = float(d) * MI_PER_DEG
        if off <= max_off:
            out.append({**s, "mile": float(miles[i]) * scale, "off_route_mi": round(off, 1)})
    # stations of one town share coordinates: keep only the cheapest per location
    best = {}
    for s in out:
        k = (s["lat"], s["lng"])
        if k not in best or s["price"] < best[k]["price"]:
            best[k] = s
    return sorted(best.values(), key=lambda s: s["mile"])


MIN_BUY_GALLONS = 3   # purchases smaller than this are skipped or folded into the previous stop when possible
MIN_SAVINGS = 0.03   # $/gal: ignore "cheaper" stations that save less than this (avoids stopping for pennies)


def plan_fuel(stations, total_miles):
    """Greedy: buy just enough to reach a cheaper station, else fill up and go to the cheapest in range.
    Tank starts empty: the first fill happens at the start, priced at the first station on the route,
    so every gallon burned is paid for. Returns (stops, total_cost)."""
    dest = {"name": "Destination", "mile": total_miles, "price": 0.0}
    nodes = stations + [dest]
    first_price = stations[0]["price"] if stations else 0.0
    cur = {"name": "Start (initial fill)", "mile": 0.0, "price": first_price}
    fuel = 0.0                                               # tank, measured in miles of range
    stops, cost = [], 0.0

    while cur["mile"] < total_miles:
        reach = [n for n in nodes if cur["mile"] < n["mile"] <= cur["mile"] + RANGE_MI]
        if not reach:
            raise NoRouteError(f"No fuel station within {RANGE_MI} miles after mile {cur['mile']:.0f}")

        cheaper = next((n for n in reach if n is dest or n["price"] < cur["price"] - MIN_SAVINGS), None)
        if cheaper:
            nxt = cheaper
            buy = max(0.0, (nxt["mile"] - cur["mile"]) - fuel)
        else:
            floor = min(n["price"] for n in reach)
            nxt = max((n for n in reach if n["price"] <= floor + MIN_SAVINGS), key=lambda n: n["mile"])
            buy = RANGE_MI - fuel
            if cur["mile"] > 0 and buy < MIN_BUY_GALLONS * MPG and fuel >= nxt["mile"] - cur["mile"]:
                buy = 0.0                                   # tank nearly full already: not worth stopping

        if buy > 0:
            gallons = buy / MPG
            spent = gallons * cur["price"]
            cost += spent
            stops.append({
                "name": cur["name"], "address": cur.get("address"),
                "city": cur.get("city"), "state": cur.get("state"),
                "lat": cur.get("lat"), "lng": cur.get("lng"),
                "mile": round(cur["mile"], 1), "price_per_gallon": round(cur["price"], 3),
                "gallons": round(gallons, 2), "cost": round(spent, 2),
                "_price": cur["price"], "_gal": gallons, "_tank_after": fuel + buy,
            })
            fuel += buy
        fuel -= nxt["mile"] - cur["mile"]
        cur = nxt

    stops = _absorb_tiny(stops)
    return stops, round(sum(st["cost"] for st in stops), 2)


def _absorb_tiny(stops, max_extra_cost=1.0):
    """Fold a tiny purchase into the previous stop if its tank has room and it costs < $1 extra."""
    out = list(stops)
    k = 1
    while k < len(out):
        cur, prev = out[k], out[k - 1]
        room = RANGE_MI - prev["_tank_after"]
        extra = cur["_gal"] * max(0.0, prev["_price"] - cur["_price"])
        if cur["_gal"] < MIN_BUY_GALLONS and cur["_gal"] * MPG <= room and extra <= max_extra_cost and prev["name"] != cur["name"]:
            prev["_gal"] += cur["_gal"]
            prev["_tank_after"] += cur["_gal"] * MPG
            del out[k]
        else:
            k += 1
    for st in out:
        st["gallons"] = round(st["_gal"], 2)
        st["cost"] = round(st["_gal"] * st["_price"], 2)
        for key in ("_price", "_gal", "_tank_after"):
            st.pop(key)
    return out