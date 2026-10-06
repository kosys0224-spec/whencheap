"""Static time-of-use tariffs from a local JSON file - for places without public dynamic prices (Korea, most of the US...).

File format (see examples/tou-example.json):

{
  "name": "My utility TOU plan",
  "unit": "KRW/kWh",
  "timezone": "Asia/Seoul",               # optional; default: local time
  "default": 120.0,                        # price used when no period matches
  "periods": [
    {"days": "mon-fri", "from": "09:00", "to": "12:00", "price": 190.0, "label": "peak"},
    {"days": "mon-fri", "from": "13:00", "to": "17:00", "price": 190.0, "label": "peak"},
    {"days": "all",     "from": "23:00", "to": "09:00", "price": 85.0,  "label": "off-peak"},
    {"months": "6-8", "days": "mon-fri", "from": "14:00", "to": "17:00", "price": 250.0, "label": "summer peak"}
  ]
}

Periods are matched in order; the first match wins. "to" earlier than "from" wraps past midnight.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from ..core import PricePoint, PriceSeries
from . import Provider, ProviderError, register

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_days(spec: str) -> set:
    spec = (spec or "all").strip().lower()
    if spec in ("all", "*", "daily", "everyday"):
        return set(range(7))
    if spec in ("weekday", "weekdays"):
        return set(range(5))
    if spec in ("weekend", "weekends"):
        return {5, 6}
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            ia, ib = _DAYS.index(a[:3]), _DAYS.index(b[:3])
            if ia <= ib:
                out.update(range(ia, ib + 1))
            else:
                out.update(list(range(ia, 7)) + list(range(0, ib + 1)))
        elif part:
            out.add(_DAYS.index(part[:3]))
    return out


def _parse_months(spec: Optional[str]) -> set:
    if not spec or str(spec).strip().lower() in ("all", "*"):
        return set(range(1, 13))
    out = set()
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            out.update(range(a, b + 1) if a <= b else list(range(a, 13)) + list(range(1, b + 1)))
        elif part:
            out.add(int(part))
    return out


def _minutes(hhmm: str) -> int:
    h, m = (hhmm.split(":") + ["0"])[:2]
    return int(h) * 60 + int(m)


def _tz(name: Optional[str]):
    if not name:
        return datetime.now().astimezone().tzinfo
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception as exc:  # pragma: no cover - depends on tzdata availability
        raise ProviderError("timezone %r not available (install the 'tzdata' package on Windows): %s" % (name, exc)) from exc


@register
class TimeOfUse(Provider):
    id = "tou"
    name = "Static time-of-use tariff (local file)"
    unit = "per kWh"
    attribution = ""
    docs = "https://github.com/kosys0224-spec/whencheap/blob/main/docs/tou-format.md"
    zones = ()
    description = "Your own tariff from a JSON file: `tou:/path/plan.json`. Works anywhere, no network."

    def supports(self, zone: str) -> bool:
        return zone.lower().endswith(".json")

    def fetch(self, zone: str, start: datetime, end: datetime) -> PriceSeries:
        path = Path(zone).expanduser()
        if not path.exists():
            raise ProviderError("TOU file not found: %s" % path)
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ProviderError("TOU file is not valid JSON: %s" % exc) from exc
        periods = spec.get("periods") or []
        default = float(spec.get("default", 0.0))
        tz = _tz(spec.get("timezone"))
        unit = spec.get("unit", "per kWh")
        compiled = []
        for p in periods:
            compiled.append((_parse_months(p.get("months")), _parse_days(p.get("days", "all")), _minutes(p["from"]), _minutes(p["to"]), float(p["price"]), p.get("label", "")))

        def price_for(local: datetime) -> float:
            mins = local.hour * 60 + local.minute
            for months, days, f, t, price, _label in compiled:
                if local.month not in months or local.weekday() not in days:
                    continue
                if f <= t:
                    if f <= mins < t:
                        return price
                else:  # wraps midnight
                    if mins >= f or mins < t:
                        return price
            return default

        # Build 15-minute slots, then merge equal neighbours.
        step = timedelta(minutes=15)
        t = start.astimezone(timezone.utc).replace(second=0, microsecond=0)
        t -= timedelta(minutes=t.minute % 15)
        raw: List[PricePoint] = []
        while t < end:
            raw.append(PricePoint(t, t + step, price_for(t.astimezone(tz))))
            t += step
        merged: List[PricePoint] = []
        for p in raw:
            if merged and merged[-1].price == p.price and merged[-1].end == p.start:
                merged[-1] = PricePoint(merged[-1].start, p.end, p.price)
            else:
                merged.append(p)
        s = self._series(spec.get("name") or path.name, merged, {"file": str(path)})
        s.unit = unit
        s.attribution = "Tariff: %s (local file %s)" % (spec.get("name", path.name), path.name)
        return s
