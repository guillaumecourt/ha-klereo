"""Button platform for the Klereo integration — container reset buttons."""
import logging
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONTAINER_TRACKING
from .entity import KlereoEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class KlereoButtonDescription(ButtonEntityDescription):
    """Klereo button entity description."""

    container_key: str
    debit_key: str
    total_time_key: str
    reset_option: str
    reset_date_option: str


BUTTON_DESCRIPTIONS: tuple[KlereoButtonDescription, ...] = tuple(
    KlereoButtonDescription(
        key=ct_def["id_key"],
        translation_key=ct_def["id_key"],
        entity_category=EntityCategory.CONFIG,
        container_key=ct_key,
        debit_key=ct_def["debit_key"],
        total_time_key=ct_def["total_time_key"],
        reset_option=ct_def["reset_option"],
        reset_date_option=ct_def["reset_date_option"],
    )
    for ct_key, ct_def in CONTAINER_TRACKING.items()
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Klereo container reset buttons."""
    coordinator = entry.runtime_data

    if not coordinator.data:
        _LOGGER.debug("No data for buttons yet.")
        return

    entities = []
    for device in coordinator.data:
        device_id = device.get("idSystem")
        if not device_id:
            continue

        for description in BUTTON_DESCRIPTIONS:
            entities.append(
                KlereoContainerResetButton(coordinator, device, entry, hass, description)
            )

    if entities:
        _LOGGER.info("Adding %d Klereo container reset buttons", len(entities))
        async_add_entities(entities)


def _compute_current_total(params: dict, debit_key: str, time_key: str) -> float:
    """Compute cumulative volume in mL from API params."""
    try:
        debit = float(params.get(debit_key, 0))
        time_s = float(params.get(time_key, 0))
        return (debit / 36000.0) * time_s
    except (ValueError, TypeError):
        return 0.0


class KlereoContainerResetButton(KlereoEntity, ButtonEntity):
    """Button to reset container tracking when a new container is installed."""

    entity_description: KlereoButtonDescription

    def __init__(self, coordinator, device, entry, hass, description: KlereoButtonDescription):
        super().__init__(coordinator, device)
        self.entity_description = description
        self._entry = entry
        self._hass = hass
        self._attr_unique_id = f"{self._device_id}_{description.key}"

    async def async_press(self) -> None:
        """Handle button press — reset container tracking."""
        device_data = self._get_device_data()
        if not device_data:
            _LOGGER.warning("No device data available for container reset")
            return

        params = device_data.get("params", {})
        current_total = _compute_current_total(
            params,
            self.entity_description.debit_key,
            self.entity_description.total_time_key,
        )

        new_options = {
            **self._entry.options,
            self.entity_description.reset_option: current_total,
            self.entity_description.reset_date_option: datetime.now().isoformat(),
        }
        self._hass.config_entries.async_update_entry(self._entry, options=new_options)

        container_key = self.entity_description.container_key
        _LOGGER.info(
            "Container %s reset. Current total: %.1f mL",
            container_key,
            current_total,
        )

        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Klereo",
                "message": f"Bidon {container_key} réinitialisé. Total enregistré : {current_total:.0f} mL",
                "notification_id": f"klereo_{container_key}_reset",
            },
        )

        await self.coordinator.async_request_refresh()
