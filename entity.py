"""Base entity for the Klereo integration."""
import logging
from typing import Any, Dict, Optional

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class KlereoEntity(CoordinatorEntity):
    """Base class for Klereo entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device: dict) -> None:
        super().__init__(coordinator)
        self._device = device
        self._device_id = device.get("idSystem")
        self._pool_nickname = device.get("poolNickname", f"Klereo Device {self._device_id}")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._pool_nickname,
            "manufacturer": "Klereo",
        }

    def _get_device_data(self) -> Optional[dict]:
        """Find this device in the coordinator data."""
        if not self.coordinator.data:
            return None
        return next(
            (d for d in self.coordinator.data if d.get("idSystem") == self._device_id),
            None,
        )

    def _get_output_data(self, index: int) -> Optional[dict]:
        """Find an output by index in the device data."""
        device_data = self._get_device_data()
        if not device_data:
            return None
        return next(
            (o for o in device_data.get("outs", []) if o.get("index") == index),
            None,
        )

    def _get_params(self) -> Dict[str, Any]:
        """Get merged params + ExtraParams dict from device data."""
        device_data = self._get_device_data()
        if not device_data:
            return {}
        params = {}
        if isinstance(device_data.get("params"), dict):
            params.update(device_data["params"])
        if isinstance(device_data.get("ExtraParams"), dict):
            params.update(device_data["ExtraParams"])
        return params
