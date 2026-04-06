"""Klereo API client."""
import aiohttp
import asyncio
import hashlib
import logging
import json
import re
import time
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .const import (
    BASE_URL,
    GET_JWT_ENDPOINT,
    GET_INDEX_ENDPOINT,
    GET_POOL_DETAILS_ENDPOINT,
    SET_OUTPUT_ENDPOINT,
    SET_AUTO_OFF_ENDPOINT,
    SET_SCHEDULE_ENDPOINT,
    SET_PARAM_ENDPOINT,
    OUTPUT_MODE_MANUAL,
    OUTPUT_MODE_SCHEDULE,
    OUTPUT_MODE_TIMER,
    OUTPUT_MODE_AUTO,
    OUTPUT_MODE_SYNC_FILTER,
    OUTPUT_MODE_PULSE,
    OUTPUT_STATE_OFF,
    OUTPUT_STATE_ON,
    OUTPUT_STATE_SCHEDULE,
    OUTPUT_STATE_SPEED_3,
    OUTPUT_STATE_AUTO,
    LIGHTING_FLAGS,
)

_LOGGER = logging.getLogger(__name__)
_SUCCESS_PATTERN = re.compile(r'\b(success|ok)\b', re.IGNORECASE)


def hash_password(password: str) -> str:
    """Hash password using SHA1."""
    try:
        return hashlib.sha1(password.encode("utf-8")).hexdigest()
    except Exception as e:
        _LOGGER.error("Error hashing password: %s", e)
        raise


def extract_jwt_from_html(html_content: str) -> Optional[str]:
    """Extract JWT token from HTML response."""
    try:
        # Try direct JSON parse first (server may return JSON with text/html content-type)
        try:
            parsed = json.loads(html_content)
            if isinstance(parsed, dict) and (jwt := parsed.get("jwt")):
                return jwt
        except (json.JSONDecodeError, AttributeError):
            pass

        # Fall back to extracting text from HTML
        soup = BeautifulSoup(html_content, "html.parser")
        if text_data := soup.get_text(strip=True):
            parsed_data = json.loads(text_data)
            if jwt := parsed_data.get("jwt"):
                return jwt
            _LOGGER.warning("Key 'jwt' missing in parsed HTML.")
        else:
            _LOGGER.warning("No JSON text found in HTML for JWT.")
    except Exception as err:
        _LOGGER.error("Error extracting JWT from HTML: %s", err)
    return None


async def handle_response(response: aiohttp.ClientResponse) -> Any:
    """Handle API response parsing."""
    _LOGGER.debug("Handling response: status=%s, content_type=%s", response.status, response.content_type)
    ctype = response.content_type or ""
    if ctype.startswith("application/json"):
        try:
            return await response.json()
        except json.JSONDecodeError as err:
            _LOGGER.error("Invalid JSON received: %s", await response.text(errors='ignore'))
            raise ValueError("Réponse JSON invalide.") from err
    elif ctype.startswith("text/html") or ctype.startswith("text/plain"):
        text = await response.text(errors='ignore')
        _LOGGER.debug("HTML/text response: %s", text[:200])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            _LOGGER.warning("HTML/text response not parsable as JSON.")
            if _SUCCESS_PATTERN.search(text):
                return {"success": True}
            return None
    else:
        _LOGGER.error("Unexpected API content type: %s", ctype)
        raise ValueError(f"Type contenu inattendu: {ctype}")


def _is_write_success(response_data: Any) -> bool:
    """Determine if a write API call succeeded."""
    if response_data is None:
        return False
    if isinstance(response_data, dict) and "success" in response_data:
        return bool(response_data["success"])
    return True


class KlereoApi:
    """Klereo API client."""

    def __init__(self, hass: HomeAssistant, username: str, password: str, pool_id: Optional[str] = None):
        self._hass = hass
        self.username = username
        self.hashed_password = hash_password(password)
        self.base_url = BASE_URL
        self.session = aiohttp_client.async_get_clientsession(hass)
        self.jwt_token = None
        self.pool_id = pool_id
        self._last_token_failure: float = 0.0
        self._TOKEN_COOLDOWN = 30  # seconds
        _LOGGER.debug("KlereoApi initialized (pool_id=%s)", pool_id)

    async def async_close(self) -> None:
        """No-op: HA manages the shared session."""
        _LOGGER.debug("KlereoApi async_close called (no-op with HA shared session)")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.async_close()

    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None, needs_auth: bool = True) -> Any:
        """Make an API request."""
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "User-Agent": "Mozilla/5.0 (HomeAssistant Klereo Integration)",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "X-Requested-With": "XMLHttpRequest",
        }
        if needs_auth:
            token = await self.async_ensure_token()
            if not token:
                raise ConnectionError("Invalid JWT token.")
            headers["Authorization"] = f"Bearer {token}"
            if method.upper() == "POST" and data is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        _LOGGER.debug("Request: Method=%s, URL=%s, Data=%s", method, url, data)
        try:
            async with self.session.request(method, url, headers=headers, data=data, params=params, timeout=20) as response:
                _LOGGER.debug("Response Status: %s", response.status)
                response.raise_for_status()
                return await handle_response(response)
        except aiohttp.ClientResponseError as err:
            _LOGGER.error("API error: URL=%s, Status=%s, Error=%s", url, err.status, err.message)
            if err.status in [401, 403]:
                self.jwt_token = None
            raise
        except asyncio.TimeoutError:
            _LOGGER.error("API timeout: %s", url)
            raise ConnectionError(f"API timeout: {url}")
        except aiohttp.ClientConnectionError as err:
            _LOGGER.error("API connection error: %s", err)
            raise ConnectionError(f"Connection error: {err}") from err
        except Exception as e:
            _LOGGER.exception("Unexpected API error: %s", e)
            raise

    # --- Authentication ---

    async def async_ensure_token(self) -> Optional[str]:
        """Ensure JWT token is valid, fetching if needed."""
        if self.jwt_token is None:
            now = time.monotonic()
            if now - self._last_token_failure < self._TOKEN_COOLDOWN:
                _LOGGER.debug("Token fetch on cooldown, skipping.")
                return None
            _LOGGER.debug("JWT token missing, fetching.")
            try:
                self.jwt_token = await self.async_get_token()
                if self.jwt_token:
                    _LOGGER.info("New JWT token obtained.")
                else:
                    self._last_token_failure = now
                    _LOGGER.error("Failed to obtain JWT token.")
            except Exception as e:
                self._last_token_failure = now
                _LOGGER.error("Exception fetching JWT token: %s", e)
                self.jwt_token = None
        return self.jwt_token

    async def async_get_token(self) -> Optional[str]:
        """Fetch JWT token from the Klereo API."""
        url = f"{self.base_url}{GET_JWT_ENDPOINT}"
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }
        payload = {
            "login": self.username,
            "password": self.hashed_password,
            "version": "392-W",
            "app": "Web",
        }
        _LOGGER.debug("Requesting JWT token from %s", url)
        try:
            async with self.session.post(url, data=payload, headers=headers, timeout=15) as response:
                _LOGGER.debug("JWT response: status=%s, content_type=%s", response.status, response.content_type)
                response.raise_for_status()
                jwt = None
                ctype = response.content_type or ""
                if ctype.startswith("application/json"):
                    data = await response.json()
                    jwt = data.get("jwt")
                elif ctype.startswith("text/html"):
                    jwt = extract_jwt_from_html(await response.text())
                else:
                    _LOGGER.error("Unexpected content type (JWT): %s", response.content_type)
                if not jwt:
                    _LOGGER.error("JWT token not found in response.")
                return jwt
        except Exception as e:
            if isinstance(e, aiohttp.ClientResponseError) and e.status in [401, 403]:
                _LOGGER.error("Klereo authentication failed (check login/password). Status: %s", e.status)
            else:
                _LOGGER.exception("Error fetching JWT: %s", e)
        return None

    # --- Pool discovery ---

    async def async_get_pools(self) -> List[Dict[str, Any]]:
        """Discover pools via GetIndex.php. Returns [{id, name}]."""
        _LOGGER.info("Discovering pools via GetIndex...")
        try:
            response_data = await self._request("POST", GET_INDEX_ENDPOINT, data={}, needs_auth=True)
            if isinstance(response_data, dict) and "response" in response_data:
                pools = []
                for pool in response_data["response"]:
                    if isinstance(pool, dict):
                        # API may use idPool, idSystem, or id as the pool identifier
                        pool_id = pool.get("idPool") or pool.get("idSystem") or pool.get("id")
                        if pool_id is not None:
                            pool_id_str = str(pool_id).strip()
                            if pool_id_str:
                                pool_name = pool.get("poolNickname") or pool.get("name") or f"Pool {pool_id_str}"
                                pools.append({"id": pool_id_str, "name": pool_name})
                            else:
                                _LOGGER.debug("Pool entry with empty id: %s", list(pool.keys())[:10])
                        else:
                            _LOGGER.debug("Pool entry without id: %s", list(pool.keys())[:10])
                if response_data["response"]:
                    _LOGGER.debug("Discovered %d pool(s). Raw keys: %s",
                                  len(pools),
                                  list(response_data["response"][0].keys())[:10])
                else:
                    _LOGGER.debug("Discovered 0 pools (empty response list).")
                return pools
            _LOGGER.warning("Unexpected GetIndex response structure: %s", type(response_data))
            return []
        except Exception as err:
            _LOGGER.error("Failed to discover pools: %s", err)
            raise

    # --- Pool data ---

    async def async_get_pool_details(self) -> list:
        """Get pool details via GetPoolDetails.php."""
        if not self.pool_id:
            _LOGGER.error("No pool_id configured.")
            return []
        _LOGGER.info("Fetching pool details for pool_id=%s", self.pool_id)
        payload = {"poolID": self.pool_id, "lang": "fr"}
        try:
            response_data = await self._request("POST", GET_POOL_DETAILS_ENDPOINT, data=payload, needs_auth=True)
            if isinstance(response_data, dict) and "response" in response_data:
                if isinstance(response_data["response"], list):
                    _LOGGER.debug("Received data for %d device(s).", len(response_data["response"]))
                    return response_data["response"]
                _LOGGER.warning("'response' is not a list.")
            else:
                _LOGGER.error("Unexpected GetPoolDetails response structure: %s", type(response_data))
            return []
        except Exception as err:
            _LOGGER.error("Failed GetPoolDetails: %s", err)
            raise

    async def async_get_index(self) -> list:
        """Alias for async_get_pool_details (backward compatibility)."""
        return await self.async_get_pool_details()

    # --- Write helper ---

    async def _write_request(self, endpoint: str, payload: dict, description: str) -> bool:
        """Execute a write API request. Returns True on success, False on failure."""
        if not self.pool_id:
            _LOGGER.error("No pool_id configured for %s.", description)
            return False
        payload["poolID"] = self.pool_id
        payload["comMode"] = 1
        try:
            response_data = await self._request("POST", endpoint, data=payload, needs_auth=True)
            success = _is_write_success(response_data)
            if success:
                _LOGGER.info("%s call succeeded.", description)
            else:
                _LOGGER.warning("%s returned None/empty.", description)
            return success
        except Exception as err:
            _LOGGER.error("Failed %s: %s", description, err)
            return False

    # --- Output control ---

    async def async_set_output_mode_and_state(
        self,
        output_index: int,
        mode: int,
        state: int,
        custom_flags: Optional[int] = None,
        other_flags: Optional[int] = None,
    ) -> bool:
        """Set output mode and state via SetOut.php."""
        _LOGGER.info("SetOut: outIdx=%d, mode=%d, state=%d", output_index, mode, state)
        payload = {
            "outIdx": output_index,
            "newMode": mode,
            "newState": state,
        }
        if custom_flags is not None:
            payload["custFlags"] = custom_flags
        if other_flags is not None:
            payload["otherFlags"] = other_flags
        return await self._write_request(SET_OUTPUT_ENDPOINT, payload, "SetOut.php")

    async def async_set_output_auto_off(self, output_index: int, off_delay: int) -> bool:
        """Set auto-off delay via SetAutoOff.php."""
        _LOGGER.info("SetAutoOff: outIdx=%d, offDelay=%d", output_index, off_delay)
        payload = {"outIdx": output_index, "offDelay": off_delay}
        return await self._write_request(SET_AUTO_OFF_ENDPOINT, payload, "SetAutoOff.php")

    async def async_set_output_schedule(self, plan_index: int, slots: str) -> bool:
        """Set schedule via SetPlages.php."""
        _LOGGER.info("SetPlages: planIdx=%d, slots=%s", plan_index, slots)
        payload = {"planIdx": plan_index, "slots": slots}
        return await self._write_request(SET_SCHEDULE_ENDPOINT, payload, "SetPlages.php")

    # --- Parameter control ---

    async def async_set_param(self, param_name: str, value: Any) -> bool:
        """Set a parameter via SetParam.php."""
        _LOGGER.info("SetParam: param=%s, value=%s", param_name, value)
        payload = {"paramName": param_name, "paramValue": value}
        return await self._write_request(SET_PARAM_ENDPOINT, payload, "SetParam.php")
