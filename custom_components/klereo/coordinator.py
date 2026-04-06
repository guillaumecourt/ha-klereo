"""Data update coordinator for the Klereo integration."""
import logging
from datetime import date, timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, CONTAINER_TRACKING
from .api import KlereoApi

_LOGGER = logging.getLogger(__name__)


class KlereoDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator for managing Klereo data updates."""

    def __init__(self, hass: HomeAssistant, api: KlereoApi, update_interval: timedelta):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)
        self.api = api
        self._previous_alert_count: dict[int, int] = {}

    async def _async_update_data(self):
        """Fetch data from the API."""
        try:
            _LOGGER.debug("Updating Klereo data.")
            data = await self.api.async_get_pool_details()

            if not data:
                _LOGGER.warning("No data received from Klereo API.")
                return []

            _LOGGER.debug("Klereo data updated: %d device(s).", len(data))

            # Detect new alerts
            for device in data:
                device_id = device.get("idSystem")
                if not device_id:
                    continue
                current_count = device.get("alertCount", 0)
                previous_count = self._previous_alert_count.get(device_id, 0)
                if current_count > previous_count:
                    await self._notify_new_alerts(device, current_count - previous_count)
                self._previous_alert_count[device_id] = current_count

            # Record daily container volumes for 7-day sliding average
            self._update_daily_history(data)

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

    async def _notify_new_alerts(self, device: dict, new_count: int) -> None:
        """Send notifications when new alerts are detected."""
        pool_name = device.get("poolNickname", "Klereo")
        device_id = device.get("idSystem")
        alert_count = device.get("alertCount", 0)
        alerts = device.get("alerts", [])

        if alerts:
            messages = [a.get("message", str(a)) if isinstance(a, dict) else str(a) for a in alerts]
            message = f"{new_count} nouvelle(s) alerte(s) sur {pool_name}:\n" + "\n".join(f"- {m}" for m in messages)
        else:
            message = f"{new_count} nouvelle(s) alerte(s) sur {pool_name}"

        _LOGGER.warning("Klereo alert: %s", message)

        # Persistent notification
        await self.hass.services.async_call(
            "persistent_notification", "create",
            {"title": "Klereo - Alerte", "message": message,
             "notification_id": f"klereo_alert_{device_id}"},
        )

        # Mobile push (notify.notify sends to all devices)
        try:
            await self.hass.services.async_call(
                "notify", "notify",
                {"title": "Klereo - Alerte", "message": message},
            )
        except Exception:
            _LOGGER.debug("Mobile notification service not available")

        # HA event for automations
        self.hass.bus.async_fire("klereo_alert", {
            "device_id": device_id,
            "pool_name": pool_name,
            "alert_count": alert_count,
            "new_alerts": new_count,
        })

    def _update_daily_history(self, data: list) -> None:
        """Record daily container consumption for 7-day sliding average."""
        if not getattr(self, "config_entry", None):
            return

        today_str = date.today().isoformat()
        new_options = {**self.config_entry.options}
        changed = False

        for device in data:
            params = {**device.get("params", {})}
            if isinstance(device.get("ExtraParams"), dict):
                params.update(device["ExtraParams"])

            for ct_key, ct_def in CONTAINER_TRACKING.items():
                history_key = f"{ct_key}_daily_history"
                history = list(self.config_entry.options.get(history_key, []))

                # Compute today's volume
                debit_raw = params.get(ct_def["debit_key"])
                time_raw = params.get(ct_def["today_time_key"])
                if debit_raw is None or time_raw is None:
                    continue
                try:
                    volume_today = (float(debit_raw) / 36000.0) * float(time_raw)
                except (ValueError, TypeError):
                    continue

                # Update or add today's entry
                if history and history[-1].get("date") == today_str:
                    history[-1]["volume"] = round(volume_today, 3)
                else:
                    history.append({"date": today_str, "volume": round(volume_today, 3)})

                # Keep only last 7 days
                history = history[-7:]
                new_options[history_key] = history
                changed = True

        if changed:
            self.hass.config_entries.async_update_entry(
                self.config_entry, options=new_options
            )
