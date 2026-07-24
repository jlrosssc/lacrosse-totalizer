# LaCrosse Rain Totalizer

A Home Assistant custom integration that produces **accurate** rainfall
totals from a LaCrosse View rain gauge — hourly, today (calendar day),
rolling 24 hours, this month, this year, and rolling 3 days.

## The problem this solves

Home Assistant's built-in `lacrosse_view` integration polls LaCrosse's
"current value" endpoint every 60 seconds. That endpoint reflects whatever
LaCrosse's cloud happens to be reporting *right now* — it is not a ledger.
During bursts of heavy rain, multiple gauge tips can happen between polls
and simply never appear in that value; depending on how fast the upstream
value refreshes relative to your poll interval, the same tip can also get
read (and summed) more than once by any downstream `utility_meter`/`daily`
helper built on top of it. Either way, daily/monthly/yearly totals derived
from that snapshot value drift from reality over time — sometimes under,
sometimes over.

LaCrosse's cloud actually stores every individual gauge tip permanently,
each with its own timestamp (`aggregate=ai.ticks.1` in their API). This
integration queries that tick-history endpoint instead of the live
snapshot: each update cycle asks "what tipped between the last checkpoint
and now," inserts any new ticks into a small local database, and then
computes every totalizer window directly from that authoritative log with
plain SQL date-range sums. Because every tip is stored exactly once with an
exact timestamp, and because each metric is fully recomputed from source on
every update rather than accumulated incrementally, the numbers can't drift
and match your LaCrosse app's own totals.

## What you get

Six sensors per configured rain gauge, each independently and exactly
computed from the tick log:

| Entity | Resets |
|---|---|
| Rain (current hour) | top of the clock hour |
| Rain (today, calendar day) | local midnight |
| Rain (rolling 24 hours) | rolling window, matches the LaCrosse app's "24 hour" total |
| Rain (this month) | 1st of the month |
| Rain (this year) | January 1 |
| Rain (rolling 3 days) | rolling window |

On first setup, the integration does a small 25-hour backfill immediately
so sensors have sensible values right away, then kicks off a one-time
background backfill of the full current year (in 14-day chunks, paced to
avoid overloading LaCrosse's API) so month-to-date and year-to-date are
correct from day one instead of slowly rebuilding from zero.

This integration runs **alongside** the built-in `lacrosse_view`
integration — it doesn't replace or modify it. Point your dashboards,
automations, and anything like Smart Irrigation's precipitation mapping at
these new sensors instead of (or as well as) the originals.

## Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories → add
   `https://github.com/jlrosssc/lacrosse-totalizer` as an Integration.
2. Install "LaCrosse Rain Totalizer", then restart Home Assistant.

### Manual

Copy `custom_components/lacrosse_totalizer` into your Home Assistant
`config/custom_components/` directory, then restart Home Assistant.

## Configuration

Settings → Devices & Services → Add Integration → "LaCrosse Rain
Totalizer". You'll be asked for your LaCrosse View account email/password,
then to pick the location and the specific rain gauge (any device exposing
a `Rain` field). Repeat for additional gauges/locations — each gets its own
config entry, own device, and own local database.

To re-run the full year backfill later (e.g. after a long outage), open the
integration's options and check "Re-run the full year-to-date backfill".

## Notes

- Polls every 5 minutes by default — a small addition on top of whatever
  polling interval the built-in integration already uses, not a
  replacement for it.
- Each config entry keeps its own SQLite tick log under
  `config/lacrosse_totalizer/<entry_id>.sqlite`. This is the source of
  truth the sensors are computed from; nothing is discarded, so any past
  window can be recomputed exactly if the logic ever needs to change.
- Built on top of the excellent [`lacrosse-view`](https://github.com/IceBotYT/lacrosse_view)
  Python library (MIT licensed), the same library the built-in HA
  integration uses.

## License

MIT — see [LICENSE](LICENSE).
