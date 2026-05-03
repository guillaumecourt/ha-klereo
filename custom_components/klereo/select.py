"""Select platform for the Klereo integration."""
import logging
from dataclasses import dataclass
from typing import Any

PARALLEL_UPDATES = 0

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    OUTPUT_MODE_MANUAL,
    OUTPUT_MODE_AUTO,
    OUTPUT_MODE_SCHEDULE,
    OUTPUT_MODE_TIMER,
    OUTPUT_MODE_PULSE,
    OUTPUT_MODE_SYNC_FILTER,
    OUTPUT_STATE_OFF,
    OUTPUT_STATE_ON,
    OUTPUT_STATE_SCHEDULE,
    OUTPUT_STATE_SPEED_3,
    OUTPUT_STATE_AUTO,
    LIGHTING_FLAGS,
    DEFAULT_OFF_DELAY_MINUTES,
    HEATING_MODE_OPTIONS,
    HEATING_MODE_TO_VALUE,
    HEATING_VALUE_TO_MODE,
    HEATING_OUTPUT_INDEX,
)
from .entity import KlereoEntity
from .api import KlereoApi

_LOGGER = logging.getLogger(__name__)

# --- Filtration constants ---
FILTRATION_OUTPUT_INDEX = 1
FILTRATION_SELECT_OPTIONS = ["off", "speed_1", "speed_2", "speed_3", "auto"]
FILTRATION_OPTION_TO_API = {
    "off": {"mode": OUTPUT_MODE_MANUAL, "state": OUTPUT_STATE_OFF},
    "speed_1": {"mode": OUTPUT_MODE_MANUAL, "state": OUTPUT_STATE_ON},
    "speed_2": {"mode": OUTPUT_MODE_MANUAL, "state": OUTPUT_STATE_SCHEDULE},
    "speed_3": {"mode": OUTPUT_MODE_MANUAL, "state": OUTPUT_STATE_SPEED_3},
    "auto": {"mode": OUTPUT_MODE_AUTO, "state": OUTPUT_STATE_AUTO},
}

# --- Lighting constants ---
LIGHTING_OUTPUT_INDEX = 0
LIGHTING_SELECT_OPTIONS = [
    "manual_off", "manual_on", "timer", "pulse",
    "schedule", "sync_filter",
]
LIGHTING_OPTION_TO_API: dict[str, dict[str, Any]] = {
    "manual_off": {"api_func": "manual", "params": {"state": False}},
    "manual_on": {"api_func": "manual", "params": {"state": True}},
    "timer": {"api_func": "timer", "params": {"off_delay": DEFAULT_OFF_DELAY_MINUTES}},
    "pulse": {"api_func": "pulse", "params": {"off_delay": DEFAULT_OFF_DELAY_MINUTES}},
    "schedule": {"api_func": "schedule", "params": {}},
    "sync_filter": {"api_func": "sync_filter", "params": {}},
}
LIGHTING_TIMER_FLAGS = {"custom_flags": 6721, "other_flags": 0}
LIGHTING_PULSE_FLAGS = {"custom_flags": 6721, "other_flags": 0}


@dataclass(frozen=True, kw_only=True)
class KlereoSelectDescription(SelectEntityDescription):
    """Select entity description for a Klereo select control."""


FILTRATION_SELECT_DESCRIPTION = KlereoSelectDescription(
    key="filtration_mode",
    translation_key="filtration_mode",
    options=FILTRATION_SELECT_OPTIONS,
)
LIGHTING_SELECT_DESCRIPTION = KlereoSelectDescription(
    key="lighting_mode",
    translation_key="lighting_mode",
    options=LIGHTING_SELECT_OPTIONS,
)
HEATING_MODE_SELECT_DESCRIPTION = KlereoSelectDescription(
    key="heating_mode",
    translation_key="heating_mode",
    options=HEATING_MODE_OPTIONS,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Klereo select platform."""
    _LOGGER.debug("Setting up Klereo select platform for entry: %s", entry.entry_id)

    coordinator = entry.runtime_data
    api = coordinator.api

    if not coordinator.data:
        _LOGGER.warning("No data available for select entities.")
        return

    select_entities = []
    for device in coordinator.data:
        device_id = device.get("idSystem", "unknown_device")
        outputs = device.get("outs", [])

        # Filtration select
        if any(out.get("index") == FILTRATION_OUTPUT_INDEX for out in outputs):
            select_entities.append(KlereoFiltrationSelect(coordinator, api, device, FILTRATION_SELECT_DESCRIPTION))

        # Lighting select
        if any(out.get("index") == LIGHTING_OUTPUT_INDEX for out in outputs):
            select_entities.append(KlereoLightingSelect(coordinator, api, device, LIGHTING_SELECT_DESCRIPTION))

        # Heating mode select
        if any(out.get("index") == HEATING_OUTPUT_INDEX for out in outputs):
            select_entities.append(KlereoHeatingModeSelect(coordinator, api, device, HEATING_MODE_SELECT_DESCRIPTION))

    if select_entities:
        _LOGGER.info("Adding %d Klereo select entities", len(select_entities))
        async_add_entities(select_entities)
    else:
        _LOGGER.info("No Klereo select entities to add.")


class KlereoFiltrationSelect(KlereoEntity, SelectEntity):
    """Filtration control select entity."""

    entity_description: KlereoSelectDescription

    def __init__(self, coordinator, api: KlereoApi, device: dict, description: KlereoSelectDescription) -> None:
        super().__init__(coordinator, device)
        self.api = api
        self.entity_description = description
        self._attr_unique_id = f"{self._device_id}_filtration_mode_out{FILTRATION_OUTPUT_INDEX}"

        self._update_state()

    @property
    def current_option(self) -> str | None:
        return self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        if option not in FILTRATION_OPTION_TO_API:
            raise HomeAssistantError(
                translation_domain="klereo",
                translation_key="invalid_option",
                translation_placeholders={"option": option},
            )
        params = FILTRATION_OPTION_TO_API[option]
        _LOGGER.info("Filtration Select: selected '%s'", option)
        success = await self.api.async_set_output_mode_and_state(
            output_index=FILTRATION_OUTPUT_INDEX,
            mode=params["mode"],
            state=params["state"],
        )
        if success:
            await self.coordinator.async_request_refresh()
        else:
            raise HomeAssistantError(
                translation_domain="klereo",
                translation_key="select_option_failed",
                translation_placeholders={"option": option},
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        current_option = None
        output_data = self._get_output_data(FILTRATION_OUTPUT_INDEX)
        if not output_data:
            self._attr_current_option = None
            return

        current_mode = output_data.get("mode")
        current_state = output_data.get("status")
        try:
            if current_mode is not None:
                current_mode = int(current_mode)
            if current_state is not None:
                current_state = int(current_state)
        except (ValueError, TypeError):
            current_mode = current_state = None

        if current_mode == OUTPUT_MODE_AUTO:
            current_option = "auto"
        elif current_mode == OUTPUT_MODE_MANUAL:
            if current_state == OUTPUT_STATE_OFF:
                current_option = "off"
            elif current_state == OUTPUT_STATE_ON:
                current_option = "speed_1"
            elif current_state == OUTPUT_STATE_SCHEDULE:
                current_option = "speed_2"
            elif current_state == OUTPUT_STATE_SPEED_3:
                current_option = "speed_3"

        if current_option not in FILTRATION_SELECT_OPTIONS:
            current_option = None
        self._attr_current_option = current_option


class KlereoLightingSelect(KlereoEntity, SelectEntity):
    """Lighting control select entity."""

    entity_description: KlereoSelectDescription

    def __init__(self, coordinator, api: KlereoApi, device: dict, description: KlereoSelectDescription) -> None:
        super().__init__(coordinator, device)
        self.api = api
        self.entity_description = description
        self._attr_unique_id = f"{self._device_id}_lighting_mode_out{LIGHTING_OUTPUT_INDEX}"

        self._update_state()

    @property
    def current_option(self) -> str | None:
        return self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        if option not in LIGHTING_OPTION_TO_API:
            raise HomeAssistantError(
                translation_domain="klereo",
                translation_key="invalid_option",
                translation_placeholders={"option": option},
            )

        command_info = LIGHTING_OPTION_TO_API[option]
        api_func_name = command_info["api_func"]
        params = command_info["params"]
        success = False

        _LOGGER.info("Lighting Select: selected '%s'", option)

        if api_func_name == "manual":
            success = await self.api.async_set_output_mode_and_state(
                output_index=LIGHTING_OUTPUT_INDEX,
                mode=OUTPUT_MODE_MANUAL,
                state=(OUTPUT_STATE_ON if params["state"] else OUTPUT_STATE_OFF),
            )
        elif api_func_name == "timer":
            step1_ok = await self.api.async_set_output_auto_off(LIGHTING_OUTPUT_INDEX, params["off_delay"])
            if step1_ok:
                success = await self.api.async_set_output_mode_and_state(
                    output_index=LIGHTING_OUTPUT_INDEX,
                    mode=OUTPUT_MODE_TIMER,
                    state=OUTPUT_STATE_ON,
                    **LIGHTING_TIMER_FLAGS,
                )
        elif api_func_name == "pulse":
            step1_ok = await self.api.async_set_output_auto_off(LIGHTING_OUTPUT_INDEX, params["off_delay"])
            if step1_ok:
                success = await self.api.async_set_output_mode_and_state(
                    output_index=LIGHTING_OUTPUT_INDEX,
                    mode=OUTPUT_MODE_PULSE,
                    state=OUTPUT_STATE_ON,
                    **LIGHTING_PULSE_FLAGS,
                )
        elif api_func_name == "schedule":
            success = await self.api.async_set_output_mode_and_state(
                output_index=LIGHTING_OUTPUT_INDEX,
                mode=OUTPUT_MODE_SCHEDULE,
                state=OUTPUT_STATE_SCHEDULE,
            )
        elif api_func_name == "sync_filter":
            success = await self.api.async_set_output_mode_and_state(
                output_index=LIGHTING_OUTPUT_INDEX,
                mode=OUTPUT_MODE_SYNC_FILTER,
                state=OUTPUT_STATE_ON,
            )

        if success:
            await self.coordinator.async_request_refresh()
        else:
            raise HomeAssistantError(
                translation_domain="klereo",
                translation_key="select_option_failed",
                translation_placeholders={"option": option},
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        current_option = None
        output_data = self._get_output_data(LIGHTING_OUTPUT_INDEX)
        if not output_data:
            self._attr_current_option = None
            return

        current_mode = output_data.get("mode")
        current_state = output_data.get("status")
        try:
            if current_mode is not None:
                current_mode = int(current_mode)
            if current_state is not None:
                current_state = int(current_state)
        except (ValueError, TypeError):
            current_mode = current_state = None

        if current_mode == OUTPUT_MODE_MANUAL:
            if current_state == OUTPUT_STATE_OFF:
                current_option = "manual_off"
            elif current_state == OUTPUT_STATE_ON:
                current_option = "manual_on"
        elif current_mode == OUTPUT_MODE_TIMER:
            current_option = "timer"
        elif current_mode == OUTPUT_MODE_PULSE:
            current_option = "pulse"
        elif current_mode == OUTPUT_MODE_SCHEDULE:
            current_option = "schedule"
        elif current_mode == OUTPUT_MODE_SYNC_FILTER:
            current_option = "sync_filter"

        if current_option not in LIGHTING_SELECT_OPTIONS:
            current_option = None
        self._attr_current_option = current_option


class KlereoHeatingModeSelect(KlereoEntity, SelectEntity):
    """Heating mode control select entity."""

    entity_description: KlereoSelectDescription

    def __init__(self, coordinator, api: KlereoApi, device: dict, description: KlereoSelectDescription) -> None:
        super().__init__(coordinator, device)
        self.api = api
        self.entity_description = description
        self._attr_unique_id = f"{self._device_id}_heating_mode"

        self._update_state()

    @property
    def current_option(self) -> str | None:
        return self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        if option not in HEATING_MODE_TO_VALUE:
            raise HomeAssistantError(
                translation_domain="klereo",
                translation_key="invalid_option",
                translation_placeholders={"option": option},
            )

        _LOGGER.info("Heating Mode Select: selected '%s'", option)
        value = HEATING_MODE_TO_VALUE[option]
        success = await self.api.async_set_param("HeaterMode", value)
        if success:
            await self.coordinator.async_request_refresh()
        else:
            raise HomeAssistantError(
                translation_domain="klereo",
                translation_key="select_option_failed",
                translation_placeholders={"option": option},
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        params = self._get_params()
        raw = params.get("HeaterMode")
        if raw is not None:
            try:
                int_val = int(float(raw))
                self._attr_current_option = HEATING_VALUE_TO_MODE.get(int_val)
            except (ValueError, TypeError):
                self._attr_current_option = None
        else:
            self._attr_current_option = None
