# Time-of-use tariff file format

Use `--zone tou:/path/to/plan.json` (or just `--zone plan.json`). No network is used.

```json
{
  "name": "My utility TOU plan",
  "unit": "KRW/kWh",
  "timezone": "Asia/Seoul",
  "default": 120.0,
  "periods": [
    {"days": "mon-fri", "from": "10:00", "to": "12:00", "price": 196.0, "label": "peak"},
    {"days": "mon-fri", "from": "13:00", "to": "17:00", "price": 196.0, "label": "peak"},
    {"days": "mon-fri", "from": "08:00", "to": "22:00", "price": 134.0, "label": "mid"},
    {"days": "sat",     "from": "08:00", "to": "22:00", "price": 134.0, "label": "mid"},
    {"days": "all",     "from": "22:00", "to": "08:00", "price": 86.0,  "label": "off-peak"},
    {"months": "6-8", "days": "mon-fri", "from": "14:00", "to": "17:00", "price": 250.0, "label": "summer peak"}
  ]
}
```

| Field | Meaning |
|---|---|
| `name` | shown as the zone name |
| `unit` | any string, e.g. `KRW/kWh`, `ct/kWh`, `c/kWh`, `USD/kWh`. Units ending in `/kWh` get a cost line with `--kw` |
| `timezone` | IANA name (`Asia/Seoul`, `America/Los_Angeles`). Omit for the machine's local time. Windows: `pip install tzdata` |
| `default` | price when no period matches |
| `periods[].days` | `all`, `weekdays`, `weekends`, a name (`sat`), a range (`mon-fri`, `fri-mon` wraps) or a list (`mon,wed,fri`) |
| `periods[].months` | optional: `6-8`, `11-2` (wraps), `12`, `all` |
| `periods[].from` / `to` | `HH:MM`, local to `timezone`. `to` earlier than `from` wraps past midnight. `to` is exclusive |
| `periods[].price` | number |
| `periods[].label` | optional, informational |

Periods are checked **in order; the first match wins**, so put the most specific (summer peak) first and the broad defaults last.

whencheap expands the plan into 15-minute slots for today and tomorrow, merges equal neighbours, and then treats it like any other price series — so `next`, `run`, `wait`, `--by`, `--kw` all work the same.

Tip: keep one file per contract in a dotfiles repo and point `WHENCHEAP_ZONE=tou:$HOME/.config/whencheap/home.json` at it.
