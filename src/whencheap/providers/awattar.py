"""aWATTar hourly market data for Germany and Austria. No API key."""
from __future__ import annotations

from datetime import datetime, timezone

from ..core import PricePoint, PriceSeries
from . import Provider, ProviderError, register


@register
class Awattar(Provider):
    id = "awattar"
    name = "aWATTar"
    unit = "ct/kWh"
    attribution = "Price data: aWATTar market data API (api.awattar.de / api.awattar.at)"
    docs = "https://www.awattar.de/services/api"
    zones = ("DE", "AT")
    description = "EPEX day-ahead hourly prices for DE and AT as published by aWATTar. Use `awattar:DE` / `awattar:AT`."

    def fetch(self, zone: str, start: datetime, end: datetime) -> PriceSeries:
        z = self.canonical(zone)
        host = "api.awattar.de" if z == "DE" else "api.awattar.at"
        s_ms = int(start.astimezone(timezone.utc).timestamp() * 1000)
        e_ms = int(end.astimezone(timezone.utc).timestamp() * 1000)
        data = self._fetch_json("https://%s/v1/marketdata?start=%d&end=%d" % (host, s_ms, e_ms))
        if not isinstance(data, dict) or "data" not in data:
            raise ProviderError("unexpected aWATTar response")
        pts = []
        for row in data["data"]:
            unit = (row.get("unit") or "Eur/MWh").replace(" ", "").lower()
            factor = 0.1 if unit.startswith("eur/mwh") else 1.0
            pts.append(PricePoint(
                datetime.fromtimestamp(row["start_timestamp"] / 1000, tz=timezone.utc),
                datetime.fromtimestamp(row["end_timestamp"] / 1000, tz=timezone.utc),
                float(row["marketprice"]) * factor,
            ))
        return self._series(z, pts)
