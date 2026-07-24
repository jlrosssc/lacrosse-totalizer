"""Config flow for the LaCrosse Rain Totalizer integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from lacrosse_view import LaCrosse, LoginError, HTTPError

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_DEVICE_NAME,
    CONF_FIELDS,
    CONF_LOCATION_ID,
    CONF_LOCATION_NAME,
    DOMAIN,
    SUPPORTED_FIELDS,
)

_LOGGER = logging.getLogger(__name__)


class LacrosseTotalizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LaCrosse Rain Totalizer."""

    VERSION = 1

    def __init__(self) -> None:
        self._username: str | None = None
        self._password: str | None = None
        self._locations: list[Any] = []
        self._location_id: str | None = None
        self._location_name: str | None = None
        self._devices: list[Any] = []
        self._device_name: str | None = None
        self._device_fields: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step: LaCrosse account credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            api = LaCrosse(session)
            try:
                await api.login(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
                self._locations = await api.get_locations()
            except LoginError:
                errors["base"] = "invalid_auth"
            except (HTTPError, aiohttp.ClientError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during LaCrosse login")
                errors["base"] = "unknown"
            else:
                if not self._locations:
                    errors["base"] = "no_locations"
                else:
                    self._username = user_input[CONF_USERNAME]
                    self._password = user_input[CONF_PASSWORD]
                    return await self.async_step_location()

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle location selection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._location_id = user_input[CONF_LOCATION_ID]
            self._location_name = next(
                (
                    loc.name
                    for loc in self._locations
                    if loc.id == self._location_id
                ),
                self._location_id,
            )

            session = async_get_clientsession(self.hass)
            api = LaCrosse(session)
            try:
                await api.login(self._username, self._password)
                location = next(
                    loc for loc in self._locations if loc.id == self._location_id
                )
                self._devices = await api.get_devices(location)
            except (HTTPError, aiohttp.ClientError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error fetching devices")
                errors["base"] = "unknown"
            else:
                self._devices = [
                    d
                    for d in self._devices
                    if any(
                        f.lower() in (sf.lower() for sf in SUPPORTED_FIELDS)
                        for f in d.sensor_field_names
                    )
                ]
                if not self._devices:
                    errors["base"] = "no_supported_devices"
                else:
                    return await self.async_step_device()

        location_options = {loc.id: loc.name for loc in self._locations}
        schema = vol.Schema(
            {vol.Required(CONF_LOCATION_ID): vol.In(location_options)}
        )
        return self.async_show_form(
            step_id="location", data_schema=schema, errors=errors
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle device selection."""
        if user_input is not None:
            self._device_name = user_input[CONF_DEVICE_NAME]
            return await self.async_step_fields()

        device_options = {d.name: d.name for d in self._devices}
        schema = vol.Schema(
            {vol.Required(CONF_DEVICE_NAME): vol.In(device_options)}
        )
        return self.async_show_form(step_id="device", data_schema=schema)

    async def async_step_fields(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle field selection (Rain, wind speed, or both)."""
        device = next(d for d in self._devices if d.name == self._device_name)
        available_fields = [
            field
            for field in SUPPORTED_FIELDS
            if field.lower() in (sf.lower() for sf in device.sensor_field_names)
        ]

        errors: dict[str, str] = {}

        if user_input is not None:
            fields = user_input[CONF_FIELDS]
            if not fields:
                errors["base"] = "no_fields_selected"
            else:
                await self.async_set_unique_id(
                    f"{self._location_id}:{self._device_name}"
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"{self._device_name} ({self._location_name}) Totalizer",
                    data={
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_LOCATION_ID: self._location_id,
                        CONF_LOCATION_NAME: self._location_name,
                        CONF_DEVICE_NAME: self._device_name,
                        CONF_FIELDS: fields,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_FIELDS, default=available_fields): selector.selector(
                    {
                        "select": {
                            "options": available_fields,
                            "multiple": True,
                            "mode": "list",
                        }
                    }
                )
            }
        )
        return self.async_show_form(
            step_id="fields", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return LacrosseTotalizerOptionsFlow(config_entry)


class LacrosseTotalizerOptionsFlow(config_entries.OptionsFlow):
    """Options flow: allow re-running the deep backfill on demand."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional("rerun_backfill", default=False): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
