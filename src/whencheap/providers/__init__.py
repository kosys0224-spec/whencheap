"""Price providers. Each one turns a public, keyless API into a PriceSeries in ct/kWh (or p/kWh)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from .. import __version__
from ..core import PriceSeries

USER_AGENT = "whencheap/%s (+https://github.com/kosys0224-spec/whencheap)" % __version__


class ProviderError(RuntimeError):
    pass


def http_get(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https hosts
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise ProviderError("rate limited by %s (HTTP 429). Try again in a minute; whencheap caches results so this is rare." % url.split("/")[2]) from exc
        raise ProviderError("HTTP %d from %s" % (exc.code, url)) from exc
    except urllib.error.URLError as exc:
        raise ProviderError("cannot reach %s: %s" % (url.split("/")[2], exc.reason)) from exc


def http_get_json(url: str, timeout: float = 20.0):
    raw = http_get(url, timeout)
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise ProviderError("non-JSON response from %s" % url) from exc


Fetcher = Callable[[str], object]


class Provider:
    id: str = ""
    name: str = ""
    unit: str = "ct/kWh"
    attribution: str = ""
    docs: str = ""
    zones: Tuple[str, ...] = ()
    description: str = ""

    def __init__(self, fetch_json: Optional[Fetcher] = None):
        self._fetch_json = fetch_json or http_get_json

    def supports(self, zone: str) -> bool:
        return zone.upper() in {z.upper() for z in self.zones}

    def canonical(self, zone: str) -> str:
        for z in self.zones:
            if z.upper() == zone.upper():
                return z
        return zone

    def fetch(self, zone: str, start: datetime, end: datetime) -> PriceSeries:  # pragma: no cover - abstract
        raise NotImplementedError

    def _series(self, zone: str, points, extra: Optional[dict] = None) -> PriceSeries:
        return PriceSeries(zone=self.canonical(zone), unit=self.unit, points=list(points), source=self.id,
                           attribution=self.attribution, fetched_at=datetime.now(timezone.utc), extra=extra or {})


_REGISTRY: Dict[str, type] = {}


def register(cls):
    _REGISTRY[cls.id] = cls
    return cls


def all_providers(fetch_json: Optional[Fetcher] = None) -> List[Provider]:
    from . import energycharts, awattar, octopus, energidata, elering, tou  # noqa: F401  (registration)

    return [cls(fetch_json) for cls in _REGISTRY.values()]


def resolve(zone: str, fetch_json: Optional[Fetcher] = None) -> Tuple[Provider, str]:
    """'DE-LU' -> (EnergyCharts, 'DE-LU'); 'awattar:AT' -> (Awattar, 'AT'); 'GB-C' -> (Octopus, 'GB-C'); 'tou:path.json'."""
    providers = all_providers(fetch_json)
    if ":" in zone:
        pid, z = zone.split(":", 1)
        for p in providers:
            if p.id == pid.lower():
                if p.id == "tou" or p.supports(z):
                    return p, (z if p.id == "tou" else p.canonical(z))
                raise ProviderError("provider %s does not know zone %r. Known: %s" % (p.id, z, ", ".join(p.zones)))
        raise ProviderError("unknown provider %r. Known: %s" % (pid, ", ".join(p.id for p in providers)))
    for p in providers:
        if p.id != "tou" and p.supports(zone):
            return p, p.canonical(zone)
    if zone.lower().endswith(".json") or zone.lower().endswith(".csv"):
        for p in providers:
            if p.id == "tou":
                return p, zone
    raise ProviderError("unknown zone %r. Run `whencheap zones` to list them." % zone)
