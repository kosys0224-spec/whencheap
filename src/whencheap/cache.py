"""Tiny on-disk cache so repeated calls (cron, scripts) do not hit provider rate limits."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .core import PriceSeries

DEFAULT_TTL = 30 * 60  # seconds


def cache_dir() -> Path:
    env = os.environ.get("WHENCHEAP_CACHE_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "whencheap"


def _key(provider: str, zone: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.\-]+", "_", "%s_%s" % (provider, zone))
    return safe + ".json"


def load(provider: str, zone: str, ttl: int = DEFAULT_TTL, needed_until: Optional[datetime] = None) -> Optional[PriceSeries]:
    """Return a cached series if it is fresh and (optionally) still covers `needed_until`."""
    path = cache_dir() / _key(provider, zone)
    try:
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > ttl:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        series = PriceSeries.from_dict(data)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if needed_until is not None:
        _, last_end = series.span()
        if last_end is None or last_end < needed_until:
            return None
    return series


def save(series: PriceSeries) -> None:
    try:
        d = cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (_key(series.source, series.zone) + ".tmp")
        tmp.write_text(json.dumps(series.to_dict()), encoding="utf-8")
        os.replace(tmp, d / _key(series.source, series.zone))
    except OSError:
        pass  # caching is best-effort


def clear() -> int:
    d = cache_dir()
    n = 0
    if d.exists():
        for f in d.glob("*.json"):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    return n


def tomorrow_end(now: datetime) -> datetime:
    """End of tomorrow in local time, as UTC - what we would like a series to cover."""
    local = now.astimezone()
    end_local = (local + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    return end_local.astimezone(timezone.utc)
