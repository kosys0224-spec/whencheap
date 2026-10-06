# Changelog

All notable changes to whencheap are documented here ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/), [SemVer](https://semver.org/)).

## [0.1.0] - 2026-10-06

Initial public release.

### Added
- `next`, `run`, `wait`, `prices`, `zones`, `cache` commands.
- Cheapest-contiguous-window search with time-weighted averages over mixed 15/30/60-minute slots; `--by`, `--after`, `--within`, `--max-price`, `--max-wait`, `--kw`, `--top`.
- Keyless providers: Energy-Charts (45 EU zones), aWATTar (DE/AT), Octopus Agile (GB regions A-P), Energi Data Service (DK1/DK2), Elering (EE/FI/LV/LT), and static time-of-use tariff files (`tou:plan.json`).
- 30-minute on-disk cache honouring provider rate limits; attribution printed with every result.
- `--json` everywhere, `--prices-file` for offline/reproducible runs, `--tz` display time zone.
- 22 offline unit tests with recorded API responses; real two-day DE-LU sample in `examples/`.

[0.1.0]: https://github.com/kosys0224-spec/whencheap/releases/tag/v0.1.0
