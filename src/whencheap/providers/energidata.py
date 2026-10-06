"""Energi Data Service (Energinet, Denmark) Elspotprices. No API key."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from ..core import PricePoint, PriceSeries
from . import Provider, ProviderError, register


@register
class EnergiData(Provider):
    id = "energidata"
    name = "Energi Data Service (Energinet)"
    unit = "øre/kWh"
    attribution = "Price data: Energinet Energi Data Service, dataset Elspotprices (CC BY 4.0)"
    docs = "https://www.energidataservice.dk/tso-electricity/Elspotprices"
    zones = ("DK1", "DK2")
    description = "Danish spot prices in DKK øre/kWh (use energidata:DK1). The same zones are also on energycharts in EUR."

    def fetch(self, zone: str, start: datetime, end: datetime) -> PriceSeries:
        z = self.canonical(zone)
        s = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")
        e = (end.astimezone(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        flt = quote(json.dumps({"PriceArea": [z]}))
        url = "https://api.energidataservice.dk/dataset/Elspotprices?start=%s&end=%s&filter=%s&sort=HourUTC%%20asc&limit=0" % (s, e, flt)
        data = self._fetch_json(url)
        if not isinstance(data, dict) or "records" not in data:
            raise ProviderError("unexpected Energi Data Service response")
        pts = []
        for r in data["records"]:
            if r.get("SpotPriceDKK") is None:
                continue
            st = datetime.fromisoformat(r["HourUTC"]).replace(tzinfo=timezone.utc)
            pts.append(PricePoint(st, st + timedelta(hours=1), float(r["SpotPriceDKK"]) / 10.0))  # DKK/MWh -> øre/kWh
        return self._series(z, pts)
