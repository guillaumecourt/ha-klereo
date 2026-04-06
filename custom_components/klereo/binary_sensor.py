"""Binary sensor platform for the Klereo integration."""
import logging
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import KlereoEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class KlereoBinarySensorDescription(BinarySensorEntityDescription):
    """Klereo binary sensor entity description."""

    output_index: int


BINARY_SENSOR_DESCRIPTIONS: tuple[KlereoBinarySensorDescription, ...] = (
    KlereoBinarySensorDescription(
        key="filtration_running",
        translation_key="filtration_running",
        output_index=1,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    KlereoBinarySensorDescription(
        key="heating_running",
        translation_key="heating_running",
        output_index=6,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    KlereoBinarySensorDescription(
        key="lighting_on",
        translation_key="lighting_on",
        output_index=0,
        device_class=BinarySensorDeviceClass.POWER,
    ),
    KlereoBinarySensorDescription(
        key="electrolysis_running",
        translation_key="electrolysis_running",
        output_index=5,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Klereo binary sensors."""
    coordinator = entry.runtime_data

    if not coordinator.data:
        _LOGGER.debug("No data for binary sensors yet.")
        return

    entities = []
    for device in coordinator.data:
        device_id = device.get("idSystem")
        if not device_id:
            continue

        available_outputs = {o.get("index") for o in device.get("outs", [])}

        for description in BINARY_SENSOR_DESCRIPTIONS:
            if description.output_index in available_outputs:
                entities.append(
                    KlereoOutputBinarySensor(coordinator, device, description)
                )

    if entities:
        _LOGGER.info("Adding %d Klereo binary sensors", len(entities))
        async_add_entities(entities)


class KlereoOutputBinarySensor(KlereoEntity, BinarySensorEntity):
    """Binary sensor showing if a Klereo output is active."""

    entity_description: KlereoBinarySensorDescription

    def __init__(self, coordinator, device: dict, description: KlereoBinarySensorDescription) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._output_index = description.output_index
        self._attr_unique_id = f"{self._device_id}_binary_{description.key}"
        self._update_state()

    @property
    def is_on(self) -> bool | None:
        return self._attr_is_on

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        """Determine on/off state from output status."""
        output_data = self._get_output_data(self._output_index)
        if output_data is None:
            self._attr_is_on = None
            return
        status = output_data.get("status")
        if status is not None:
            try:
                self._attr_is_on = int(status) != 0
            except (ValueError, TypeError):
                self._attr_is_on = None
        else:
            self._attr_is_on = None
