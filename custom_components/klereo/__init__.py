"""The Klereo integration."""
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import PLATFORMS, CONF_POOL_ID, CONF_POOL_NAME
from .api import KlereoApi
from .coordinator import KlereoDataUpdateCoordinator

KlereoConfigEntry = ConfigEntry

_LOGGER = logging.getLogger(__name__)

MIGRATION_VERSION = 2


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entry from older version."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        new_data = {**config_entry.data}

        if CONF_POOL_ID not in new_data:
            # Try to discover pool via API
            try:
                api = KlereoApi(hass, new_data["username"], new_data["password"])
                pools = await api.async_get_pools()
                if pools:
                    new_data[CONF_POOL_ID] = pools[0]["id"]
                    new_data[CONF_POOL_NAME] = pools[0]["name"]
                    _LOGGER.info("Migration: discovered pool %s (%s)", pools[0]["id"], pools[0]["name"])
                else:
                    _LOGGER.warning("Migration: no pools discovered, entry may need reconfiguration.")
            except Exception as err:
                _LOGGER.warning("Migration: failed to discover pools: %s. Entry may need reconfiguration.", err)

        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)
        _LOGGER.info("Migration to version 2 successful")

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Klereo from a config entry."""
    _LOGGER.debug("Initializing async_setup_entry for entry: %s", entry.entry_id)

    if "username" not in entry.data or "password" not in entry.data:
        _LOGGER.error("Invalid config data (username/password missing)")
        return False

    pool_id = entry.data.get(CONF_POOL_ID)
    api = KlereoApi(hass, entry.data["username"], entry.data["password"], pool_id=pool_id)
    raw_interval = entry.options.get("update_interval", 15)
    # Migration: old values were in seconds (>= 60), new values are in minutes
    if raw_interval >= 60:
        raw_interval = raw_interval // 60
    update_interval = timedelta(minutes=raw_interval)

    coordinator = KlereoDataUpdateCoordinator(
        hass=hass,
        api=api,
        update_interval=update_interval,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady from err

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Klereo integration for entry: %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        try:
            await entry.runtime_data.api.async_close()
            _LOGGER.debug("Klereo API session closed.")
        except Exception as e:
            _LOGGER.warning("Error closing Klereo API session: %s", e)

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug("Updating Klereo options for entry: %s", entry.entry_id)
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator:
        new_interval_minutes = entry.options.get("update_interval", 15)
        coordinator.update_interval = timedelta(minutes=new_interval_minutes)
        _LOGGER.debug("Coordinator update interval set to %s minutes", new_interval_minutes)
