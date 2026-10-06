"""whencheap tests - all offline (recorded API responses in tests/fixtures). Run: python -m unittest discover -s tests -v"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
FIX = Path(__file__).resolve().parent / "fixtures"

from whencheap import cache  # noqa: E402
from whencheap.cli import main  # noqa: E402
from whencheap.core import PricePoint, PriceSeries, find_windows, parse_clock, parse_duration  # noqa: E402
from whencheap.providers import ProviderError, all_providers, resolve  # noqa: E402
from whencheap.providers.awattar import Awattar  # noqa: E402
from whencheap.providers.elering import Elering  # noqa: E402
from whencheap.providers.energidata import EnergiData  # noqa: E402
from whencheap.providers.energycharts import EnergyCharts  # noqa: E402
from whencheap.providers.octopus import OctopusAgile  # noqa: E402
from whencheap.providers.tou import TimeOfUse  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 10, 6, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 8, 0, 0, tzinfo=UTC)
SAMPLE = str(ROOT / "examples" / "sample-prices-DE-LU.json")


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def fake_fetcher(name, record=None):
    def f(url):
        if record is not None:
            record.append(url)
        return fx(name)

    return f


def hourly(prices, start=T0):
    pts = []
    for i, p in enumerate(prices):
        s = start + timedelta(hours=i)
        pts.append(PricePoint(s, s + timedelta(hours=1), float(p)))
    return PriceSeries("TEST", "ct/kWh", pts, "test")


class TestCore(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(parse_duration("90m"), timedelta(minutes=90))
        self.assertEqual(parse_duration("1h30m"), timedelta(minutes=90))
        self.assertEqual(parse_duration("2h"), timedelta(hours=2))
        self.assertEqual(parse_duration("1.5h"), timedelta(minutes=90))
        self.assertEqual(parse_duration("45"), timedelta(minutes=45))
        self.assertEqual(parse_duration("1d"), timedelta(days=1))
        for bad in ("", "abc", "0m", "2x"):
            with self.assertRaises(ValueError):
                parse_duration(bad)

    def test_parse_clock_next_occurrence(self):
        now = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
        later = parse_clock("12:00", now)
        earlier = parse_clock("09:00", now)
        self.assertGreater(later, now)
        self.assertGreater(earlier, now)
        self.assertLess(earlier - now, timedelta(days=1))

    def test_find_window_picks_cheapest_contiguous(self):
        s = hourly([30, 20, 10, 10, 25, 5, 40, 40])
        wins = find_windows(s, timedelta(hours=2), top=3)
        self.assertEqual(wins[0].start, T0 + timedelta(hours=2))  # 10,10 -> avg 10
        self.assertAlmostEqual(wins[0].avg_price, 10.0)
        self.assertEqual(len(wins), 3)
        # alternatives must not overlap heavily
        starts = [w.start for w in wins]
        self.assertEqual(len(set(starts)), 3)

    def test_find_window_respects_bounds(self):
        s = hourly([1, 1, 1, 50, 50, 50, 2, 2])
        wins = find_windows(s, timedelta(hours=2), not_before=T0 + timedelta(hours=3), top=1)
        self.assertEqual(wins[0].start, T0 + timedelta(hours=6))
        wins = find_windows(s, timedelta(hours=2), not_after=T0 + timedelta(hours=5), top=1)
        self.assertEqual(wins[0].start, T0)
        self.assertEqual(find_windows(s, timedelta(hours=9)), [])  # longer than data

    def test_window_can_start_mid_slot_now(self):
        s = hourly([10, 10, 50, 50])
        now = T0 + timedelta(minutes=20)
        wins = find_windows(s.future(now), timedelta(hours=1), not_before=now, top=1)
        self.assertEqual(wins[0].start, now)
        self.assertAlmostEqual(wins[0].avg_price, 10.0)

    def test_variable_slot_lengths(self):
        pts = [PricePoint(T0, T0 + timedelta(minutes=15), 10.0), PricePoint(T0 + timedelta(minutes=15), T0 + timedelta(minutes=60), 20.0),
               PricePoint(T0 + timedelta(minutes=60), T0 + timedelta(minutes=120), 5.0)]
        s = PriceSeries("X", "ct/kWh", pts)
        self.assertAlmostEqual(s.average(), (10 * 15 + 20 * 45 + 5 * 60) / 120)
        wins = find_windows(s, timedelta(minutes=30), top=1)
        self.assertEqual(wins[0].start, T0 + timedelta(minutes=60))

    def test_series_roundtrip(self):
        s = hourly([1, 2, 3])
        s2 = PriceSeries.from_dict(json.loads(json.dumps(s.to_dict())))
        self.assertEqual([p.price for p in s2.points], [1, 2, 3])
        self.assertEqual(s2.points[0].start, T0)


class TestProviders(unittest.TestCase):
    def test_energycharts(self):
        urls = []
        s = EnergyCharts(fake_fetcher("energycharts_DE-LU.json", urls)).fetch("de-lu", T0, T2)
        self.assertEqual(s.zone, "DE-LU")
        self.assertEqual(s.unit, "ct/kWh")
        self.assertEqual(len(s), 192)
        self.assertAlmostEqual(s.points[0].price, 16.055)  # 160.55 EUR/MWh
        self.assertEqual(s.points[0].minutes, 15)
        self.assertIn("bzn=DE-LU", urls[0])
        self.assertIn("CC BY", s.attribution)
        self.assertTrue(s.extra["open_data"])

    def test_awattar(self):
        s = Awattar(fake_fetcher("awattar_DE.json")).fetch("DE", T0, T2)
        self.assertEqual(len(s), 4)
        self.assertAlmostEqual(s.points[0].price, 24.98)
        self.assertEqual(s.points[0].minutes, 60)

    def test_octopus_sorted_and_pence(self):
        urls = []
        s = OctopusAgile(fake_fetcher("octopus_GB-C.json", urls)).fetch("GB-C", T0, T2)
        self.assertEqual(s.unit, "p/kWh")
        self.assertEqual([p.price for p in s.points], [9.9, 12.1, 24.84, 21.6])  # re-sorted ascending by time
        self.assertIn("E-1R-AGILE-24-10-01-C", urls[0])
        self.assertEqual(s.extra["region"], "London")

    def test_energidata(self):
        s = EnergiData(fake_fetcher("energidata_DK1.json")).fetch("DK1", T0, T2)
        self.assertEqual(s.unit, "øre/kWh")
        self.assertAlmostEqual(s.points[0].price, 86.6099359)
        self.assertEqual(s.points[0].start, datetime(2026, 10, 6, 19, tzinfo=UTC))

    def test_elering(self):
        s = Elering(fake_fetcher("elering_EE.json")).fetch("EE", T0, T2)
        self.assertEqual([p.price for p in s.points], [9.55, 8.025, 6.0])
        self.assertEqual(s.points[-1].minutes, 60)
        with self.assertRaises(ProviderError):
            Elering(fake_fetcher("elering_EE.json")).fetch("LV", T0, T2)

    def test_tou(self):
        s = TimeOfUse().fetch(str(ROOT / "examples" / "tou-example.json"), T0, T0 + timedelta(days=2))
        self.assertEqual(s.unit, "KRW/kWh")
        # 2026-10-06 is a Tuesday. 11:00 Seoul = 02:00 UTC -> peak 196
        self.assertEqual(s.price_at(datetime(2026, 10, 6, 2, 0, tzinfo=UTC)), 196.0)
        # 23:00 Seoul = 14:00 UTC -> off-peak 86
        self.assertEqual(s.price_at(datetime(2026, 10, 6, 14, 0, tzinfo=UTC)), 86.0)
        self.assertLess(len(s), 50)  # merged slots

    def test_resolve(self):
        p, z = resolve("fr")
        self.assertEqual((p.id, z), ("energycharts", "FR"))
        p, z = resolve("awattar:at")
        self.assertEqual((p.id, z), ("awattar", "AT"))
        p, z = resolve("GB-C")
        self.assertEqual(p.id, "octopus")
        p, z = resolve("energidata:DK2")
        self.assertEqual(p.id, "energidata")
        p, z = resolve("tou:/x/plan.json")
        self.assertEqual(p.id, "tou")
        with self.assertRaises(ProviderError):
            resolve("MARS")
        with self.assertRaises(ProviderError):
            resolve("awattar:FR")
        ids = {p.id for p in all_providers()}
        self.assertEqual(ids, {"energycharts", "awattar", "octopus", "energidata", "elering", "tou"})

    def test_bad_responses(self):
        with self.assertRaises(ProviderError):
            EnergyCharts(lambda u: {"oops": 1}).fetch("FR", T0, T2)
        with self.assertRaises(ProviderError):
            Awattar(lambda u: []).fetch("DE", T0, T2)


class TestCache(unittest.TestCase):
    def test_cache_roundtrip_and_ttl(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["WHENCHEAP_CACHE_DIR"] = d
            try:
                s = hourly([1, 2, 3])
                cache.save(s)
                got = cache.load("test", "TEST")
                self.assertIsNotNone(got)
                self.assertEqual(len(got), 3)
                self.assertIsNone(cache.load("test", "TEST", needed_until=T0 + timedelta(days=5)))
                self.assertIsNone(cache.load("test", "TEST", ttl=-1))
                self.assertEqual(cache.clear(), 1)
            finally:
                del os.environ["WHENCHEAP_CACHE_DIR"]


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_next_text_and_json(self):
        code, out, _ = self.run_cli("next", "--prices-file", SAMPLE, "-d", "2h", "--now", "2026-10-06T14:20:00Z", "--no-color", "--kw", "7.4", "--tz", "Europe/Berlin")
        self.assertEqual(code, 0)
        self.assertIn("CHEAPEST 2h", out)
        self.assertIn("12:15-14:15", out)
        self.assertIn("€", out)
        code, out, _ = self.run_cli("next", "--prices-file", SAMPLE, "-d", "2h", "--now", "2026-10-06T14:20:00Z", "--json")
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["best"]["start"], "2026-10-07T10:15:00+00:00")
        self.assertAlmostEqual(d["best"]["avg_price"], 12.5052, places=3)
        self.assertEqual(len(d["alternatives"]), 2)

    def test_next_constraints(self):
        code, out, _ = self.run_cli("next", "--prices-file", SAMPLE, "-d", "1h", "--by", "07:00", "--now", "2026-10-06T20:00:00Z", "--json", "--tz", "UTC")
        d = json.loads(out)
        self.assertEqual(code, 0)
        self.assertLessEqual(d["best"]["end"], "2026-10-07T07:00:00+00:00")
        code, out, _ = self.run_cli("next", "--prices-file", SAMPLE, "-d", "1h", "--within", "30m", "--now", "2026-10-06T20:00:00Z", "--no-color")
        self.assertEqual(code, 1)
        self.assertIn("No window", out)
        code, _, _ = self.run_cli("next", "--prices-file", SAMPLE, "-d", "1h", "--max-price", "5", "--now", "2026-10-06T20:00:00Z", "--json")
        self.assertEqual(code, 1)

    def test_prices(self):
        code, out, _ = self.run_cli("prices", "--prices-file", SAMPLE, "--now", "2026-10-06T14:20:00Z", "--no-color", "--tz", "Europe/Berlin")
        self.assertEqual(code, 0)
        self.assertIn("█", out)
        self.assertIn("<- now", out)
        code, out, _ = self.run_cli("prices", "--prices-file", SAMPLE, "--json")
        self.assertEqual(json.loads(out)["zone"], "DE-LU")

    def test_run_dry_and_wait_limits(self):
        code, out, err = self.run_cli("run", "--prices-file", SAMPLE, "-d", "1h", "--now", "2026-10-06T20:00:00Z", "--dry-run", "--no-color", "--", "echo", "hi")
        self.assertEqual(code, 0)
        self.assertIn("would wait", err)
        code, _, err = self.run_cli("run", "--prices-file", SAMPLE, "-d", "1h", "--now", "2026-10-06T20:00:00Z", "--max-wait", "1m", "--", "echo", "hi")
        self.assertEqual(code, 1)
        self.assertIn("max-wait", err)
        code, _, err = self.run_cli("run", "--prices-file", SAMPLE, "-d", "1h", "--now", "2026-10-06T20:00:00Z")
        self.assertEqual(code, 2)

    def test_tou_zone_and_zones_listing(self):
        code, out, _ = self.run_cli("next", "-z", "tou:" + str(ROOT / "examples" / "tou-example.json"), "-d", "3h", "--now", "2026-10-06T05:00:00Z", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["unit"], "KRW/kWh")
        code, out, _ = self.run_cli("zones")
        self.assertEqual(code, 0)
        self.assertIn("GB-A", out)
        code, out, _ = self.run_cli("zones", "--json")
        self.assertEqual(len(json.loads(out)), 6)

    def test_errors(self):
        code, _, err = self.run_cli("next", "-d", "1h", "-z", "MARS")
        self.assertEqual(code, 2)
        self.assertIn("unknown zone", err)
        code, _, err = self.run_cli("next", "--prices-file", SAMPLE, "-d", "nonsense")
        self.assertEqual(code, 2)
        code, _, _ = self.run_cli()
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
