"""Switch platform for the Klereo integration."""
import logging
from dataclasses import dataclass
from typing import Any

PARALLEL_UPDATES = 0

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    OUTPUT_NAMES,
    OUTPUT_TRANSLATION_KEYS,
    OUTPUT_MODE_MANUAL,
    OUTPUT_STATE_OFF,
    OUTPUT_STATE_ON,
)
from .entity import KlereoEntity
from .api import KlereoApi

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class KlereoSwitchDescription(SwitchEntityDescription):
    """Switch entity description for a Klereo output."""

    output_index: int


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Klereo switches."""
    _LOGGER.debug("Setting up Klereo switches for entry: %s", entry.entry_id)
    coordinator = entry.runtime_data
    api = coordinator.api

    if not coordinator.data:
        _LOGGER.warning("No data for switches.")
        return

    switches = []
    for device in coordinator.data:
        device_id = device.get("idSystem")
        if not device_id:
            continue

        for output in device.get("outs", []):
            output_index = output.get("index")
            if output_index is not None:
                description = KlereoSwitchDescription(
                    key=f"switch_out{output_index}",
                    translation_key=OUTPUT_TRANSLATION_KEYS.get(output_index, f"output_{output_index}"),
                    output_index=output_index,
                )
                switches.append(KlereoOutputSwitch(coordinator, api, device, description))

    if switches:
        async_add_entities(switches)
        _LOGGER.info("Adding %d Klereo switches", len(switches))
    else:
        _LOGGER.info("No Klereo switches to add.")


class KlereoOutputSwitch(KlereoEntity, SwitchEntity):
    """Switch for a Klereo output."""

    entity_description: KlereoSwitchDescription

    def __init__(self, coordinator, api: KlereoApi, device: dict, description: KlereoSwitchDescription) -> None:
        super().__init__(coordinator, device)
        self.api = api
        self.entity_description = description
        self._output_index = description.output_index
        self._attr_unique_id = f"{self._device_id}_switch_out{description.output_index}"

        self._update_state()

    @property
    def is_on(self) -> bool | None:
        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the output."""
        _LOGGER.info("Turning on output %d", self._output_index)
        success = await self.api.async_set_output_mode_and_state(
            output_index=self._output_index,
            mode=OUTPUT_MODE_MANUAL,
            state=OUTPUT_STATE_ON,
        )
        if success:
            await self.coordinator.async_request_refresh()
        else:
            raise HomeAssistantError(
                translation_domain="klereo",
                translation_key="set_output_failed",
                translation_placeholders={"output": str(self._output_index)},
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the output."""
        _LOGGER.info("Turning off output %d", self._output_index)
        success = await self.api.async_set_output_mode_and_state(
            output_index=self._output_index,
            mode=OUTPUT_MODE_MANUAL,
            state=OUTPUT_STATE_OFF,
        )
        if success:
            await self.coordinator.async_request_refresh()
        else:
            raise HomeAssistantError(
                translation_domain="klereo",
                translation_key="set_output_failed",
                translation_placeholders={"output": str(self._output_index)},
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        """Determine on/off state from output status."""
        self._attr_is_on = self._output_is_on(self._output_index)
