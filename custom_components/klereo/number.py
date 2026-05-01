"""Number platform for the Klereo integration."""
import logging
from typing import Any

PARALLEL_UPDATES = 0

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    SETPOINT_DEFINITIONS,
    SETPOINT_DISABLED_THRESHOLD,
    CONTAINER_TRACKING,
    OUTPUT_MODE_MANUAL,
)
from .entity import KlereoEntity
from .api import KlereoApi

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Klereo number entities."""
    _LOGGER.debug("Setting up Klereo numbers for entry: %s", entry.entry_id)
    coordinator = entry.runtime_data
    api = coordinator.api

    if not coordinator.data:
        _LOGGER.warning("No data for numbers.")
        return

    numbers = []
    for device in coordinator.data:
        device_id = device.get("idSystem")
        if not device_id:
            continue

        params = device.get("params", {})
        if not isinstance(params, dict):
            continue

        # Setpoint numbers
        for param_key, setpoint_def in SETPOINT_DEFINITIONS.items():
            if param_key in params:
                numbers.append(KlereoSetpointNumber(coordinator, api, device, param_key, setpoint_def))

        # Container capacity numbers
        for ct_key, ct_def in CONTAINER_TRACKING.items():
            numbers.append(
                KlereoContainerCapacityNumber(coordinator, device, ct_key, ct_def)
            )

        # Variable speed pump
        pump_max_speed = params.get("PumpMaxSpeed")
        if pump_max_speed is not None:
            try:
                max_speed = int(float(pump_max_speed))
                if max_speed > 1:
                    numbers.append(KlereoPumpSpeedNumber(coordinator, api, device, max_speed))
            except (ValueError, TypeError):
                pass

    if numbers:
        async_add_entities(numbers)
        _LOGGER.info("Adding %d Klereo number entities", len(numbers))
    else:
        _LOGGER.info("No Klereo number entities to add.")


class KlereoSetpointNumber(KlereoEntity, NumberEntity):
    """Setpoint number entity driven by SETPOINT_DEFINITIONS."""

    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, api: KlereoApi, device: dict, param_key: str, setpoint_def: dict) -> None:
        super().__init__(coordinator, device)
        self.api = api
        self._param_key = param_key
        self._setpoint_def = setpoint_def

        self._attr_translation_key = setpoint_def["id_key"]
        self._attr_unique_id = f"{self._device_id}_{setpoint_def['id_key']}"
        self._attr_native_unit_of_measurement = setpoint_def.get("unit")
        self._attr_native_min_value = setpoint_def.get("min", 0)
        self._attr_native_max_value = setpoint_def.get("max", 100)
        self._attr_native_step = setpoint_def.get("step", 1)

        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        params = self._get_params()
        raw = params.get(self._param_key)
        if raw is not None:
            try:
                value = float(raw)
                if value <= SETPOINT_DISABLED_THRESHOLD:
                    self._attr_native_value = None
                else:
                    self._attr_native_value = round(value, 1)
            except (ValueError, TypeError):
                self._attr_native_value = None
        else:
            self._attr_native_value = None

    async def async_set_native_value(self, value: float) -> None:
        """Set the setpoint value via API."""
        _LOGGER.info("Setting %s to %s", self._param_key, value)
        success = await self.api.async_set_param(self._param_key, value)
        if success:
            await self.coordinator.async_request_refresh()
        else:
            raise HomeAssistantError(
                translation_domain="klereo",
                translation_key="set_value_failed",
                translation_placeholders={"param": self._param_key, "value": str(value)},
            )


class KlereoPumpSpeedNumber(KlereoEntity, NumberEntity):
    """Variable speed pump control."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_value: float | None = None

    def __init__(self, coordinator, api: KlereoApi, device: dict, max_speed: int) -> None:
        super().__init__(coordinator, device)
        self.api = api
        self._max_speed = max_speed
        # Find filtration output index (default 1)
        self._filtration_index = 1

        self._attr_translation_key = "pump_speed"
        self._attr_unique_id = f"{self._device_id}_pump_speed"
        self._attr_native_min_value = 0
        self._attr_native_max_value = max_speed
        self._attr_native_step = 1

        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        output_data = self._get_output_data(self._filtration_index)
        if output_data is not None:
            status = output_data.get("status")
            if status is not None:
                try:
                    self._attr_native_value = float(int(status))
                except (ValueError, TypeError):
                    self._attr_native_value = None
            else:
                self._attr_native_value = None
        else:
            self._attr_native_value = None

    async def async_set_native_value(self, value: float) -> None:
        """Set pump speed via SetOut."""
        speed = int(value)
        _LOGGER.info("Setting pump speed to %d", speed)
        success = await self.api.async_set_output_mode_and_state(
            output_index=self._filtration_index,
            mode=OUTPUT_MODE_MANUAL,
            state=speed,
        )
        if success:
            await self.coordinator.async_request_refresh()
        else:
            raise HomeAssistantError(
                translation_domain="klereo",
                translation_key="set_value_failed",
                translation_placeholders={"param": "pump_speed", "value": str(speed)},
            )


class KlereoContainerCapacityNumber(KlereoEntity, NumberEntity):
    """Container capacity number entity stored in config entry options."""

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device: dict, container_key: str, ct_def: dict) -> None:
        super().__init__(coordinator, device)
        self._container_key = container_key
        self._capacity_option = ct_def["capacity_option"]
        self._capacity_default = ct_def["capacity_default"]

        self._attr_translation_key = f"capacity_{container_key}"
        self._attr_unique_id = f"{self._device_id}_capacity_{container_key}"
        self._attr_native_unit_of_measurement = "L"
        self._attr_native_min_value = ct_def.get("capacity_min", 1.0)
        self._attr_native_max_value = ct_def.get("capacity_max", 200.0)
        self._attr_native_step = ct_def.get("capacity_step", 0.5)

        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        entry = self.coordinator.config_entry
        raw = entry.options.get(self._capacity_option)
        if raw is not None:
            try:
                self._attr_native_value = float(raw)
            except (ValueError, TypeError):
                self._attr_native_value = self._capacity_default
        else:
            self._attr_native_value = self._capacity_default

    async def async_set_native_value(self, value: float) -> None:
        """Set capacity in config entry options."""
        entry = self.coordinator.config_entry
        new_options = {**entry.options, self._capacity_option: value}
        self.hass.config_entries.async_update_entry(entry, options=new_options)
        self._attr_native_value = value
        self.async_write_ha_state()
