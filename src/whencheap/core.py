"""Price series model and the cheapest-window search. No I/O here."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class PricePoint:
    start: datetime          # timezone-aware (UTC)
    end: datetime
    price: float             # in `PriceSeries.unit` (e.g. ct/kWh)

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0


@dataclass
class PriceSeries:
    zone: str
    unit: str                      # e.g. "ct/kWh", "p/kWh", "øre/kWh"
    points: List[PricePoint]
    source: str = ""               # provider id
    attribution: str = ""          # license / credit line required by the provider
    fetched_at: Optional[datetime] = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.points = sorted(self.points, key=lambda p: p.start)

    # -- basic stats -------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.points)

    def span(self):
        if not self.points:
            return None, None
        return self.points[0].start, self.points[-1].end

    def average(self) -> float:
        tot = sum(p.price * p.minutes for p in self.points)
        mins = sum(p.minutes for p in self.points)
        return tot / mins if mins else float("nan")

    def min_point(self) -> Optional[PricePoint]:
        return min(self.points, key=lambda p: p.price) if self.points else None

    def max_point(self) -> Optional[PricePoint]:
        return max(self.points, key=lambda p: p.price) if self.points else None

    def price_at(self, when: datetime) -> Optional[float]:
        for p in self.points:
            if p.start <= when < p.end:
                return p.price
        return None

    def future(self, now: datetime) -> "PriceSeries":
        """Points that have not ended yet (the current slot is kept)."""
        return PriceSeries(self.zone, self.unit, [p for p in self.points if p.end > now], self.source, self.attribution, self.fetched_at, dict(self.extra))

    def between(self, start: Optional[datetime], end: Optional[datetime]) -> "PriceSeries":
        pts = [p for p in self.points if (start is None or p.end > start) and (end is None or p.start < end)]
        return PriceSeries(self.zone, self.unit, pts, self.source, self.attribution, self.fetched_at, dict(self.extra))

    def to_dict(self) -> dict:
        return {
            "zone": self.zone,
            "unit": self.unit,
            "source": self.source,
            "attribution": self.attribution,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "points": [{"start": p.start.isoformat(), "end": p.end.isoformat(), "price": p.price} for p in self.points],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PriceSeries":
        pts = [PricePoint(_parse_iso(x["start"]), _parse_iso(x["end"]), float(x["price"])) for x in d["points"]]
        fetched = _parse_iso(d["fetched_at"]) if d.get("fetched_at") else None
        return cls(d["zone"], d["unit"], pts, d.get("source", ""), d.get("attribution", ""), fetched)


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class Window:
    start: datetime
    end: datetime
    avg_price: float           # time-weighted average over the window
    cost_units: float          # avg_price * hours  (i.e. price for 1 kW running the whole window)
    points: List[PricePoint]

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "avg_price": round(self.avg_price, 4), "minutes": self.minutes}


def _window_avg(points: Sequence[PricePoint], start: datetime, end: datetime) -> Optional[float]:
    """Time-weighted average price between start and end; None if the series does not cover it."""
    total = 0.0
    covered = 0.0
    for p in points:
        s = max(p.start, start)
        e = min(p.end, end)
        if e > s:
            m = (e - s).total_seconds() / 60.0
            total += p.price * m
            covered += m
    need = (end - start).total_seconds() / 60.0
    if covered + 1e-6 < need:
        return None
    return total / covered


def find_windows(
    series: PriceSeries,
    duration: timedelta,
    not_before: Optional[datetime] = None,
    not_after: Optional[datetime] = None,
    step: Optional[timedelta] = None,
    top: int = 3,
    min_gap: Optional[timedelta] = None,
) -> List[Window]:
    """Return the `top` cheapest contiguous windows of `duration`, sorted cheapest first.

    Candidate start times are every `step` (default: the series' slot length, min 5 min) from
    `not_before` (default: first point) such that the window ends by `not_after` (default: last point).
    Windows overlapping an already-chosen better window by more than `min_gap` are skipped so the
    alternatives are actually different times.
    """
    pts = series.points
    if not pts or duration <= timedelta(0):
        return []
    first_start, last_end = pts[0].start, pts[-1].end
    lo = max(not_before, first_start) if not_before else first_start
    hi = min(not_after, last_end) if not_after else last_end
    if step is None:
        slot = min(p.minutes for p in pts)
        step = timedelta(minutes=max(5.0, min(slot, 60.0)))
    # Align candidates to slot boundaries after `lo`.
    candidates: List[datetime] = []
    t = lo
    # snap to the next slot boundary if lo falls mid-slot (keeps windows aligned with price changes),
    # but also consider `lo` itself (start right now).
    candidates.append(lo)
    for p in pts:
        if p.start > lo and p.start + duration <= hi:
            candidates.append(p.start)
    # also fine-grained steps if step is smaller than slot
    if step < timedelta(minutes=min(p.minutes for p in pts)):
        t = lo
        while t + duration <= hi:
            candidates.append(t)
            t += step
    candidates = sorted(set(c for c in candidates if c + duration <= hi))
    scored = []
    for c in candidates:
        avg = _window_avg(pts, c, c + duration)
        if avg is None:
            continue
        scored.append((avg, c))
    scored.sort(key=lambda x: (x[0], x[1]))
    chosen: List[Window] = []
    gap = min_gap if min_gap is not None else max(timedelta(minutes=30), duration / 2)
    for avg, c in scored:
        if any(abs((c - w.start)) < gap for w in chosen):
            continue
        end = c + duration
        inside = [p for p in pts if p.end > c and p.start < end]
        chosen.append(Window(c, end, avg, avg * duration.total_seconds() / 3600.0, inside))
        if len(chosen) >= top:
            break
    return chosen


def parse_duration(text: str) -> timedelta:
    """'90m', '1h30m', '2h', '45min', '1.5h', '3600s', '2d' -> timedelta."""
    import re

    s = text.strip().lower().replace(" ", "")
    if not s:
        raise ValueError("empty duration")
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return timedelta(minutes=float(s))
    total = 0.0
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)(d|h|m|min|mins|s|sec)", s):
        n = float(num)
        if unit == "d":
            total += n * 1440
        elif unit == "h":
            total += n * 60
        elif unit in ("m", "min", "mins"):
            total += n
        else:
            total += n / 60
    if total <= 0 or not re.fullmatch(r"(\d+(\.\d+)?(d|h|m|min|mins|s|sec))+", s):
        raise ValueError("cannot parse duration %r (try 90m, 1h30m, 2h)" % text)
    return timedelta(minutes=total)


def parse_clock(text: str, now: datetime) -> datetime:
    """'07:00' -> next occurrence of 07:00 local time (>= now); 'HH:MM' or 'HH'."""
    s = text.strip()
    if ":" in s:
        hh, mm = s.split(":", 1)
    else:
        hh, mm = s, "0"
    local_now = now.astimezone()
    cand = local_now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if cand <= local_now:
        cand += timedelta(days=1)
    return cand.astimezone(timezone.utc)


def nan_safe(x: float) -> float:
    return 0.0 if math.isnan(x) else x
