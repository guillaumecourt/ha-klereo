"""Data update coordinator for the Klereo integration."""
import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .api import KlereoApi

_LOGGER = logging.getLogger(__name__)


class KlereoDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator for managing Klereo data updates."""

    def __init__(self, hass: HomeAssistant, api: KlereoApi, update_interval: timedelta):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)
        self.api = api

    async def _async_update_data(self):
        """Fetch data from the API."""
        try:
            _LOGGER.debug("Updating Klereo data.")
            data = await self.api.async_get_pool_details()

            if not data:
                _LOGGER.warning("No data received from Klereo API.")
                return []

            _LOGGER.debug("Klereo data updated: %d device(s).", len(data))
            return data

        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                raise ConfigEntryAuthFailed(
                    f"Authentication failed (HTTP {err.status})"
                ) from err
            raise UpdateFailed(f"API error (HTTP {err.status}): {err}") from err
        except Exception as err:
            _LOGGER.error("Error communicating with Klereo API", exc_info=True)
            raise UpdateFailed(f"Error communicating with Klereo API: {err}") from err
