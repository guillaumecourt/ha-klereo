"""Config flow for the Klereo integration."""
import aiohttp
import logging
import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, CONF_POOL_ID, CONF_POOL_NAME
from .api import KlereoApi

_LOGGER = logging.getLogger(__name__)


class KlereoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Klereo."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._username: str | None = None
        self._password: str | None = None
        self._title: str = "Klereo"
        self._pools: list[dict] = []

    async def async_step_user(self, user_input=None):
        """Handle the initial credentials step."""
        errors = {}
        if user_input is not None:
            if not user_input.get("password"):
                errors["password"] = "password_too_short"

            if not errors:
                await self.async_set_unique_id(user_input["username"].lower())
                self._abort_if_unique_id_configured()

                try:
                    api = KlereoApi(self.hass, user_input["username"], user_input["password"])
                    await api.async_get_token()
                except aiohttp.ClientConnectionError as e:
                    _LOGGER.error("Connection error to Klereo API: %s", e)
                    errors["base"] = "cannot_connect"
                except aiohttp.ClientResponseError as e:
                    if e.status == 401:
                        _LOGGER.warning("Klereo authentication failed")
                        errors["base"] = "invalid_auth"
                    else:
                        _LOGGER.error("Klereo API error: %s", e)
                        errors["base"] = "api_error"
                except (aiohttp.ClientError, ValueError, KeyError) as e:
                    _LOGGER.exception("Unexpected error during authentication: %s", e)
                    errors["base"] = "unknown_error"
                else:
                    self._username = user_input["username"]
                    self._password = user_input["password"]
                    self._title = user_input.get("title", "Klereo")

                    # Discover pools
                    try:
                        self._pools = await api.async_get_pools()
                    except (aiohttp.ClientError, ValueError, KeyError) as err:
                        _LOGGER.warning("Failed to discover pools: %s", err)
                        self._pools = []

                    if len(self._pools) == 1:
                        # Single pool: auto-select
                        return self.async_create_entry(
                            title=self._pools[0]["name"],
                            data={
                                "username": self._username,
                                "password": self._password,
                                CONF_POOL_ID: self._pools[0]["id"],
                                CONF_POOL_NAME: self._pools[0]["name"],
                            },
                        )
                    elif len(self._pools) > 1:
                        return await self.async_step_pool()
                    else:
                        # No pools discovered: create entry without pool_id
                        return self.async_create_entry(
                            title=self._title,
                            data={
                                "username": self._username,
                                "password": self._password,
                            },
                        )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("username"): str,
                    vol.Required("password"): str,
                    vol.Optional("title", default="Klereo"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_pool(self, user_input=None):
        """Handle pool selection step."""
        if user_input is not None:
            selected_pool_id = user_input[CONF_POOL_ID]
            pool = next((p for p in self._pools if p["id"] == selected_pool_id), None)
            pool_name = pool["name"] if pool else f"Pool {selected_pool_id}"

            return self.async_create_entry(
                title=pool_name,
                data={
                    "username": self._username,
                    "password": self._password,
                    CONF_POOL_ID: selected_pool_id,
                    CONF_POOL_NAME: pool_name,
                },
            )

        pool_options = {p["id"]: p["name"] for p in self._pools}
        return self.async_show_form(
            step_id="pool",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POOL_ID): vol.In(pool_options),
                }
            ),
        )

    async def async_step_reauth(self, entry_data=None):
        """Handle re-authentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Handle re-auth confirmation."""
        errors = {}
        if user_input is not None:
            try:
                api = KlereoApi(self.hass, user_input["username"], user_input["password"])
                await api.async_get_token()
            except aiohttp.ClientConnectionError:
                errors["base"] = "cannot_connect"
            except aiohttp.ClientResponseError as e:
                if e.status == 401:
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "api_error"
            except (aiohttp.ClientError, ValueError, KeyError):
                errors["base"] = "unknown_error"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={"username": user_input["username"], "password": user_input["password"]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("username"): str,
                    vol.Required("password"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfiguration to change pool selection."""
        entry = self._get_reconfigure_entry()
        errors = {}

        if user_input is not None:
            selected_pool_id = user_input[CONF_POOL_ID]
            pool = next((p for p in self._pools if p["id"] == selected_pool_id), None)
            pool_name = pool["name"] if pool else f"Pool {selected_pool_id}"

            return self.async_update_reload_and_abort(
                entry,
                data_updates={
                    CONF_POOL_ID: selected_pool_id,
                    CONF_POOL_NAME: pool_name,
                },
            )

        # Discover pools using existing credentials
        try:
            api = KlereoApi(self.hass, entry.data["username"], entry.data["password"])
            await api.async_get_token()
            self._pools = await api.async_get_pools()
        except (aiohttp.ClientError, ValueError, KeyError) as err:
            _LOGGER.error("Failed to discover pools during reconfigure: %s", err)
            return self.async_abort(reason="cannot_connect")

        if len(self._pools) <= 1:
            return self.async_abort(reason="single_pool")

        pool_options = {p["id"]: p["name"] for p in self._pools}
        current_pool_id = entry.data.get(CONF_POOL_ID)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_POOL_ID, default=current_pool_id): vol.In(pool_options),
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return KlereoOptionsFlowHandler()


class KlereoOptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}

        if user_input is not None:
            new_username = user_input.get("username", "")
            new_password = user_input.get("password", "")

            credentials_changed = (
                new_username != self.config_entry.data.get("username")
                or new_password != self.config_entry.data.get("password")
            )

            if credentials_changed and new_username and new_password:
                try:
                    api = KlereoApi(self.hass, new_username, new_password)
                    await api.async_get_token()
                except aiohttp.ClientConnectionError:
                    errors["base"] = "cannot_connect"
                except aiohttp.ClientResponseError as e:
                    if e.status == 401:
                        errors["base"] = "invalid_auth"
                    else:
                        errors["base"] = "api_error"
                except (aiohttp.ClientError, ValueError, KeyError):
                    errors["base"] = "unknown_error"

            if not errors:
                new_options = {"update_interval": user_input["update_interval"]}

                if credentials_changed and new_username and new_password:
                    new_data = {
                        **self.config_entry.data,
                        "username": new_username,
                        "password": new_password,
                    }
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=new_data, options=new_options
                    )
                    await self.hass.config_entries.async_reload(
                        self.config_entry.entry_id
                    )
                    return self.async_abort(reason="reauth_successful")

                return self.async_create_entry(title="Options", data=new_options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "username",
                        default=self.config_entry.data.get("username", ""),
                    ): str,
                    vol.Required(
                        "password",
                        default=self.config_entry.data.get("password", ""),
                    ): str,
                    vol.Required(
                        "update_interval",
                        default=self.config_entry.options.get("update_interval", 15),
                    ): vol.All(int, vol.Range(min=1)),
                }
            ),
            errors=errors,
        )
