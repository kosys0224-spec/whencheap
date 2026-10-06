"""Elering (Estonian TSO) Nord Pool day-ahead prices for EE, FI, LV, LT. No API key."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..core import PricePoint, PriceSeries
from . import Provider, ProviderError, register


@register
class Elering(Provider):
    id = "elering"
    name = "Elering dashboard API"
    unit = "ct/kWh"
    attribution = "Price data: Elering AS (dashboard.elering.ee), Nord Pool day-ahead"
    docs = "https://dashboard.elering.ee/assets/api-doc.html"
    zones = ("EE", "FI", "LV", "LT")
    description = "Baltic + Finland day-ahead prices in EUR (use elering:EE). Same zones also on energycharts."

    def fetch(self, zone: str, start: datetime, end: datetime) -> PriceSeries:
        z = self.canonical(zone)
        fmt = "%Y-%m-%dT%H:%M:%S.000Z"
        url = "https://dashboard.elering.ee/api/nps/price?start=%s&end=%s" % (
            start.astimezone(timezone.utc).strftime(fmt), (end.astimezone(timezone.utc) + timedelta(hours=1)).strftime(fmt))
        data = self._fetch_json(url)
        rows = None
        if isinstance(data, dict):
            rows = (data.get("data") or {}).get(z.lower())
        if rows is None:
            raise ProviderError("unexpected Elering response (no %s data)" % z.lower())
        rows = sorted(rows, key=lambda r: r["timestamp"])
        pts = []
        for i, r in enumerate(rows):
            st = datetime.fromtimestamp(int(r["timestamp"]), tz=timezone.utc)
            if i + 1 < len(rows):
                en = datetime.fromtimestamp(int(rows[i + 1]["timestamp"]), tz=timezone.utc)
            else:
                en = st + timedelta(hours=1)
            pts.append(PricePoint(st, en, float(r["price"]) / 10.0))  # EUR/MWh -> ct/kWh
        return self._series(z, pts)
