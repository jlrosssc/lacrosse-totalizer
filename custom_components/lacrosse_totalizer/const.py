"""Constants for the LaCrosse Rain Totalizer integration."""

DOMAIN = "lacrosse_totalizer"

CONF_LOCATION_ID = "location_id"
CONF_LOCATION_NAME = "location_name"
CONF_DEVICE_NAME = "device_name"
CONF_FIELD = "field"

DEFAULT_FIELD = "Rain"

SCAN_INTERVAL_MINUTES = 5
INITIAL_LOOKBACK_HOURS = 25
BACKFILL_CHUNK_DAYS = 14
BACKFILL_SLEEP_SECONDS = 1

# (metric key, translation key, SQL WHERE clause selecting ticks in this window)
METRICS = [
    (
        "hourly",
        "hourly",
        "strftime('%Y-%m-%d %H', ts, 'unixepoch', 'localtime') = "
        "strftime('%Y-%m-%d %H', 'now', 'localtime')",
    ),
    (
        "calendar_daily",
        "calendar_daily",
        "date(ts, 'unixepoch', 'localtime') = date('now', 'localtime')",
    ),
    (
        "rolling_24h",
        "rolling_24h",
        "ts >= strftime('%s', 'now') - 86400",
    ),
    (
        "monthly",
        "monthly",
        "strftime('%Y-%m', ts, 'unixepoch', 'localtime') = "
        "strftime('%Y-%m', 'now', 'localtime')",
    ),
    (
        "yearly",
        "yearly",
        "strftime('%Y', ts, 'unixepoch', 'localtime') = strftime('%Y', 'now', 'localtime')",
    ),
    (
        "rolling_3day",
        "rolling_3day",
        "ts >= strftime('%s', 'now') - 3 * 86400",
    ),
]
