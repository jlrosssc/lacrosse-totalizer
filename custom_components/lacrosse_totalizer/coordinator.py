"""Data update coordinator for the LaCrosse Rain Totalizer integration."""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta

from lacrosse_view import HTTPError, LaCrosse, Location

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BACKFILL_CHUNK_DAYS,
    BACKFILL_SLEEP_SECONDS,
    CONF_DEVICE_NAME,
    CONF_FIELDS,
    CONF_LOCATION_ID,
    CONF_LOCATION_NAME,
    INITIAL_LOOKBACK_HOURS,
    SCAN_INTERVAL_MINUTES,
    SQL_AGGREGATE_FUNCTIONS,
    build_metrics,
)

_LOGGER = logging.getLogger(__name__)


class LacrosseTotalizerCoordinator(DataUpdateCoordinator[dict[str, float]]):
    """Fetches LaCrosse tick history and computes accurate totals/extremes.

    Unlike the built-in lacrosse_view integration (which polls a live
    "current value" snapshot every 60 seconds and can silently drop or
    double-count events during bursts of activity), this coordinator
    queries LaCrosse's own tick-history endpoint for the exact readings
    recorded since the last checkpoint. Every reading is timestamped and
    durably logged by LaCrosse's cloud as it happens, so asking "what was
    recorded between time A and time B" is always exact, regardless of how
    often this coordinator runs.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"LaCrosse Totalizer ({entry.data[CONF_DEVICE_NAME]})",
            update_interval=timedelta(minutes=SCAN_INTERVAL_MINUTES),
        )
        self.entry = entry
        self.username = entry.data["username"]
        self.password = entry.data["password"]
        self.location_id = entry.data[CONF_LOCATION_ID]
        self.location_name = entry.data[CONF_LOCATION_NAME]
        self.device_name = entry.data[CONF_DEVICE_NAME]
        self.fields: list[str] = entry.data[CONF_FIELDS]
        self.metrics = build_metrics(self.fields)

        db_dir = hass.config.path("lacrosse_totalizer")
        self._db_path = f"{db_dir}/{entry.entry_id}.sqlite"
        self._api_lock = asyncio.Lock()
        self._backfill_task: asyncio.Task | None = None
        # Raw ticks fetched by the most recent update, keyed by field --
        # consumed by "current value" sensors to replay each real reading
        # as its own state update. Reset at the start of every update.
        self.new_ticks_by_field: dict[str, list[dict]] = {}

    async def async_config_entry_first_refresh(self) -> None:
        """Set up the local database, then run the first refresh."""
        await self.hass.async_add_executor_job(self._init_db)
        await super().async_config_entry_first_refresh()
        self._backfill_task = self.entry.async_create_background_task(
            self.hass, self._async_run_backfill(), "lacrosse_totalizer_backfill"
        )

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ticks (
                ts INTEGER NOT NULL,
                field TEXT NOT NULL,
                value REAL NOT NULL,
                PRIMARY KEY (ts, field)
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()

    def _get_meta(self, conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()

    def _insert_ticks(
        self, conn: sqlite3.Connection, ticks_by_field: dict[str, list[dict]]
    ) -> tuple[int, dict[str, list[dict]]]:
        max_ts = 0
        new_ticks_by_field: dict[str, list[dict]] = {}
        for field, ticks in ticks_by_field.items():
            for tick in ticks:
                ts = tick.get("u")
                val = tick.get("s")
                if ts is None or val is None:
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO ticks (ts, field, value) VALUES (?, ?, ?)",
                    (ts, field, val),
                )
                if cur.rowcount:
                    new_ticks_by_field.setdefault(field, []).append(tick)
                max_ts = max(max_ts, ts)
        conn.commit()
        return max_ts, new_ticks_by_field

    def _compute_totals(self, conn: sqlite3.Connection) -> dict[str, float]:
        totals: dict[str, float] = {}
        for metric in self.metrics:
            sql_func = SQL_AGGREGATE_FUNCTIONS[metric["aggregate"]]
            value = conn.execute(
                f"SELECT {sql_func}(value) FROM ticks "
                f"WHERE field = ? AND {metric['where_clause']}",
                (metric["field"],),
            ).fetchone()[0]
            totals[metric["key"]] = round(value, 4) if value is not None else None
        return totals

    async def _fetch_ticks(
        self, start_ts: int, end_ts: int
    ) -> dict[str, list[dict]]:
        async with self._api_lock:
            session = async_get_clientsession(self.hass)
            api = LaCrosse(session)
            await api.login(self.username, self.password)
            location = Location(id=self.location_id, name=self.location_name)
            sensors = await api.get_sensors(
                location,
                tz=str(self.hass.config.time_zone),
                start=str(start_ts),
                end=str(end_ts),
            )
        for sensor in sensors:
            if sensor.name == self.device_name and sensor.data:
                return {
                    field: sensor.data[field].get("values", [])
                    for field in self.fields
                    if field in sensor.data
                }
        return {}

    async def _async_update_data(self) -> dict[str, float]:
        def _read_checkpoint() -> int:
            conn = sqlite3.connect(self._db_path)
            try:
                checkpoint = self._get_meta(conn, "last_ts")
                if checkpoint:
                    return int(checkpoint)
                return int(time.time()) - INITIAL_LOOKBACK_HOURS * 3600
            finally:
                conn.close()

        start_ts = await self.hass.async_add_executor_job(_read_checkpoint)
        end_ts = int(time.time())

        try:
            ticks_by_field = (
                await self._fetch_ticks(start_ts, end_ts)
                if end_ts - start_ts >= 5
                else {}
            )
        except HTTPError as err:
            raise UpdateFailed(f"Error fetching LaCrosse tick history: {err}") from err

        def _apply() -> tuple[dict[str, float], dict[str, list[dict]]]:
            conn = sqlite3.connect(self._db_path)
            try:
                max_ts, new_ticks_by_field = self._insert_ticks(conn, ticks_by_field)
                self._set_meta(conn, "last_ts", str(max(max_ts, end_ts - 60)))
                return self._compute_totals(conn), new_ticks_by_field
            finally:
                conn.close()

        totals, self.new_ticks_by_field = await self.hass.async_add_executor_job(_apply)
        return totals

    async def async_request_backfill(self) -> None:
        """Manually (re)trigger the deep year-start backfill."""

        def _reset_progress() -> None:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("DELETE FROM meta WHERE key = 'backfill_progress_ts'")
                conn.commit()
            finally:
                conn.close()

        await self.hass.async_add_executor_job(_reset_progress)
        self._backfill_task = self.entry.async_create_background_task(
            self.hass, self._async_run_backfill(), "lacrosse_totalizer_backfill"
        )

    async def _async_run_backfill(self) -> None:
        """One-time backfill of tick history from Jan 1 of the current year.

        Runs in chunks (large single requests can 502 from LaCrosse's
        backend) and shares the same API lock as regular updates, so it
        never races the periodic refresh for the same login session.
        """

        def _read_progress() -> tuple[int, int]:
            conn = sqlite3.connect(self._db_path)
            try:
                year_start = int(datetime(datetime.now().year, 1, 1).timestamp())
                progress = self._get_meta(conn, "backfill_progress_ts")
                cursor = int(progress) if progress else year_start
                checkpoint = self._get_meta(conn, "last_ts")
                backfill_end = int(checkpoint) if checkpoint else int(time.time())
                return cursor, backfill_end
            finally:
                conn.close()

        cursor, backfill_end = await self.hass.async_add_executor_job(_read_progress)
        if cursor >= backfill_end:
            return

        chunk_seconds = BACKFILL_CHUNK_DAYS * 86400
        while cursor < backfill_end:
            chunk_end = min(cursor + chunk_seconds, backfill_end)
            try:
                ticks_by_field = await self._fetch_ticks(cursor, chunk_end)
            except HTTPError:
                _LOGGER.warning(
                    "LaCrosse backfill chunk failed (%s -> %s), will retry next time",
                    cursor,
                    chunk_end,
                )
                return

            def _store(ticks_by_field=ticks_by_field, chunk_end=chunk_end) -> None:
                conn = sqlite3.connect(self._db_path)
                try:
                    self._insert_ticks(conn, ticks_by_field)
                    self._set_meta(conn, "backfill_progress_ts", str(chunk_end))
                finally:
                    conn.close()

            await self.hass.async_add_executor_job(_store)
            cursor = chunk_end
            await asyncio.sleep(BACKFILL_SLEEP_SECONDS)

        _LOGGER.info("LaCrosse Totalizer backfill complete for %s", self.device_name)
