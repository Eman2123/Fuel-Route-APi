# Fuel Route API (Django 6.1)

Start/finish inside the USA -> route map, cheapest fuel stops (500 mi range, 10 mpg) and total fuel cost.

## Setup
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_data      # loads cities + geocoded stations (6.6k US stations)
python manage.py runserver
```

* API: `GET /api/route/?start=Los Angeles, CA&finish=New York, NY` (`lat,lng` also accepted)
* Map UI: `http://127.0.0.1:8000/` (or the `map_url` in the response)
* Tests: `python manage.py test`

## How it works
1. `start` / `finish` are resolved from the local `City` table (no API call).
2. ONE call to the free OSRM API returns the route geometry + distance (cached per start/finish for 1 h).
3. Stations within 10 miles of the route are found with a KD-tree; each gets a mile marker.
4. Greedy optimal planner: buy just enough to reach a cheaper station, otherwise fill up and go to the cheapest in range.
5. Response: route GeoJSON (downsampled), fuel stops (gallons, price, cost), total gallons and total cost.

## Assumptions
* Tank starts empty; first fill is priced at the first station on the route, so all fuel burned is paid for.
* Fuel CSV has no coordinates -> stations are placed at their city centroid (`data/us_cities.csv`); non-US rows are dropped
  and duplicate listings keep the cheapest price.
* Stops that save less than $0.03/gal are ignored to avoid stopping for pennies (`MIN_SAVINGS` in `planner.py`).