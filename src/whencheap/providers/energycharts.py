"""Energy-Charts (Fraunhofer ISE) day-ahead prices for European bidding zones. No API key."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..core import PricePoint, PriceSeries
from . import Provider, ProviderError, register

# Zones whose data is CC BY 4.0 (Bundesnetzagentur | SMARD.de). The API serves more zones, but marks
# them "for private and internal use only"; we keep them available and print the attribution either way.
_OPEN_ZONES = ("AT", "BE", "CH", "CZ", "DE-LU", "DE-AT-LU", "DK1", "DK2", "FR", "HU", "IT-North", "NL", "NO2", "PL", "SE4", "SI")
_OTHER_ZONES = ("BG", "EE", "ES", "FI", "GR", "HR", "IT-Calabria", "IT-Centre-North", "IT-Centre-South", "IT-SACOAC",
                "IT-SACODC", "IT-Sardinia", "IT-Sicily", "IT-South", "LT", "LV", "ME", "NO1", "NO3", "NO4", "NO5", "PT", "RO",
                "RS", "SE1", "SE2", "SE3", "SK", "IE(SEM)")


@register
class EnergyCharts(Provider):
    id = "energycharts"
    name = "Energy-Charts (Fraunhofer ISE)"
    unit = "ct/kWh"
    attribution = "Price data: CC BY 4.0 from Bundesnetzagentur | SMARD.de via api.energy-charts.info"
    docs = "https://api.energy-charts.info/"
    zones = _OPEN_ZONES + _OTHER_ZONES
    description = "EU day-ahead (EPEX/Nord Pool) prices, 15-min or hourly, EUR. Rate limit 2 req/min - whencheap caches."

    def fetch(self, zone: str, start: datetime, end: datetime) -> PriceSeries:
        z = self.canonical(zone)
        s = start.astimezone(timezone.utc).strftime("%Y-%m-%d")
        e = (end.astimezone(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        data = self._fetch_json("https://api.energy-charts.info/price?bzn=%s&start=%s&end=%s" % (z, s, e))
        if not isinstance(data, dict) or "unix_seconds" not in data:
            raise ProviderError("unexpected Energy-Charts response for %s" % z)
        ts = data.get("unix_seconds") or []
        prices = data.get("price") or []
        unit = (data.get("unit") or "EUR / MWh").replace(" ", "")
        factor = 0.1 if unit.upper().startswith("EUR/MWH") else 1.0
        pts = []
        for i, (t, p) in enumerate(zip(ts, prices)):
            if p is None:
                continue
            st = datetime.fromtimestamp(t, tz=timezone.utc)
            if i + 1 < len(ts):
                en = datetime.fromtimestamp(ts[i + 1], tz=timezone.utc)
            else:
                prev = ts[i] - ts[i - 1] if i > 0 else 3600
                en = st + timedelta(seconds=prev)
            pts.append(PricePoint(st, en, float(p) * factor))
        extra = {"license": data.get("license_info", ""), "open_data": z in _OPEN_ZONES}
        return self._series(z, pts, extra)

