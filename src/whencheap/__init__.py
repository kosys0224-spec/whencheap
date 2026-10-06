"""whencheap - find the cheapest hours to run things, from public day-ahead electricity prices."""

__version__ = "0.1.0"

from .core import PricePoint, PriceSeries, Window, find_windows  # noqa: E402,F401

__all__ = ["__version__", "PricePoint", "PriceSeries", "Window", "find_windows"]
