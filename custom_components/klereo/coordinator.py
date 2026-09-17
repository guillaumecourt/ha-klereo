"""Data update coordinator for the Klereo integration."""
import logging
from datetime import datetime, timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue, async_delete_issue
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, CONTAINER_TRACKING, ALERT_CODES, VOLUME_DIVISOR
from .api import KlereoApi, KlereoServiceUnavailableError, KlereoSessionExpiredError

STALE_DEVICE_THRESHOLD = 3
# Consecutive session rejections tolerated before asking the user to re-auth.
# ConfigEntryAuthFailed stops polling until the user acts, so a transient
# server-side rejection must not be enough to trigger it.
AUTH_FAILURE_THRESHOLD = 3
# Consecutive failed updates before telling the user the data stopped coming.
# Klereo runs a nightly maintenance window that costs a single cycle and heals
# itself, so notifying on the first failure would fire almost every night.
FAILURE_NOTIFY_THRESHOLD = 2

NOTIFICATION_ID_LOST = "klereo_connection_lost"
NOTIFICATION_ID_RESTORED = "klereo_connection_restored"

_LOGGER = logging.getLogger(__name__)


def _format_duration(delta: timedelta) -> str:
    """Render an outage length the way a person would say it."""
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {minutes:02d}"
    days, hours = divmod(hours, 24)
    return f"{days} j {hours} h"


class KlereoDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator for managing Klereo data updates."""

    def __init__(self, hass: HomeAssistant, api: KlereoApi, update_interval: timedelta):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)
        self.api = api
        self._previous_alert_count: dict[int, int] = {}
        self._absent_device_count: dict[str, int] = {}
        self._consecutive_auth_failures = 0
        self._consecutive_failures = 0
        self._unavailable_since: datetime | None = None
        self._loss_notified = False
        self._had_success = False

    def _raise_auth_rejection(self, err: Exception, reason: str) -> None:
        """Escalate a rejected session, but only once it proves persistent.

        The API client already retried with a freshly minted JWT before we get
        here. ConfigEntryAuthFailed suspends polling until the user completes a
        reauth flow, so a one-off server-side rejection must stay an
        UpdateFailed: the coordinator then keeps retrying and recovers on its
        own when the service comes back.
        """
        self._consecutive_auth_failures += 1
        if self._consecutive_auth_failures < AUTH_FAILURE_THRESHOLD:
            _LOGGER.warning(
                "Klereo rejected the session (%s) - attempt %d/%d, retrying",
                reason,
                self._consecutive_auth_failures,
                AUTH_FAILURE_THRESHOLD,
            )
            raise UpdateFailed(f"Klereo session rejected ({reason})") from err
        async_create_issue(
            self.hass,
            DOMAIN,
            "auth_expired",
            is_fixable=False,
            is_persistent=True,
            severity=IssueSeverity.ERROR,
            translation_key="auth_expired",
        )
        raise ConfigEntryAuthFailed(f"Klereo session rejected ({reason})") from err

    async def _async_update_data(self):
        """Fetch data, tracking availability transitions for the user.

        The fetch itself lives in _async_fetch_data, which raises from five
        different places; wrapping it gives a single point to notice that the
        data stopped -- and started again -- without instrumenting each one.
        """
        try:
            data = await self._async_fetch_data()
        except Exception as err:
            await self._handle_unavailable(err)
            raise
        await self._handle_available()
        return data

    async def _handle_unavailable(self, err: Exception) -> None:
        """Notify once the data has been missing for long enough to matter."""
        self._consecutive_failures += 1
        if self._unavailable_since is None:
            self._unavailable_since = dt_util.now()

        if not self._had_success:
            # A failure on the very first refresh is already surfaced by HA as
            # ConfigEntryNotReady; a notification on top would just be noise.
            return
        if self._loss_notified or self._consecutive_failures < FAILURE_NOTIFY_THRESHOLD:
            return

        self._loss_notified = True
        message = (
            "Les donnees de la piscine ne remontent plus.\n"
            f"Cause : {err}\n\n"
            "L'integration continue d'essayer de se reconnecter."
        )
        _LOGGER.warning("Klereo data unavailable for %d cycles: %s", self._consecutive_failures, err)
        await self._notify(
            "create",
            {"title": "Klereo - Donnees indisponibles", "message": message,
             "notification_id": NOTIFICATION_ID_LOST},
        )

    async def _handle_available(self) -> None:
        """Close the outage and report how long it lasted."""
        self._had_success = True
        was_notified = self._loss_notified
        started_at = self._unavailable_since
        self._consecutive_failures = 0
        self._unavailable_since = None
        self._loss_notified = False

        if not was_notified:
            return

        duration = _format_duration(dt_util.now() - started_at) if started_at else None
        message = "Les donnees de la piscine remontent a nouveau."
        if duration:
            message += f"\nInterruption : {duration}."
        _LOGGER.info("Klereo data available again (outage: %s)", duration or "unknown")

        await self._notify("dismiss", {"notification_id": NOTIFICATION_ID_LOST})
        await self._notify(
            "create",
            {"title": "Klereo - Connexion retablie", "message": message,
             "notification_id": NOTIFICATION_ID_RESTORED},
        )

    async def _notify(self, service: str, payload: dict) -> None:
        """Call persistent_notification without ever masking the real error.

        _handle_unavailable runs inside an `except` block: an exception raised
        here would replace the fetch failure the caller is about to re-raise.
        """
        try:
            await self.hass.services.async_call("persistent_notification", service, payload)
        except Exception:  # noqa: BLE001 - notifications are never worth a crash
            _LOGGER.debug("persistent_notification.%s failed", service, exc_info=True)

    async def _async_fetch_data(self):
        """Fetch data from the API."""
        try:
            _LOGGER.debug("Updating Klereo data.")
            data = await self.api.async_get_pool_details()
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                self._raise_auth_rejection(err, f"HTTP {err.status}")
            async_create_issue(
                self.hass,
                DOMAIN,
                "api_unreachable",
                is_fixable=False,
                is_persistent=False,
                severity=IssueSeverity.WARNING,
                translation_key="api_unreachable",
            )
            raise UpdateFailed(f"API error (HTTP {err.status}): {err}") from err
        except KlereoServiceUnavailableError as err:
            # Klereo maintenance window (typically nightly): transient, entities
            # come back on their own — no repair issue, no auth flow.
            _LOGGER.warning("Klereo service temporarily unavailable: %s", err)
            raise UpdateFailed(f"Klereo service unavailable: {err}") from err
        except KlereoSessionExpiredError as err:
            # Raised only after a JWT renewal was already attempted and the API
            # still rejected the session.
            self._raise_auth_rejection(err, str(err))
        except Exception as err:
            _LOGGER.error("Error communicating with Klereo API", exc_info=True)
            async_create_issue(
                self.hass,
                DOMAIN,
                "api_unreachable",
                is_fixable=False,
                is_persistent=False,
                severity=IssueSeverity.WARNING,
                translation_key="api_unreachable",
            )
            raise UpdateFailed(f"Error communicating with Klereo API: {err}") from err

        if not data:
            raise UpdateFailed("No data received from Klereo API.")

        _LOGGER.debug("Klereo data updated: %d device(s).", len(data))

        # Clear any previous repair issues on successful update
        self._consecutive_auth_failures = 0
        async_delete_issue(self.hass, DOMAIN, "auth_expired")
        async_delete_issue(self.hass, DOMAIN, "api_unreachable")

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

        # Track stale devices
        self._cleanup_stale_devices(data)

        return data

    async def _notify_new_alerts(self, device: dict, new_count: int) -> None:
        """Send notifications when new alerts are detected."""
        pool_name = device.get("poolNickname", "Klereo")
        device_id = device.get("idSystem")
        alert_count = device.get("alertCount", 0)
        alerts = device.get("alerts", [])

        if alerts:
            descriptions = []
            for a in alerts:
                if isinstance(a, dict):
                    code = a.get("code", 0)
                    descriptions.append(ALERT_CODES.get(code, f"Alerte inconnue ({code})"))
                else:
                    descriptions.append(str(a))
            message = f"Alerte(s) sur {pool_name} :\n" + "\n".join(f"- {d}" for d in descriptions)
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

        today_str = dt_util.now().date().isoformat()
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
                    debit_f = float(debit_raw)
                    time_f = float(time_raw)
                except (ValueError, TypeError):
                    continue

                # Read TodayTime snapshot saved at reset (Bug #1 fix).
                # When set, we subtract the pre-reset portion so the
                # current-day history entry only reflects post-reset usage.
                snapshot_key = ct_def.get("today_time_reset_option")
                snapshot_raw = (
                    new_options.get(snapshot_key) if snapshot_key else None
                )
                snapshot_f: float | None = None
                if snapshot_raw is not None:
                    try:
                        snapshot_f = float(snapshot_raw)
                    except (ValueError, TypeError):
                        snapshot_f = None

                # Rollover detection: pod resets TodayTime to 0 at its
                # local midnight. When TodayTime drops below the snapshot,
                # the snapshot is stale and must be cleared.
                if snapshot_f is not None and time_f < snapshot_f:
                    _LOGGER.debug(
                        "Container %s: TodayTime (%.0fs) < snapshot (%.0fs), "
                        "clearing snapshot (pod midnight rollover detected).",
                        ct_key, time_f, snapshot_f,
                    )
                    new_options[snapshot_key] = None
                    snapshot_f = None
                    changed = True

                effective_time = (
                    time_f - snapshot_f if snapshot_f is not None else time_f
                )
                volume_today = (debit_f / VOLUME_DIVISOR) * effective_time
                rounded_volume = round(volume_today, 3)

                # Update or add today's entry
                volume_changed = True
                if history and history[-1].get("date") == today_str:
                    if history[-1].get("volume") == rounded_volume:
                        volume_changed = False
                    else:
                        history[-1]["volume"] = rounded_volume
                else:
                    history.append({"date": today_str, "volume": rounded_volume})

                # Safety net: if a snapshot is still set but HA has crossed
                # a day since the reset, clear it. Defends against pod TZ
                # skew where the rollover detection above never fires. The
                # current poll's entry may be slightly off; subsequent polls
                # will self-correct (today's entry is overwritten each poll).
                snapshot_cleared_stale = False
                if snapshot_f is not None and ct_def.get("reset_date_option"):
                    reset_date_val = self.config_entry.options.get(
                        ct_def["reset_date_option"]
                    )
                    if isinstance(reset_date_val, str):
                        reset_day = reset_date_val.split("T", 1)[0]
                        if reset_day != today_str:
                            new_options[snapshot_key] = None
                            snapshot_cleared_stale = True
                            _LOGGER.debug(
                                "Container %s: HA day rolled since reset "
                                "(%s -> %s), clearing stale snapshot.",
                                ct_key, reset_day, today_str,
                            )

                if not volume_changed and not snapshot_cleared_stale:
                    # Nothing meaningful to persist this iteration.
                    continue

                # Keep only last 7 days
                history = history[-7:]
                new_options[history_key] = history
                changed = True
                _LOGGER.debug(
                    "Container %s daily history: date=%s volume=%.3fL snapshot=%s",
                    ct_key, today_str, rounded_volume, snapshot_f,
                )

        if changed:
            self.hass.config_entries.async_update_entry(
                self.config_entry, options=new_options
            )

    def _cleanup_stale_devices(self, data: list) -> None:
        """Remove devices from registry that are no longer reported by the API."""
        current_ids = {
            str(d.get("idSystem")) for d in data if d.get("idSystem")
        }

        # Track absent devices
        previously_tracked = set(self._absent_device_count.keys())
        for device_id in previously_tracked:
            if device_id in current_ids:
                self._absent_device_count.pop(device_id, None)
            else:
                self._absent_device_count[device_id] = (
                    self._absent_device_count.get(device_id, 0) + 1
                )

        # Check for newly absent devices (not previously tracked)
        if getattr(self, "data", None):
            old_ids = {
                str(d.get("idSystem")) for d in self.data if d.get("idSystem")
            }
            for device_id in old_ids - current_ids:
                if device_id not in self._absent_device_count:
                    self._absent_device_count[device_id] = 1

        # Remove devices exceeding threshold
        device_registry = dr.async_get(self.hass)
        for device_id, count in list(self._absent_device_count.items()):
            if count >= STALE_DEVICE_THRESHOLD:
                device_entry = device_registry.async_get_device(
                    identifiers={(DOMAIN, device_id)}
                )
                if device_entry:
                    _LOGGER.info(
                        "Removing stale device %s after %d consecutive absences",
                        device_id, count,
                    )
                    device_registry.async_remove_device(device_entry.id)
                self._absent_device_count.pop(device_id, None)
