"""Constants for the LaCrosse Rain Totalizer integration."""

DOMAIN = "lacrosse_totalizer"

CONF_LOCATION_ID = "location_id"
CONF_LOCATION_NAME = "location_name"
CONF_DEVICE_NAME = "device_name"
CONF_FIELDS = "fields"

FIELD_RAIN = "Rain"
FIELD_WIND_SPEED = "WindSpeed"

# Fields this integration knows how to turn into accurate totals/extremes.
# Wind heading is deliberately excluded: it's a circular quantity, so
# sum/max/min over a window don't mean anything useful the way they do for
# a rain amount or a wind speed reading.
SUPPORTED_FIELDS = [FIELD_RAIN, FIELD_WIND_SPEED]

# Which SQL aggregate(s) make sense for each field's tick values. Rain ticks
# are discrete gauge-tip amounts, so a window's total is their SUM. Wind
# speed ticks are instantaneous readings, so a window's true peak/lull is
# the MAX/MIN of the readings in it, not their sum.
FIELD_AGGREGATES = {
    FIELD_RAIN: ["sum"],
    FIELD_WIND_SPEED: ["max", "min"],
}

SQL_AGGREGATE_FUNCTIONS = {
    "sum": "SUM",
    "max": "MAX",
    "min": "MIN",
}

# Fields that also get a "current value" sensor which replays each new tick
# as its own state update (not just window aggregates). This matters for
# consumers like Smart Irrigation that sample a mapped entity's own state
# history and average it themselves -- feeding them the real, deduplicated
# tick sequence (instead of a 60-second snapshot poll that can repeat a
# stale reading or miss a brief gust) gives their own averaging genuinely
# better raw material. Rain doesn't need this: its consumers want a
# pre-summed total, not a raw sample stream.
FIELDS_WITH_CURRENT_SENSOR = [FIELD_WIND_SPEED]

SCAN_INTERVAL_MINUTES = 5
INITIAL_LOOKBACK_HOURS = 25
BACKFILL_CHUNK_DAYS = 14
BACKFILL_SLEEP_SECONDS = 1

# Time windows shared by every field/aggregate: (window key, SQL WHERE
# clause selecting ticks in this window).
WINDOWS = [
    (
        "hourly",
        "strftime('%Y-%m-%d %H', ts, 'unixepoch', 'localtime') = "
        "strftime('%Y-%m-%d %H', 'now', 'localtime')",
    ),
    (
        "calendar_daily",
        "date(ts, 'unixepoch', 'localtime') = date('now', 'localtime')",
    ),
    (
        "rolling_24h",
        "ts >= strftime('%s', 'now') - 86400",
    ),
    (
        "monthly",
        "strftime('%Y-%m', ts, 'unixepoch', 'localtime') = "
        "strftime('%Y-%m', 'now', 'localtime')",
    ),
    (
        "yearly",
        "strftime('%Y', ts, 'unixepoch', 'localtime') = strftime('%Y', 'now', 'localtime')",
    ),
    (
        "rolling_3day",
        "ts >= strftime('%s', 'now') - 3 * 86400",
    ),
]


def build_metrics(fields: list[str]) -> list[dict]:
    """Build the full metric list (one entry per field/aggregate/window).

    Rain keeps its original simple metric keys ("hourly", "calendar_daily",
    ...) since sum is its only aggregate. Other fields get
    "<field>_<aggregate>_<window>" keys, e.g. "windspeed_max_calendar_daily".
    """
    metrics: list[dict] = []
    for field in fields:
        for aggregate in FIELD_AGGREGATES.get(field, []):
            for window_key, where_clause in WINDOWS:
                if field == FIELD_RAIN:
                    metric_key = window_key
                else:
                    metric_key = f"{field.lower()}_{aggregate}_{window_key}"
                metrics.append(
                    {
                        "key": metric_key,
                        "translation_key": metric_key,
                        "field": field,
                        "aggregate": aggregate,
                        "where_clause": where_clause,
                    }
                )
    return metrics
