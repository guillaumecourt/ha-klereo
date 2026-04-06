"""Diagnostics platform for the Klereo integration."""
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

REDACT_KEYS = {"jwt", "password", "token", "login", "username"}


def _redact_data(data: Any) -> Any:
    """Recursively redact sensitive data."""
    if isinstance(data, dict):
        return {
            k: "**REDACTED**" if k.lower() in REDACT_KEYS else _redact_data(v)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_redact_data(item) for item in data]
    return data


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = getattr(entry, "runtime_data", None)

    return {
        "config_entry": _redact_data(dict(entry.data)),
        "coordinator_data": _redact_data(coordinator.data if coordinator else None),
    }
