import csv
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from routing.models import City, Station

DATA = Path(settings.BASE_DIR) / "data"

# Towns missing from the gazetteer (approximate centroids).
MANUAL = {
    ("port wentworth", "GA"): (32.1488, -81.1673),
    ("elizabethport", "NJ"): (40.6590, -74.1900),
    ("brookpark", "OH"): (41.3995, -81.8046),
    ("evergreen", "AL"): (31.4335, -86.9558),
    ("henrico", "VA"): (37.5540, -77.4010),
    ("university park", "IL"): (41.4437, -87.6830),
}


def norm(name):
    name = name.lower().replace(".", "").replace("'", "")
    name = re.sub(r"\bsaint\b", "st", name)
    name = re.sub(r"\bmount\b", "mt", name)
    name = re.sub(r"\bfort\b", "ft", name)
    return " ".join(name.split())


class Command(BaseCommand):
    help = "Load cities and geocoded stations from data/*.csv"

    @transaction.atomic
    def handle(self, *args, **opts):
        City.objects.all().delete()
        Station.objects.all().delete()

        cities, seen = [], {}
        with open(DATA / "us_cities.csv", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                key = (norm(r["city"]), r["state"])
                if key in seen:
                    continue
                seen[key] = (float(r["lat"]), float(r["lng"]))
                cities.append(City(name=key[0], state=key[1], lat=seen[key][0], lng=seen[key][1]))
        City.objects.bulk_create(cities, batch_size=5000)
        seen.update(MANUAL)
        us_states = {s for _, s in seen}

        best, foreign, missing = {}, 0, 0
        with open(DATA / "fuel-prices-for-be-assessment.csv", newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                state = r["State"].strip().upper()
                if state not in us_states:
                    foreign += 1
                    continue
                ll = seen.get((norm(r["City"]), state))
                if ll is None:
                    missing += 1
                    continue
                sid, price = int(r["OPIS Truckstop ID"]), float(r["Retail Price"])
                if sid in best and best[sid].price <= price:
                    continue
                best[sid] = Station(
                    opis_id=sid, name=r["Truckstop Name"].strip(), address=r["Address"].strip(),
                    city=r["City"].strip(), state=state, lat=ll[0], lng=ll[1], price=price,
                )
        Station.objects.bulk_create(best.values(), batch_size=5000)
        self.stdout.write(self.style.SUCCESS(
            f"Loaded {len(cities)} cities, {len(best)} stations "
            f"(skipped {foreign} non-US rows, {missing} unmatched cities)"
        ))