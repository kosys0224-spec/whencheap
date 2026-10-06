"""Octopus Energy Agile (Great Britain) half-hourly unit rates, per DNO region. No API key."""
from __future__ import annotations

from datetime import datetime, timezone

from ..core import PricePoint, PriceSeries, _parse_iso
from . import Provider, ProviderError, register

PRODUCT = "AGILE-24-10-01"
REGIONS = ("A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M", "N", "P")
REGION_NAMES = {
    "A": "Eastern England", "B": "East Midlands", "C": "London", "D": "Merseyside and Northern Wales", "E": "West Midlands",
    "F": "North Eastern England", "G": "North Western England", "H": "Southern England", "J": "South Eastern England",
    "K": "Southern Wales", "L": "South Western England", "M": "Yorkshire", "N": "Southern Scotland", "P": "Northern Scotland",
}


@register
class OctopusAgile(Provider):
    id = "octopus"
    name = "Octopus Energy Agile"
    unit = "p/kWh"
    attribution = "Price data: Octopus Energy public API (product %s), incl. VAT" % PRODUCT
    docs = "https://developer.octopus.energy/rest/guides/endpoints"
    zones = tuple("GB-" + r for r in REGIONS)
    description = "Agile Octopus half-hourly import rates by GB region letter (GB-A ... GB-P), pence incl. VAT."

    def fetch(self, zone: str, start: datetime, end: datetime) -> PriceSeries:
        z = self.canonical(zone)
        region = z.split("-", 1)[1]
        tariff = "E-1R-%s-%s" % (PRODUCT, region)
        url = ("https://api.octopus.energy/v1/products/%s/electricity-tariffs/%s/standard-unit-rates/"
               "?period_from=%s&period_to=%s&page_size=1500") % (
            PRODUCT, tariff, start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))
        data = self._fetch_json(url)
        if not isinstance(data, dict) or "results" not in data:
            raise ProviderError("unexpected Octopus response for %s" % tariff)
        pts = [PricePoint(_parse_iso(r["valid_from"]), _parse_iso(r["valid_to"]), float(r["value_inc_vat"]))
               for r in data["results"] if r.get("valid_to")]
        return self._series(z, pts, {"tariff": tariff, "region": REGION_NAMES.get(region, "")})
