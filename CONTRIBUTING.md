# Contributing to whencheap

## Adding a price provider (the most useful contribution)

One file in `src/whencheap/providers/`, ~30 lines:

```python
from datetime import datetime, timedelta, timezone
from ..core import PricePoint, PriceSeries
from . import Provider, ProviderError, register

@register
class MyTso(Provider):
    id = "mytso"                       # used as the zone prefix: mytso:ZONE
    name = "My TSO public API"
    unit = "ct/kWh"                    # per-kWh unit after conversion
    attribution = "Price data: ..."    # printed with every result - respect the source's licence
    docs = "https://..."
    zones = ("ZONE1", "ZONE2")
    description = "one line for `whencheap zones`"

    def fetch(self, zone, start, end):
        data = self._fetch_json("https://.../prices?zone=%s" % self.canonical(zone))   # keyless HTTPS GET
        pts = [PricePoint(start_utc, end_utc, price_per_kwh) for ... in data]
        return self._series(zone, pts)
```

Rules:
- **Keyless, public, documented** APIs only. If a token is required the provider must work without it for at least a default zone, or go in a separate "token providers" PR with a clear note.
- Convert to a per-kWh unit (EUR/MWh ÷ 10 → ct/kWh). Timestamps must be timezone-aware UTC.
- Register the import in `providers/__init__.py:all_providers`.
- Add a **recorded response** to `tests/fixtures/` and a test in `tests/test_whencheap.py` that parses it (no network in tests).
- Add the provider to the README table.

## Layout

```
src/whencheap/core.py        PriceSeries, Window, find_windows(), duration/clock parsing  (pure, no I/O)
src/whencheap/providers/     one file per data source + registry/resolve()
src/whencheap/cache.py       on-disk cache
src/whencheap/render.py      bar chart and summary rendering
src/whencheap/cli.py         argparse commands
tests/                       offline unittest suite + fixtures
examples/                    real sample prices, TOU example
scripts/make_screenshot.py   regenerates docs/demo.png (needs Playwright)
```

## Running

```bash
pip install -e .
python -m unittest discover -s tests -v
whencheap next --prices-file examples/sample-prices-DE-LU.json -d 2h --now 2026-10-06T17:20:00Z
```

Standard library only; no new runtime dependencies. Lines ≤ 160. One provider or fix per PR.
