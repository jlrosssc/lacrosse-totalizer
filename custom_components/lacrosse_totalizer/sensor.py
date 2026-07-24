"""Sensor platform for the LaCrosse Rain Totalizer integration."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPrecipitationDepth, UnitOfSpeed
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_NAME,
    CONF_LOCATION_NAME,
    DOMAIN,
    FIELD_RAIN,
    FIELD_WIND_SPEED,
    FIELDS_WITH_CURRENT_SENSOR,
)
from .coordinator import LacrosseTotalizerCoordinator

_FIELD_SENSOR_PROPS = {
    FIELD_RAIN: {
        "native_unit_of_measurement": UnitOfPrecipitationDepth.INCHES,
        "device_class": SensorDeviceClass.PRECIPITATION,
    },
    FIELD_WIND_SPEED: {
        "native_unit_of_measurement": UnitOfSpeed.MILES_PER_HOUR,
        "device_class": SensorDeviceClass.WIND_SPEED,
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LaCrosse Rain Totalizer sensors from a config entry."""
    coordinator: LacrosseTotalizerCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = [
        SensorEntityDescription(
            key=metric["key"],
            translation_key=metric["translation_key"],
            state_class=SensorStateClass.MEASUREMENT,
            **_FIELD_SENSOR_PROPS[metric["field"]],
        )
        for metric in coordinator.metrics
    ]

    entities: list[SensorEntity] = [
        LacrosseTotalizerSensor(coordinator, entry, description)
        for description in descriptions
    ]
    entities.extend(
        LacrosseCurrentValueSensor(coordinator, entry, field)
        for field in coordinator.fields
        if field in FIELDS_WITH_CURRENT_SENSOR
    )

    async_add_entities(entities)


class LacrosseTotalizerSensor(
    CoordinatorEntity[LacrosseTotalizerCoordinator], SensorEntity
):
    """Representation of a single corrected LaCrosse metric."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: LacrosseTotalizerCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"{entry.data[CONF_DEVICE_NAME]} ({entry.data[CONF_LOCATION_NAME]})",
            manufacturer="LaCrosse Technology",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value for this metric."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.key)


class LacrosseCurrentValueSensor(
    CoordinatorEntity[LacrosseTotalizerCoordinator], SensorEntity
):
    """Replays each new tick as its own state update, in order.

    Not a window aggregate -- this exists for consumers (like Smart
    Irrigation's own sample-and-average mechanism) that want the real,
    deduplicated sequence of readings since the last update rather than a
    single snapshot. A 60-second poll of a live "current value" can repeat
    a stale reading or miss a brief spike between polls; replaying the
    actual tick history never does either.
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: LacrosseTotalizerCoordinator,
        entry: ConfigEntry,
        field: str,
    ) -> None:
        super().__init__(coordinator)
        self._field = field
        key = f"{field.lower()}_current"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        props = _FIELD_SENSOR_PROPS[field]
        self._attr_native_unit_of_measurement = props["native_unit_of_measurement"]
        self._attr_device_class = props["device_class"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"{entry.data[CONF_DEVICE_NAME]} ({entry.data[CONF_LOCATION_NAME]})",
            manufacturer="LaCrosse Technology",
            entry_type=DeviceEntryType.SERVICE,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Replay every new tick for this field as its own state write."""
        new_ticks = self.coordinator.new_ticks_by_field.get(self._field, [])
        for tick in sorted(new_ticks, key=lambda t: t.get("u", 0)):
            value = tick.get("s")
            if value is None:
                continue
            self._attr_native_value = value
            self.async_write_ha_state()
