"""Command-line interface for whencheap."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from . import __version__, cache
from .core import PriceSeries, Window, find_windows, parse_clock, parse_duration
from .providers import ProviderError, all_providers, resolve
from .render import BOLD, DIM, GREEN, YELLOW, bar_chart, c, fmt_day, fmt_delta, fmt_price, fmt_time, use_color, window_summary

EXIT_OK = 0
EXIT_NO_WINDOW = 1
EXIT_ERROR = 2


def _tz(name: Optional[str]):
    if not name:
        return None
    from zoneinfo import ZoneInfo

    return ZoneInfo(name)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="whencheap",
        description="Find the cheapest hours to run things, from public day-ahead electricity prices (EU, GB) or your own time-of-use tariff.",
        epilog="Examples:\n"
               "  whencheap next --zone DE-LU --duration 2h\n"
               "  whencheap next -z GB-C -d 90m --by 07:00 --kw 7.4      # EV charging before the commute\n"
               "  whencheap run -z FR -d 3h -- ./backup.sh                 # wait for the cheapest 3h, then run\n"
               "  whencheap prices -z awattar:AT --tomorrow\n"
               "  whencheap next -z tou:examples/tou-example.json -d 1h\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version="whencheap %s" % __version__)
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    def common(sp):
        sp.add_argument("-z", "--zone", default=os.environ.get("WHENCHEAP_ZONE"), help="price zone, e.g. DE-LU, FR, GB-C, awattar:AT, energidata:DK1, tou:plan.json (env WHENCHEAP_ZONE)")
        sp.add_argument("--prices-file", metavar="FILE", help="read prices from a JSON file written by `whencheap prices --json` instead of the network")
        sp.add_argument("--tz", metavar="IANA", help="display timezone, e.g. Europe/Berlin (default: system local)")
        sp.add_argument("--no-cache", action="store_true", help="always fetch fresh prices")
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        sp.add_argument("--no-color", action="store_true")
        sp.add_argument("--color", action="store_true", help="force colours")
        sp.add_argument("--now", metavar="ISO", help=argparse.SUPPRESS)  # testing: pretend it is this time

    def window_args(sp):
        sp.add_argument("-d", "--duration", required=True, help="how long the job runs: 30m, 90m, 2h, 1h30m")
        sp.add_argument("--by", metavar="HH:MM", help="must finish by this local clock time (next occurrence)")
        sp.add_argument("--after", metavar="HH:MM", help="must not start before this local clock time")
        sp.add_argument("--within", metavar="DUR", help="must finish within this much time from now, e.g. 12h")
        sp.add_argument("--kw", type=float, help="load in kW, to print the cost of the window")
        sp.add_argument("--top", type=int, default=3, help="number of alternative windows to show (default 3)")
        sp.add_argument("--max-price", type=float, metavar="P", help="fail (exit 1) if the best window averages above P")

    n = sub.add_parser("next", help="show the cheapest window for a job of a given duration")
    common(n)
    window_args(n)
    n.add_argument("--no-chart", action="store_true", help="hide the price bar chart")

    pr = sub.add_parser("prices", help="show upcoming prices as a bar chart (or JSON)")
    common(pr)
    pr.add_argument("--tomorrow", action="store_true", help="only tomorrow")
    pr.add_argument("--slots", action="store_true", help="show every price slot instead of hourly averages")
    pr.add_argument("--hours", type=int, help="limit to the next N hours")

    r = sub.add_parser("run", help="wait until the cheapest window starts, then run a command")
    common(r)
    window_args(r)
    r.add_argument("--max-wait", metavar="DUR", help="give up (exit 1) if the window starts later than this, e.g. 8h")
    r.add_argument("--dry-run", action="store_true", help="print what would happen and exit")
    r.add_argument("command", nargs=argparse.REMAINDER, help="command to run (put -- before it)")

    w = sub.add_parser("wait", help="sleep until the cheapest window starts (for shell scripts)")
    common(w)
    window_args(w)
    w.add_argument("--max-wait", metavar="DUR")

    z = sub.add_parser("zones", help="list providers and zones")
    z.add_argument("--json", action="store_true")

    cc = sub.add_parser("cache", help="show or clear the on-disk price cache")
    cc.add_argument("--clear", action="store_true")
    return p


def _now(args) -> datetime:
    if getattr(args, "now", None):
        s = args.now
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def load_series(args, now: datetime) -> PriceSeries:
    if getattr(args, "prices_file", None):
        data = json.loads(Path(args.prices_file).read_text(encoding="utf-8"))
        return PriceSeries.from_dict(data)
    zone = getattr(args, "zone", None)
    if not zone:
        raise ProviderError("no zone given. Use --zone (or WHENCHEAP_ZONE), e.g. --zone DE-LU. `whencheap zones` lists them.")
    provider, z = resolve(zone)
    needed_until = cache.tomorrow_end(now)
    if not getattr(args, "no_cache", False) and provider.id != "tou":
        cached = cache.load(provider.id, z, needed_until=now + timedelta(hours=6))
        if cached is not None:
            return cached
    start = (now - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    series = provider.fetch(z, start, needed_until)
    if provider.id != "tou":
        cache.save(series)
    return series


def _window_bounds(args, now: datetime):
    not_before = now
    not_after = None
    if getattr(args, "after", None):
        not_before = max(now, parse_clock(args.after, now))
    if getattr(args, "by", None):
        not_after = parse_clock(args.by, now)
    if getattr(args, "within", None):
        lim = now + parse_duration(args.within)
        not_after = min(not_after, lim) if not_after else lim
    return not_before, not_after


def _best(args, series: PriceSeries, now: datetime) -> List[Window]:
    duration = parse_duration(args.duration)
    not_before, not_after = _window_bounds(args, now)
    fut = series.future(now)
    return find_windows(fut, duration, not_before=not_before, not_after=not_after, top=max(1, args.top))


def _print_attribution(series: PriceSeries, color: bool) -> None:
    if series.attribution:
        print(c(DIM, "  " + series.attribution, color))


def cmd_next(args) -> int:
    now = _now(args)
    color = use_color(args.color, args.no_color)
    tz = _tz(args.tz)
    series = load_series(args, now)
    wins = _best(args, series, now)
    if args.json:
        print(json.dumps({"zone": series.zone, "unit": series.unit, "source": series.source, "now": now.isoformat(),
                          "best": wins[0].to_dict() if wins else None, "alternatives": [w.to_dict() for w in wins[1:]],
                          "upcoming_average": round(series.future(now).average(), 4), "price_now": series.price_at(now),
                          "attribution": series.attribution}, indent=2))
        return EXIT_OK if wins and (args.max_price is None or wins[0].avg_price <= args.max_price) else EXIT_NO_WINDOW
    first, last = series.span()
    print(c(BOLD, "whencheap", color) + c(DIM, "  %s  prices known until %s %s" % (series.zone, fmt_day(last, now, tz), fmt_time(last, tz)), color))
    if not wins:
        print(c(YELLOW, "  No window of %s fits the constraints with the prices available." % args.duration, color))
        print(c(DIM, "  Day-ahead prices for tomorrow are usually published around 13:00 CET; try again later or relax --by/--within.", color))
        return EXIT_NO_WINDOW
    print()
    for line in window_summary(series, wins[0], now, color, tz, wins, args.kw):
        print(line)
    if not args.no_chart:
        print()
        for line in bar_chart(series.future(now), now, wins[0], color, tz=tz):
            print(line)
    print()
    _print_attribution(series, color)
    if args.max_price is not None and wins[0].avg_price > args.max_price:
        print(c(YELLOW, "  best window (%s) is above --max-price %s" % (fmt_price(wins[0].avg_price, series.unit), args.max_price), color))
        return EXIT_NO_WINDOW
    return EXIT_OK


def cmd_prices(args) -> int:
    now = _now(args)
    color = use_color(args.color, args.no_color)
    tz = _tz(args.tz)
    series = load_series(args, now)
    shown = series
    if args.tomorrow:
        local = now.astimezone(tz) if tz else now.astimezone()
        t0 = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        shown = series.between(t0.astimezone(timezone.utc), (t0 + timedelta(days=1)).astimezone(timezone.utc))
    else:
        shown = series.future(now)
    if args.json:
        d = series.to_dict() if not args.tomorrow else shown.to_dict()
        print(json.dumps(d, indent=2))
        return EXIT_OK
    if not shown.points:
        print(c(YELLOW, "no prices available for that period yet", color))
        return EXIT_NO_WINDOW
    mn, mx = shown.min_point(), shown.max_point()
    print(c(BOLD, "whencheap", color) + c(DIM, "  %s  %d slots, avg %s, min %s at %s %s, max %s at %s %s" % (
        series.zone, len(shown), fmt_price(shown.average(), series.unit), fmt_price(mn.price, series.unit), fmt_day(mn.start, now, tz), fmt_time(mn.start, tz),
        fmt_price(mx.price, series.unit), fmt_day(mx.start, now, tz), fmt_time(mx.start, tz)), color))
    for line in bar_chart(shown, now, None, color, tz=tz, hourly=not args.slots, limit_hours=args.hours):
        print(line)
    _print_attribution(series, color)
    return EXIT_OK


def _wait_until(start: datetime, now_fn, color: bool, quiet: bool = False) -> None:
    while True:
        now = now_fn()
        remaining = start - now
        if remaining.total_seconds() <= 0:
            return
        if not quiet:
            sys.stderr.write("\r" + c(DIM, "whencheap: waiting %s until %s ... " % (fmt_delta(remaining), fmt_time(start)), color))
            sys.stderr.flush()
        time.sleep(min(60.0, max(1.0, remaining.total_seconds())))


def cmd_run(args, run_command: bool) -> int:
    now = _now(args)
    color = use_color(args.color, args.no_color)
    series = load_series(args, now)
    wins = _best(args, series, now)
    cmd = [a for a in (getattr(args, "command", None) or []) if a != "--"]
    if run_command and not cmd:
        print("whencheap run: no command given. Usage: whencheap run -z ZONE -d 2h -- your-command args", file=sys.stderr)
        return EXIT_ERROR
    if not wins:
        print("whencheap: no window of %s fits the constraints; nothing to do." % args.duration, file=sys.stderr)
        return EXIT_NO_WINDOW
    win = wins[0]
    if args.max_price is not None and win.avg_price > args.max_price:
        print("whencheap: best window averages %s, above --max-price %s; not running." % (fmt_price(win.avg_price, series.unit), args.max_price), file=sys.stderr)
        return EXIT_NO_WINDOW
    if getattr(args, "max_wait", None) and win.start - now > parse_duration(args.max_wait):
        print("whencheap: cheapest window starts in %s, more than --max-wait %s; not running." % (fmt_delta(win.start - now), args.max_wait), file=sys.stderr)
        return EXIT_NO_WINDOW
    msg = "cheapest %s window: %s %s-%s, avg %s (starts in %s)" % (args.duration, fmt_day(win.start, now), fmt_time(win.start), fmt_time(win.end), fmt_price(win.avg_price, series.unit), fmt_delta(win.start - now))
    print(c(GREEN, "whencheap: " + msg, color), file=sys.stderr)
    if args.json:
        print(json.dumps({"window": win.to_dict(), "command": cmd}))
    if getattr(args, "dry_run", False):
        print("whencheap: dry run - would wait %s then run: %s" % (fmt_delta(win.start - now), " ".join(cmd)), file=sys.stderr)
        return EXIT_OK
    if args.now:  # test mode: never actually sleep
        return EXIT_OK
    try:
        _wait_until(win.start, lambda: datetime.now(timezone.utc), color)
    except KeyboardInterrupt:
        print("\nwhencheap: interrupted while waiting", file=sys.stderr)
        return EXIT_ERROR
    sys.stderr.write("\n")
    if not run_command:
        return EXIT_OK
    print(c(DIM, "whencheap: running %s" % " ".join(cmd), color), file=sys.stderr)
    try:
        return subprocess.call(cmd)
    except FileNotFoundError:
        print("whencheap: command not found: %s" % cmd[0], file=sys.stderr)
        return EXIT_ERROR


def cmd_zones(args) -> int:
    providers = all_providers()
    if args.json:
        print(json.dumps([{"id": p.id, "name": p.name, "unit": p.unit, "zones": list(p.zones), "docs": p.docs, "description": p.description} for p in providers], indent=2))
        return EXIT_OK
    color = use_color()
    for p in providers:
        print(c(BOLD, "%s" % p.id, color) + "  " + p.name + c(DIM, "  [%s]" % p.unit, color))
        print("  " + p.description)
        if p.zones:
            zs = list(p.zones)
            print("  zones: " + ", ".join(zs[:16]) + (", ... (%d total)" % len(zs) if len(zs) > 16 else ""))
            if p.id == "energycharts":
                print(c(DIM, "  use the zone name directly (e.g. --zone FR); other providers need a prefix (awattar:AT, energidata:DK1, elering:EE)", color))
        print()
    return EXIT_OK


def cmd_cache(args) -> int:
    if args.clear:
        print("removed %d cached file(s) from %s" % (cache.clear(), cache.cache_dir()))
        return EXIT_OK
    d = cache.cache_dir()
    files = sorted(d.glob("*.json")) if d.exists() else []
    print("cache dir: %s (%d file(s))" % (d, len(files)))
    for f in files:
        age = time.time() - f.stat().st_mtime
        print("  %-40s %5.0f min old" % (f.name, age / 60))
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return EXIT_ERROR
    try:
        if args.cmd == "next":
            return cmd_next(args)
        if args.cmd == "prices":
            return cmd_prices(args)
        if args.cmd == "run":
            return cmd_run(args, run_command=True)
        if args.cmd == "wait":
            return cmd_run(args, run_command=False)
        if args.cmd == "zones":
            return cmd_zones(args)
        if args.cmd == "cache":
            return cmd_cache(args)
    except ProviderError as exc:
        print("whencheap: %s" % exc, file=sys.stderr)
        return EXIT_ERROR
    except ValueError as exc:
        print("whencheap: %s" % exc, file=sys.stderr)
        return EXIT_ERROR
    except (OSError, json.JSONDecodeError) as exc:
        print("whencheap: %s" % exc, file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        return EXIT_ERROR
    except BrokenPipeError:  # e.g. `whencheap prices | head`
        try:
            sys.stdout.close()
        except Exception:
            pass
        return EXIT_OK
    return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
