"""Sensor platform for the Klereo integration."""
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
    SensorDeviceClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfPressure
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import PROBE_TYPES, CALCULATED_SENSORS, STATUS_SENSORS, CONTAINER_TRACKING
from .entity import KlereoEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Klereo sensors."""
    _LOGGER.debug("Setting up Klereo sensors for entry: %s", entry.entry_id)
    coordinator = entry.runtime_data

    if not coordinator.data:
        _LOGGER.warning("No data for sensors.")
        return

    sensors: list[SensorEntity] = []

    for device in coordinator.data:
        device_id = device.get("idSystem")
        if not device_id:
            _LOGGER.error("Device data missing 'idSystem'.")
            continue

        try:
            str(int(device_id))
        except (ValueError, TypeError):
            _LOGGER.error("Invalid 'idSystem' format: %s.", device_id)
            continue

        # Probe sensors
        for probe in device.get("probes", []):
            if probe.get("type") in PROBE_TYPES:
                sensors.append(KlereoProbeSensor(coordinator, device, probe))

        # Calculated sensors
        if "params" in device and isinstance(device["params"], dict):
            merged_params = {**device["params"]}
            if isinstance(device.get("ExtraParams"), dict):
                merged_params.update(device["ExtraParams"])
            for sensor_key, sensor_def in CALCULATED_SENSORS.items():
                # Only add if the required params exist
                if _calculated_sensor_has_data(merged_params, sensor_def):
                    sensors.append(KlereoCalculatedSensor(coordinator, device, sensor_key, sensor_def))

        # Status sensors
        if "params" in device and isinstance(device["params"], dict):
            for param_key, status_def in STATUS_SENSORS.items():
                if param_key in device["params"]:
                    sensors.append(KlereoStatusSensor(coordinator, device, param_key, status_def))

        # Container estimation sensors
        for ct_key, ct_def in CONTAINER_TRACKING.items():
            sensors.append(KlereoContainerRemainingSensor(coordinator, device, entry, ct_key, ct_def))
            sensors.append(KlereoContainerDaysRemainingSensor(coordinator, device, entry, ct_key, ct_def))

        # Alert sensors
        if "alerts" in device:
            sensors.append(KlereoAlertCountSensor(coordinator, device))

    if sensors:
        async_add_entities(sensors)
        _LOGGER.info("Adding %d Klereo sensors", len(sensors))
    else:
        _LOGGER.info("No Klereo sensors to add.")


def _calculated_sensor_has_data(params: dict, sensor_def: dict) -> bool:
    """Check if the params contain the required keys for a calculated sensor."""
    formula = sensor_def.get("formula")
    if formula == "debit_time":
        return sensor_def.get("debit_key") in params and sensor_def.get("time_key") in params
    elif formula == "time_hours":
        return sensor_def.get("time_key") in params
    elif formula in ("param_direct", "gram_production"):
        return sensor_def.get("param_key") in params
    return False


class KlereoProbeSensor(KlereoEntity, SensorEntity):
    """Representation of a Klereo probe sensor."""

    def __init__(self, coordinator, device: dict, probe: dict) -> None:
        super().__init__(coordinator, device)
        self._probe = probe
        self._probe_index = probe.get("index", "N/A")
        probe_type = probe.get("type")
        probe_details = PROBE_TYPES[probe_type]

        self._attr_translation_key = probe_details["id_key"]
        self._attr_unique_id = f"{self._device_id}_{probe_details['id_key']}_{self._probe_index}"
        self._attr_native_unit_of_measurement = probe_details.get("unit")

        state_class = probe_details.get("state_class")
        if state_class:
            self._attr_state_class = getattr(SensorStateClass, state_class.upper(), state_class)

        device_class = probe_details.get("device_class")
        if device_class:
            self._attr_device_class = getattr(SensorDeviceClass, device_class.upper(), device_class)
            if device_class == "temperature":
                self._attr_suggested_unit_of_measurement = UnitOfTemperature.CELSIUS
            elif device_class == "pressure":
                self._attr_suggested_unit_of_measurement = UnitOfPressure.MBAR

        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        new_value = None
        device_data = self._get_device_data()
        if device_data:
            probe_data = next(
                (p for p in device_data.get("probes", []) if p.get("index") == self._probe_index),
                None,
            )
            if probe_data:
                # Prefer filteredValue over directValue
                raw_value = probe_data.get("filteredValue") or probe_data.get("directValue")
                if raw_value is not None:
                    try:
                        new_value = round(float(raw_value), 2)
                    except (ValueError, TypeError):
                        _LOGGER.warning("[%s] Probe: Cannot convert '%s' to float", self.unique_id, raw_value)
        self._attr_native_value = new_value


class KlereoCalculatedSensor(KlereoEntity, SensorEntity):
    """Data-driven calculated sensor."""

    def __init__(self, coordinator, device: dict, sensor_key: str, sensor_def: dict) -> None:
        super().__init__(coordinator, device)
        self._sensor_def = sensor_def

        self._attr_translation_key = sensor_def["id_key"]
        self._attr_unique_id = f"{self._device_id}_{sensor_def['id_key']}"
        self._attr_native_unit_of_measurement = sensor_def.get("unit")

        state_class = sensor_def.get("state_class")
        if state_class:
            self._attr_state_class = getattr(SensorStateClass, state_class.upper(), state_class)

        device_class = sensor_def.get("device_class")
        if device_class:
            self._attr_device_class = getattr(SensorDeviceClass, device_class.upper(), device_class)

        if not sensor_def.get("enabled_default", True):
            self._attr_entity_registry_enabled_default = False

        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        new_value = None
        params = self._get_params()
        formula = self._sensor_def.get("formula")

        try:
            if formula == "debit_time":
                debit_raw = params.get(self._sensor_def["debit_key"])
                time_raw = params.get(self._sensor_def["time_key"])
                if debit_raw is not None and time_raw is not None:
                    debit = float(debit_raw)
                    time_val = float(time_raw)
                    digits = self._sensor_def.get("round_digits", 2)
                    new_value = round((debit / 36000.0) * time_val, digits) if debit > 0 else 0.0

            elif formula == "time_hours":
                time_raw = params.get(self._sensor_def["time_key"])
                if time_raw is not None:
                    new_value = round(float(time_raw) / 3600.0, 2)

            elif formula == "param_direct":
                raw = params.get(self._sensor_def["param_key"])
                if raw is not None:
                    new_value = float(raw)

            elif formula == "gram_production":
                raw = params.get(self._sensor_def["param_key"])
                if raw is not None:
                    new_value = round(float(raw) / 1000.0, 2)

        except (ValueError, TypeError, KeyError) as e:
            _LOGGER.warning("[%s] Calculated sensor error: %s", self.unique_id, e)

        self._attr_native_value = new_value


class KlereoStatusSensor(KlereoEntity, SensorEntity):
    """Status/mode sensor that maps integer values to string labels."""

    def __init__(self, coordinator, device: dict, param_key: str, status_def: dict) -> None:
        super().__init__(coordinator, device)
        self._param_key = param_key
        self._status_def = status_def
        self._value_map = status_def.get("value_map", {})

        self._attr_translation_key = status_def["id_key"]
        self._attr_unique_id = f"{self._device_id}_{status_def['id_key']}"

        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        new_value = None
        params = self._get_params()
        raw = params.get(self._param_key)
        if raw is not None:
            try:
                int_val = int(float(raw))
                new_value = self._value_map.get(int_val, f"Unknown ({int_val})")
            except (ValueError, TypeError):
                _LOGGER.warning("[%s] Status sensor: cannot convert '%s'", self.unique_id, raw)
        self._attr_native_value = new_value


class KlereoAlertCountSensor(KlereoEntity, SensorEntity):
    """Alert count sensor with messages as extra attributes."""

    def __init__(self, coordinator, device: dict) -> None:
        super().__init__(coordinator, device)
        self._attr_translation_key = "alert_count"
        self._attr_unique_id = f"{self._device_id}_alert_count"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        device_data = self._get_device_data()
        alerts = []
        if device_data:
            alerts = device_data.get("alerts", [])
        self._attr_native_value = len(alerts)
        self._attr_extra_state_attributes = {"messages": alerts}

    @property
    def extra_state_attributes(self) -> dict:
        return getattr(self, "_attr_extra_state_attributes", {})


def _compute_volume(params: dict, debit_key: str, time_key: str) -> float | None:
    """Compute volume in liters from debit and time params."""
    debit_raw = params.get(debit_key)
    time_raw = params.get(time_key)
    if debit_raw is None or time_raw is None:
        return None
    try:
        debit = float(debit_raw)
        time_val = float(time_raw)
        return (debit / 36000.0) * time_val if debit > 0 else 0.0
    except (ValueError, TypeError):
        return None


class KlereoContainerRemainingSensor(KlereoEntity, SensorEntity):
    """Sensor showing remaining volume in a container."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "L"

    def __init__(self, coordinator, device: dict, entry, ct_key: str, ct_def: dict) -> None:
        super().__init__(coordinator, device)
        self._entry = entry
        self._ct_def = ct_def

        self._attr_translation_key = f"container_remaining_{ct_key}"
        self._attr_unique_id = f"{self._device_id}_container_remaining_{ct_key}"
        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        params = self._get_params()
        volume_total = _compute_volume(params, self._ct_def["debit_key"], self._ct_def["total_time_key"])
        if volume_total is None:
            self._attr_native_value = None
            return

        options = self._entry.options
        capacity = float(options.get(self._ct_def["capacity_option"], self._ct_def["capacity_default"]))
        reset_at = float(options.get(self._ct_def["reset_option"], 0))

        consumed_since_reset = volume_total - reset_at
        remaining = round(capacity - consumed_since_reset, 2)
        self._attr_native_value = max(remaining, 0.0)


class KlereoContainerDaysRemainingSensor(KlereoEntity, SensorEntity):
    """Sensor estimating days until container needs replacement."""

    _attr_native_unit_of_measurement = "d"

    def __init__(self, coordinator, device: dict, entry, ct_key: str, ct_def: dict) -> None:
        super().__init__(coordinator, device)
        self._entry = entry
        self._ct_def = ct_def

        self._attr_translation_key = f"container_days_remaining_{ct_key}"
        self._attr_unique_id = f"{self._device_id}_container_days_remaining_{ct_key}"
        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        from datetime import datetime, timezone

        params = self._get_params()
        volume_total = _compute_volume(params, self._ct_def["debit_key"], self._ct_def["total_time_key"])
        volume_today = _compute_volume(params, self._ct_def["debit_key"], self._ct_def["today_time_key"])
        if volume_total is None:
            self._attr_native_value = None
            return

        # Remaining volume
        options = self._entry.options
        capacity = float(options.get(self._ct_def["capacity_option"], self._ct_def["capacity_default"]))
        reset_at = float(options.get(self._ct_def["reset_option"], 0))
        remaining = capacity - (volume_total - reset_at)

        if remaining <= 0:
            self._attr_native_value = 0
            return

        # Long-term average from installDate
        device_data = self._get_device_data()
        install_ts = device_data.get("installDate") if device_data else None
        avg_long_term = None
        if install_ts:
            try:
                install_date = datetime.fromtimestamp(int(install_ts), tz=timezone.utc)
                days_since = (datetime.now(tz=timezone.utc) - install_date).total_seconds() / 86400
                if days_since > 1 and volume_total > 0:
                    avg_long_term = volume_total / days_since
            except (ValueError, TypeError, OSError):
                pass

        # Weighted average: 70% today + 30% long-term
        if volume_today and volume_today > 0 and avg_long_term and avg_long_term > 0:
            weighted_avg = 0.7 * volume_today + 0.3 * avg_long_term
        elif avg_long_term and avg_long_term > 0:
            weighted_avg = avg_long_term
        elif volume_today and volume_today > 0:
            weighted_avg = volume_today
        else:
            self._attr_native_value = None
            return

        self._attr_native_value = round(remaining / weighted_avg, 1)
