"""Sensor platform for the Klereo integration."""
import logging
from dataclasses import dataclass, field
from typing import Any

PARALLEL_UPDATES = 0

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
    SensorDeviceClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfPressure
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import PROBE_TYPES, CALCULATED_SENSORS, STATUS_SENSORS, CONTAINER_TRACKING, ALERT_CODES, VOLUME_DIVISOR
from .entity import KlereoEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class KlereoProbeSensorDescription(SensorEntityDescription):
    """Sensor entity description for a Klereo probe."""

    probe_type: int


PROBE_SENSOR_DESCRIPTIONS: dict[int, KlereoProbeSensorDescription] = {
    probe_type: KlereoProbeSensorDescription(
        key=pdef["id_key"],
        name=pdef["name"],
        translation_key=pdef["id_key"],
        probe_type=probe_type,
        native_unit_of_measurement=pdef.get("unit"),
        state_class=getattr(SensorStateClass, pdef["state_class"].upper()) if pdef.get("state_class") else None,
        device_class=getattr(SensorDeviceClass, pdef["device_class"].upper()) if pdef.get("device_class") else None,
        suggested_unit_of_measurement=(
            UnitOfTemperature.CELSIUS if pdef.get("device_class") == "temperature"
            else UnitOfPressure.MBAR if pdef.get("device_class") == "pressure"
            else None
        ),
    )
    for probe_type, pdef in PROBE_TYPES.items()
}


@dataclass(frozen=True, kw_only=True)
class KlereoCalculatedSensorDescription(SensorEntityDescription):
    """Sensor entity description for a Klereo calculated sensor."""

    formula: str
    debit_key: str | None = None
    time_key: str | None = None
    param_key: str | None = None
    round_digits: int = 2


CALCULATED_SENSOR_DESCRIPTIONS: tuple[KlereoCalculatedSensorDescription, ...] = tuple(
    KlereoCalculatedSensorDescription(
        key=sdef["id_key"],
        translation_key=sdef["id_key"],
        native_unit_of_measurement=sdef.get("unit"),
        state_class=getattr(SensorStateClass, sdef["state_class"].upper()) if sdef.get("state_class") else None,
        device_class=getattr(SensorDeviceClass, sdef["device_class"].upper()) if sdef.get("device_class") else None,
        entity_registry_enabled_default=sdef.get("enabled_default", True),
        formula=sdef["formula"],
        debit_key=sdef.get("debit_key"),
        time_key=sdef.get("time_key"),
        param_key=sdef.get("param_key"),
        round_digits=sdef.get("round_digits", 2),
    )
    for sdef in CALCULATED_SENSORS.values()
)


@dataclass(frozen=True, kw_only=True)
class KlereoStatusSensorDescription(SensorEntityDescription):
    """Sensor entity description for a Klereo status sensor."""

    param_key: str
    value_map: dict = field(default_factory=dict)


STATUS_SENSOR_DESCRIPTIONS: tuple[KlereoStatusSensorDescription, ...] = tuple(
    KlereoStatusSensorDescription(
        key=sdef["id_key"],
        translation_key=sdef["id_key"],
        param_key=param_key,
        value_map=sdef.get("value_map") or {},  # type: ignore[arg-type]
        entity_registry_enabled_default=sdef.get("enabled_default", True),
    )
    for param_key, sdef in STATUS_SENSORS.items()
)


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
    failed_count = 0

    def _safe_create(entity_cls, *args, **kwargs):
        """Create an entity, returning None on failure."""
        nonlocal failed_count
        try:
            return entity_cls(*args, **kwargs)
        except Exception:
            _LOGGER.warning(
                "Failed to create %s entity", entity_cls.__name__, exc_info=True
            )
            failed_count += 1
            return None

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

        # Probe sensors — detect duplicates by type
        probes = [p for p in device.get("probes", []) if p.get("type") in PROBE_SENSOR_DESCRIPTIONS]
        type_counts: dict[int, int] = {}
        for probe in probes:
            t = probe.get("type")
            type_counts[t] = type_counts.get(t, 0) + 1
        type_instance: dict[int, int] = {}
        for probe in probes:
            t = probe.get("type")
            type_instance[t] = type_instance.get(t, 0) + 1
            suffix = f" {type_instance[t]}" if type_counts.get(t, 0) > 1 else None
            desc = PROBE_SENSOR_DESCRIPTIONS[t]  # type: ignore[index]
            entity = _safe_create(KlereoProbeSensor, coordinator, device, desc, probe.get("index"), suffix)
            if entity is not None:
                sensors.append(entity)

        # Calculated sensors
        if "params" in device and isinstance(device["params"], dict):
            merged_params = {**device["params"]}
            if isinstance(device.get("ExtraParams"), dict):
                merged_params.update(device["ExtraParams"])
            for desc in CALCULATED_SENSOR_DESCRIPTIONS:
                if _calculated_sensor_has_data(merged_params, desc):
                    entity = _safe_create(KlereoCalculatedSensor, coordinator, device, desc)
                    if entity is not None:
                        sensors.append(entity)

        # Status sensors
        if "params" in device and isinstance(device["params"], dict):
            for desc in STATUS_SENSOR_DESCRIPTIONS:
                if desc.param_key in device["params"]:
                    entity = _safe_create(KlereoStatusSensor, coordinator, device, desc)
                    if entity is not None:
                        sensors.append(entity)

        # Container estimation sensors
        for ct_key, ct_def in CONTAINER_TRACKING.items():
            entity = _safe_create(KlereoContainerRemainingSensor, coordinator, device, entry, ct_key, ct_def)
            if entity is not None:
                sensors.append(entity)
            entity = _safe_create(KlereoContainerDaysRemainingSensor, coordinator, device, entry, ct_key, ct_def)
            if entity is not None:
                sensors.append(entity)

        # Alert sensors
        if "alerts" in device:
            entity = _safe_create(KlereoAlertCountSensor, coordinator, device)
            if entity is not None:
                sensors.append(entity)

    if failed_count > 0:
        _LOGGER.warning("%d sensor(s) failed to initialize and were skipped", failed_count)

    if sensors:
        async_add_entities(sensors)
        _LOGGER.debug("Added %d Klereo sensors", len(sensors))
    else:
        _LOGGER.info("No Klereo sensors to add.")


def _calculated_sensor_has_data(params: dict, description: KlereoCalculatedSensorDescription) -> bool:
    """Check if the params contain the required keys for a calculated sensor."""
    formula = description.formula
    if formula == "debit_time":
        return description.debit_key in params and description.time_key in params
    elif formula == "time_hours":
        return description.time_key in params
    elif formula in ("param_direct", "gram_production"):
        return description.param_key in params
    return False


class KlereoProbeSensor(KlereoEntity, SensorEntity):
    """Representation of a Klereo probe sensor."""

    entity_description: KlereoProbeSensorDescription

    def __init__(self, coordinator, device: dict, description: KlereoProbeSensorDescription, probe_index, suffix: str | None = None) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._probe_index = probe_index
        self._attr_unique_id = f"{self._device_id}_{description.key}_{probe_index}"
        if suffix:
            self._attr_name = (description.name or description.key) + suffix

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

    entity_description: KlereoCalculatedSensorDescription

    def __init__(self, coordinator, device: dict, description: KlereoCalculatedSensorDescription) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._attr_unique_id = f"{self._device_id}_{description.key}"

        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        new_value = None
        params = self._get_params()
        desc = self.entity_description
        formula = desc.formula

        try:
            if formula == "debit_time" and desc.debit_key and desc.time_key:
                debit_raw = params.get(desc.debit_key)
                time_raw = params.get(desc.time_key)
                if debit_raw is not None and time_raw is not None:
                    debit = float(debit_raw)
                    time_val = float(time_raw)
                    new_value = round((debit / VOLUME_DIVISOR) * time_val, desc.round_digits) if debit > 0 else 0.0

            elif formula == "time_hours" and desc.time_key:
                time_raw = params.get(desc.time_key)
                if time_raw is not None:
                    new_value = round(float(time_raw) / 3600.0, 2)

            elif formula == "param_direct" and desc.param_key:
                raw = params.get(desc.param_key)
                if raw is not None:
                    new_value = float(raw)

            elif formula == "gram_production" and desc.param_key:
                raw = params.get(desc.param_key)
                if raw is not None:
                    new_value = round(float(raw) / 1000.0, 2)

        except (ValueError, TypeError, KeyError) as e:
            _LOGGER.warning("[%s] Calculated sensor error: %s", self.unique_id, e)

        self._attr_native_value = new_value


class KlereoStatusSensor(KlereoEntity, SensorEntity):
    """Status/mode sensor that maps integer values to string labels."""

    entity_description: KlereoStatusSensorDescription

    def __init__(self, coordinator, device: dict, description: KlereoStatusSensorDescription) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._param_key = description.param_key
        self._value_map = description.value_map
        self._attr_unique_id = f"{self._device_id}_{description.key}"

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
        alerts_detail = []
        for alert in alerts:
            if isinstance(alert, dict):
                code = alert.get("code", 0)
                alerts_detail.append({
                    "code": code,
                    "description": ALERT_CODES.get(code, f"Alerte inconnue ({code})"),
                    "level": alert.get("level"),
                })
            else:
                alerts_detail.append({"description": str(alert)})
        self._attr_extra_state_attributes = {"alerts": alerts_detail}

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
        return (debit / VOLUME_DIVISOR) * time_val if debit > 0 else 0.0
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
        self._ct_key = ct_key
        self._ct_def = ct_def

        self._attr_translation_key = f"container_days_remaining_{ct_key}"
        self._attr_unique_id = f"{self._device_id}_container_days_remaining_{ct_key}"
        self._update_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        from datetime import datetime, timezone, date

        params = self._get_params()
        volume_total = _compute_volume(params, self._ct_def["debit_key"], self._ct_def["total_time_key"])
        if volume_total is None:
            self._attr_native_value = None
            return

        # Remaining volume
        options = self._entry.options
        capacity = float(options.get(self._ct_def["capacity_option"], self._ct_def["capacity_default"]))
        reset_at = float(options.get(self._ct_def["reset_option"], 0))
        remaining = capacity - (volume_total - reset_at)

        if remaining <= 0:
            self._attr_native_value = 0.0
            return

        # Rolling average over completed days only.
        # The last entry of daily_history is the in-progress day (cumulative
        # since midnight). Excluding it prevents a partial cumul from biasing
        # the average and causing intra-day sawtooth on the resulting estimate.
        history_key = f"{self._ct_key}_daily_history"
        history = options.get(history_key, [])
        today_str = date.today().isoformat()
        completed = [e for e in history if e.get("date") != today_str and "volume" in e]
        avg_completed = None
        if completed:
            avg_completed = sum(e["volume"] for e in completed) / len(completed)

        # Fallback: long-term average from installDate when no completed day yet.
        avg_long_term = None
        if avg_completed is None:
            device_data = self._get_device_data()
            install_ts = device_data.get("installDate") if device_data else None
            if install_ts:
                try:
                    install_date = datetime.fromtimestamp(int(install_ts), tz=timezone.utc)
                    days_since = (datetime.now(tz=timezone.utc) - install_date).total_seconds() / 86400
                    if days_since > 1 and volume_total > 0:
                        avg_long_term = volume_total / days_since
                except (ValueError, TypeError, OSError):
                    pass

        daily_rate = avg_completed if avg_completed is not None else avg_long_term

        # Negligible / unknown rate → return None rather than 9999d aberrations.
        if not daily_rate or daily_rate < 0.01:
            self._attr_native_value = None
            return

        self._attr_native_value = round(remaining / daily_rate, 1)
