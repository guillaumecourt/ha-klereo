"""Button platform for the Klereo integration — container reset buttons."""
import logging
from dataclasses import dataclass

PARALLEL_UPDATES = 0

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONTAINER_TRACKING, VOLUME_DIVISOR
from .entity import KlereoEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class KlereoButtonDescription(ButtonEntityDescription):
    """Klereo button entity description."""

    container_key: str
    debit_key: str
    total_time_key: str
    today_time_key: str
    reset_option: str
    reset_date_option: str
    today_time_reset_option: str


BUTTON_DESCRIPTIONS: tuple[KlereoButtonDescription, ...] = tuple(
    KlereoButtonDescription(
        key=ct_def["id_key"],
        translation_key=ct_def["id_key"],
        entity_category=EntityCategory.CONFIG,
        container_key=ct_key,
        debit_key=ct_def["debit_key"],
        total_time_key=ct_def["total_time_key"],
        today_time_key=ct_def["today_time_key"],
        reset_option=ct_def["reset_option"],
        reset_date_option=ct_def["reset_date_option"],
        today_time_reset_option=ct_def["today_time_reset_option"],
    )
    for ct_key, ct_def in CONTAINER_TRACKING.items()
)


REFRESH_BUTTON_DESCRIPTION = ButtonEntityDescription(
    key="refresh",
    translation_key="refresh",
    entity_category=EntityCategory.CONFIG,
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
                KlereoContainerResetButton(coordinator, device, description)
            )

        # Refresh button per device
        entities.append(KlereoRefreshButton(coordinator, device))

    if entities:
        _LOGGER.info("Adding %d Klereo buttons", len(entities))
        async_add_entities(entities)


def _compute_current_total(params: dict, debit_key: str, time_key: str) -> float:
    """Compute cumulative volume in liters from API params."""
    try:
        debit = float(params.get(debit_key, 0))
        time_s = float(params.get(time_key, 0))
        return (debit / VOLUME_DIVISOR) * time_s
    except (ValueError, TypeError):
        return 0.0


class KlereoContainerResetButton(KlereoEntity, ButtonEntity):
    """Button to reset container tracking when a new container is installed."""

    entity_description: KlereoButtonDescription

    def __init__(self, coordinator, device, description: KlereoButtonDescription):
        super().__init__(coordinator, device)
        self.entity_description = description
        self._attr_unique_id = f"{self._device_id}_{description.key}"

    async def async_press(self) -> None:
        """Handle button press — reset container tracking."""
        params = self._get_params()
        if not params:
            _LOGGER.warning("No device data available for container reset")
            return

        current_total = _compute_current_total(
            params,
            self.entity_description.debit_key,
            self.entity_description.total_time_key,
        )

        # Snapshot the pod's intra-day counter so post-reset daily_history
        # entries can subtract pre-reset consumption. Cleared by the
        # coordinator on rollover (TodayTime resets to 0 at pod midnight)
        # or when the day rolls over on the HA side.
        today_time_snapshot = 0.0
        try:
            today_time_snapshot = float(
                params.get(self.entity_description.today_time_key, 0) or 0
            )
        except (ValueError, TypeError):
            today_time_snapshot = 0.0

        entry = self.coordinator.config_entry
        container_key = self.entity_description.container_key
        new_options = {
            **entry.options,
            self.entity_description.reset_option: current_total,
            self.entity_description.reset_date_option: dt_util.now().isoformat(),
            self.entity_description.today_time_reset_option: today_time_snapshot,
            f"{container_key}_daily_history": [],
        }
        self.hass.config_entries.async_update_entry(entry, options=new_options)

        _LOGGER.info(
            "Container %s reset. Current total: %.1f L, today_time_snapshot: %.0fs",
            container_key,
            current_total,
            today_time_snapshot,
        )

        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Klereo",
                "message": f"Bidon {container_key} réinitialisé. Total enregistré : {current_total:.1f} L",
                "notification_id": f"klereo_{container_key}_reset",
            },
        )

        await self.coordinator.async_request_refresh()


class KlereoRefreshButton(KlereoEntity, ButtonEntity):
    """Button to manually refresh data from the Klereo API."""

    entity_description: ButtonEntityDescription

    def __init__(self, coordinator, device: dict):
        super().__init__(coordinator, device)
        self.entity_description = REFRESH_BUTTON_DESCRIPTION
        self._attr_unique_id = f"{self._device_id}_refresh"

    async def async_press(self) -> None:
        """Handle button press — refresh data."""
        _LOGGER.info("Manual refresh triggered for device %s", self._device_id)
        await self.coordinator.async_request_refresh()
