"""Terminal rendering: price bars, window summary, colours."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .core import PriceSeries, Window

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
BG_GREEN = "\033[42;30m"


def _utf8_stdout() -> bool:
    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "utf" in enc


def glyphs() -> dict:
    """Unicode bars/markers when the terminal can show them, plain ASCII otherwise (e.g. Windows cp1252)."""
    if _utf8_stdout():
        return {"bar": "\u2588", "win": "\u25b6", "now": "\u00b7"}
    return {"bar": "#", "win": ">", "now": "*"}


def use_color(force: bool = False, disable: bool = False) -> bool:
    if disable or os.environ.get("NO_COLOR"):
        return False
    if force or os.environ.get("FORCE_COLOR"):
        return True
    try:
        return sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
    except Exception:
        return False


def c(code: str, s: str, on: bool) -> str:
    return "%s%s%s" % (code, s, RESET) if on else s


def fmt_price(v: float, unit: str) -> str:
    if abs(v) >= 100:
        return "%.0f %s" % (v, unit)
    return "%.2f %s" % (v, unit)


_MAJOR = {"ct/kWh": ("\u20ac", 100.0), "p/kWh": ("\u00a3", 100.0), "\u00f8re/kWh": ("DKK ", 100.0)}


def fmt_cost(amount: float, unit: str) -> str:
    """Cost for energy priced in `unit`: 185 ct -> '\u20ac1.85'; 12 p -> '\u00a30.12'; other units verbatim."""
    sym, div = _MAJOR.get(unit, (None, 1.0))
    if sym:
        return "%s%.2f" % (sym, amount / div)
    base = unit.replace("/kWh", "").strip()
    return "%.0f %s" % (amount, base) if abs(amount) >= 100 else "%.2f %s" % (amount, base)


def fmt_time(dt: datetime, tz=None) -> str:
    loc = dt.astimezone(tz) if tz else dt.astimezone()
    return loc.strftime("%H:%M")


def fmt_day(dt: datetime, now: datetime, tz=None) -> str:
    loc = dt.astimezone(tz) if tz else dt.astimezone()
    today = (now.astimezone(tz) if tz else now.astimezone()).date()
    d = loc.date()
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    if d == today - timedelta(days=1):
        return "yesterday"
    return loc.strftime("%a %d %b")


def fmt_delta(td: timedelta) -> str:
    secs = int(td.total_seconds())
    if secs < 0:
        return "now"
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h and m:
        return "%dh %02dm" % (h, m)
    if h:
        return "%dh" % h
    return "%dm" % m


def bar_chart(series: PriceSeries, now: datetime, highlight: Optional[Window] = None, color: bool = True,
              width: int = 40, tz=None, hourly: bool = True, limit_hours: Optional[int] = None) -> List[str]:
    """One line per hour (or per slot): time, bar, price. Cheapest third green, dearest third red."""
    pts = series.points
    if not pts:
        return ["(no prices)"]
    rows = []
    if hourly:
        # merge slots into hourly averages for readability
        buckets = {}
        for p in pts:
            key = p.start.astimezone(tz) if tz else p.start.astimezone()
            key = key.replace(minute=0, second=0, microsecond=0)
            buckets.setdefault(key, []).append(p)
        for key in sorted(buckets):
            group = buckets[key]
            mins = sum(g.minutes for g in group)
            avg = sum(g.price * g.minutes for g in group) / mins
            rows.append((key, group[0].start, group[-1].end, avg))
    else:
        for p in pts:
            rows.append((p.start.astimezone(tz) if tz else p.start.astimezone(), p.start, p.end, p.price))
    prices = [r[3] for r in rows]
    if limit_hours:
        rows = rows[:limit_hours]
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or 1.0
    sorted_p = sorted(prices)
    t1 = sorted_p[len(sorted_p) // 3]
    t2 = sorted_p[(2 * len(sorted_p)) // 3]
    out = []
    last_day = None
    for local, st, en, price in rows:
        day = local.date()
        if day != last_day:
            out.append(c(BOLD, "  %s %s" % (fmt_day(st, now, tz), local.strftime("%d %b")), color))
            last_day = day
        n = max(1, int(round((price - lo) / span * width)))
        colour = GREEN if price <= t1 else (RED if price >= t2 else YELLOW)
        g = glyphs()
        bar = g["bar"] * n
        is_now = st <= now < en
        in_win = highlight is not None and st < highlight.end and en > highlight.start
        marker = g["win"] if in_win else (" " if not is_now else g["now"])
        label = local.strftime("%H:%M")
        line = "%s %s %s %s" % (c(DIM, label, color) if not in_win else c(BOLD, label, color), marker, c(colour, bar, color), c(DIM, fmt_price(price, series.unit), color))
        if is_now:
            line += c(DIM, "  <- now", color)
        out.append(line)
    return out


def window_summary(series: PriceSeries, win: Window, now: datetime, color: bool, tz=None, alternatives: Optional[List[Window]] = None, kw: Optional[float] = None) -> List[str]:
    out = []
    starts_in = win.start - now
    avg_all = series.future(now).average()
    now_price = series.price_at(now)
    dur = fmt_delta(win.end - win.start)
    head = "%s %s %s-%s %s" % (c(BG_GREEN, " CHEAPEST %s " % dur, color), fmt_day(win.start, now, tz), fmt_time(win.start, tz), fmt_time(win.end, tz), c(DIM, "(%s)" % ("starts in " + fmt_delta(starts_in) if starts_in > timedelta(0) else "already running"), color))
    out.append(head)
    out.append("  average %s" % c(BOLD, fmt_price(win.avg_price, series.unit), color)
               + c(DIM, "  vs %s upcoming average" % fmt_price(avg_all, series.unit), color)
               + (c(DIM, ", %s right now" % fmt_price(now_price, series.unit), color) if now_price is not None else ""))
    if now_price is not None and now_price > 0:
        saving = (1 - win.avg_price / now_price) * 100
        if saving > 0.5:
            out.append("  " + c(GREEN, "%.0f%% cheaper than starting now" % saving, color))
        elif saving < -0.5:
            out.append("  " + c(YELLOW, "now is already the cheapest time (%.0f%% below the best later window)" % (-saving), color))
    if kw:
        hours = win.minutes / 60.0
        cost = win.avg_price * kw * hours
        cost_now = (now_price or 0) * kw * hours
        out.append("  %.1f kW for %s: %s" % (kw, dur, c(BOLD, fmt_cost(cost, series.unit), color))
                   + (c(DIM, " (vs %s if started now)" % fmt_cost(cost_now, series.unit), color) if now_price is not None else ""))
    if alternatives:
        alts = [w for w in alternatives if w.start != win.start][:3]
        if alts:
            out.append(c(DIM, "  also cheap: " + "; ".join("%s %s-%s (%s)" % (fmt_day(w.start, now, tz), fmt_time(w.start, tz), fmt_time(w.end, tz), fmt_price(w.avg_price, series.unit)) for w in alts), color))
    return out
