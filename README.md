# LaCrosse Rain Totalizer

A Home Assistant custom integration that produces **accurate** rainfall
totals and wind speed extremes from a LaCrosse View weather station —
hourly, today (calendar day), rolling 24 hours, this month, this year, and
rolling 3 days.

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

Six window sensors per configured field, each independently and exactly
computed from the tick log — rain is summed (each tick is a discrete
gauge-tip amount), wind speed is tracked as max **and** min (each tick is
an instantaneous reading, so a window's true peak/lull is the extreme of
the readings in it, not their sum):

| Window | Resets |
|---|---|
| Current hour | top of the clock hour |
| Today (calendar day) | local midnight |
| Rolling 24 hours | rolling window, matches the LaCrosse app's "24 hour" total |
| This month | 1st of the month |
| This year | January 1 |
| Rolling 3 days | rolling window |

Wind speed also gets a **current value** sensor that replays every new
tick as its own state update, in order — not a window aggregate, but the
real deduplicated reading sequence. This matters for anything that samples
a mapped entity's state history and averages it itself (Smart Irrigation's
`Windspeed` mapping, for example): a 60-second poll of the built-in
integration's live value can repeat a stale reading or miss a brief gust
between polls, which quietly skews that kind of average. Feeding it the
actual tick sequence instead removes that error at the source.

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
then to pick the location and the specific device, then which supported
fields to track (Rain, wind speed, or both — only fields your device
actually reports are offered). Repeat for additional devices/locations —
each gets its own config entry, own device, and own local database.

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

Licensed under the [GNU General Public License v3.0](LICENSE) — if you
distribute a modified version of this integration, GPLv3 requires that you
also make your modified source available under the same license.

    Copyright (C) 2026 Joe Ross

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

This project depends on (but does not bundle) the MIT-licensed
[`lacrosse-view`](https://github.com/IceBotYT/lacrosse_view) library,
installed automatically via `manifest.json` `requirements`. MIT is
permissive and compatible with GPLv3.
