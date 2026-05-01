"""Constants for the Klereo integration."""
from typing import Any

from homeassistant.const import Platform

DOMAIN = "klereo"
PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SELECT, Platform.SWITCH, Platform.NUMBER, Platform.BUTTON]

# --- Config flow constants ---
CONF_POOL_ID = "pool_id"
CONF_POOL_NAME = "pool_name"

# Volume formula divisor: Klereo API returns debit in cL/h, time in seconds.
# volume_liters = (debit_cL_per_h / 36000) * time_seconds
# 36000 = 100 (cL→L) * 3600 (h→s) / 10 (internal scaling)
VOLUME_DIVISOR = 36000.0

# Setpoint sentinel: API returns -1000 or -2000 when a setpoint is disabled/inactive
SETPOINT_DISABLED_THRESHOLD = -1000

# Default off delay in minutes for timer/pulse lighting modes
DEFAULT_OFF_DELAY_MINUTES = 30

# --- API Endpoints ---
BASE_URL = "https://connect.klereo.fr"
GET_JWT_ENDPOINT = "/php/GetJWT.php"
GET_INDEX_ENDPOINT = "/php/GetIndex.php"
GET_POOL_DETAILS_ENDPOINT = "/php/GetPoolDetails.php"
SET_OUTPUT_ENDPOINT = "/php/SetOut.php"
SET_AUTO_OFF_ENDPOINT = "/php/SetAutoOff.php"
SET_SCHEDULE_ENDPOINT = "/php/SetPlages.php"
SET_PARAM_ENDPOINT = "/php/SetParam.php"

# --- Output mode codes ---
OUTPUT_MODE_MANUAL = 0
OUTPUT_MODE_SCHEDULE = 1
OUTPUT_MODE_TIMER = 2
OUTPUT_MODE_AUTO = 3
OUTPUT_MODE_SYNC_FILTER = 4
OUTPUT_MODE_PULSE = 8

# --- Output state codes ---
OUTPUT_STATE_OFF = 0
OUTPUT_STATE_ON = 1
OUTPUT_STATE_SCHEDULE = 2
OUTPUT_STATE_SPEED_3 = 3
OUTPUT_STATE_AUTO = 15

# --- Lighting flags ---
# 6721 = Klereo web app custom flags for timer/pulse lighting modes (reverse-engineered)
LIGHTING_FLAGS = {"custFlags": 6721, "otherFlags": 0}

# --- Output type names (16 types, index-based) ---
OUTPUT_NAMES = {
    0: "Lighting",
    1: "Filtration",
    2: "pH Minus",
    3: "pH Plus",
    4: "Chlorine",
    5: "Electrolysis",
    6: "Heating",
    7: "Auxiliary 1",
    8: "Auxiliary 2",
    9: "Auxiliary 3",
    10: "Auxiliary 4",
    11: "Cover",
    12: "Counter Current",
    13: "Alarm",
    14: "Water Fill",
    15: "Backwash",
}

# --- Probe types (14 types matching ha-klereo) ---
# type_id -> {name, id_key, unit, icon, state_class, device_class}
PROBE_TYPES: dict[int, dict[str, Any]] = {
    0: {
        "name": "Tech Room Temp",
        "id_key": "tech_room_temp",
        "unit": "°C",
        "icon": "mdi:thermometer",
        "state_class": "measurement",
        "device_class": "temperature",
    },
    1: {
        "name": "Air Temp",
        "id_key": "air_temp",
        "unit": "°C",
        "icon": "mdi:thermometer-lines",
        "state_class": "measurement",
        "device_class": "temperature",
    },
    2: {
        "name": "Water Level",
        "id_key": "water_level",
        "unit": None,
        "icon": "mdi:waves-arrow-up",
        "state_class": "measurement",
    },
    3: {
        "name": "pH",
        "id_key": "ph",
        "unit": None,
        "icon": "mdi:ph",
        "state_class": "measurement",
    },
    4: {
        "name": "Redox",
        "id_key": "redox",
        "unit": "mV",
        "icon": "mdi:chemical-weapon",
        "state_class": "measurement",
    },
    5: {
        "name": "Water Temp",
        "id_key": "water_temp",
        "unit": "°C",
        "icon": "mdi:thermometer",
        "state_class": "measurement",
        "device_class": "temperature",
    },
    6: {
        "name": "Pressure",
        "id_key": "pressure",
        "unit": "mbar",
        "icon": "mdi:gauge",
        "state_class": "measurement",
        "device_class": "pressure",
    },
    7: {
        "name": "Generic",
        "id_key": "generic",
        "unit": None,
        "icon": "mdi:chart-line",
        "state_class": "measurement",
    },
    8: {
        "name": "Flow",
        "id_key": "flow",
        "unit": "L/h",
        "icon": "mdi:water-pump",
        "state_class": "measurement",
    },
    9: {
        "name": "Container Level",
        "id_key": "container_level",
        "unit": "%",
        "icon": "mdi:cup-water",
        "state_class": "measurement",
    },
    10: {
        "name": "Cover Position",
        "id_key": "cover_pos",
        "unit": "%",
        "icon": "mdi:window-shutter",
        "state_class": "measurement",
    },
    11: {
        "name": "Chlorine",
        "id_key": "chlorine",
        "unit": "mg/L",
        "icon": "mdi:flask-outline",
        "state_class": "measurement",
    },
    12: {
        "name": "Conductivity",
        "id_key": "conductivity",
        "unit": "µS/cm",
        "icon": "mdi:flash-outline",
        "state_class": "measurement",
    },
    13: {
        "name": "TDS",
        "id_key": "tds",
        "unit": "ppm",
        "icon": "mdi:water-opacity",
        "state_class": "measurement",
    },
}

# --- Calculated sensor definitions ---
# key -> {name, id_key, unit, icon, state_class, device_class, formula}
# formula: "debit_time" = (debit/36000)*time, "time_hours" = seconds/3600, "param_direct" = raw param value, "gram_production" = value/1000
CALCULATED_SENSORS: dict[str, dict[str, Any]] = {
    "ph_volume_today": {
        "name": "pH Volume Today",
        "id_key": "ph_volume_today",
        "unit": "L",
        "icon": "mdi:flask-minus-outline",
        "state_class": "total_increasing",
        "formula": "debit_time",
        "debit_key": "PHMinus_Debit",
        "time_key": "PHMinus_TodayTime",
        "round_digits": 3,
    },
    "ph_volume_total": {
        "name": "pH Volume Total",
        "id_key": "ph_volume_total",
        "unit": "L",
        "icon": "mdi:flask-minus",
        "state_class": "total_increasing",
        "formula": "debit_time",
        "debit_key": "PHMinus_Debit",
        "time_key": "PHMinus_TotalTime",
        "round_digits": 1,
    },
    "ph_max_daily_volume": {
        "name": "pH Max Daily Volume",
        "id_key": "ph_max_daily_volume",
        "unit": "mL",
        "icon": "mdi:gauge-high",
        "state_class": "measurement",
        "formula": "param_direct",
        "param_key": "VolumePH_PerDay",
        "enabled_default": False,
    },
    "chlorine_volume_today": {
        "name": "Chlorine Volume Today",
        "id_key": "chlorine_volume_today",
        "unit": "L",
        "icon": "mdi:flask-plus-outline",
        "state_class": "total_increasing",
        "formula": "debit_time",
        "debit_key": "Chlore_Debit",
        "time_key": "HybChl_TodayTime",
        "round_digits": 3,
    },
    "chlorine_volume_total": {
        "name": "Chlorine Volume Total",
        "id_key": "chlorine_volume_total",
        "unit": "L",
        "icon": "mdi:flask-plus",
        "state_class": "total_increasing",
        "formula": "debit_time",
        "debit_key": "Chlore_Debit",
        "time_key": "HybChl_TotalTime",
        "round_digits": 1,
    },
    "filtration_today_time": {
        "name": "Filtration Time Today",
        "id_key": "filtration_today_time",
        "unit": "h",
        "icon": "mdi:clock-outline",
        "state_class": "total_increasing",
        "device_class": "duration",
        "formula": "time_hours",
        "time_key": "Filtration_TodayTime",
    },
    "filtration_total_time": {
        "name": "Filtration Time Total",
        "id_key": "filtration_total_time",
        "unit": "h",
        "icon": "mdi:clock-check-outline",
        "state_class": "total_increasing",
        "device_class": "duration",
        "formula": "time_hours",
        "time_key": "Filtration_TotalTime",
    },
    "heating_today_time": {
        "name": "Heating Time Today",
        "id_key": "heating_today_time",
        "unit": "h",
        "icon": "mdi:radiator",
        "state_class": "total_increasing",
        "device_class": "duration",
        "formula": "time_hours",
        "time_key": "Chauffage_TodayTime",
    },
    "heating_total_time": {
        "name": "Heating Time Total",
        "id_key": "heating_total_time",
        "unit": "h",
        "icon": "mdi:radiator",
        "state_class": "total_increasing",
        "device_class": "duration",
        "formula": "time_hours",
        "time_key": "Chauffage_TotalTime",
    },
    "chlorine_run_today_time": {
        "name": "Chlorine Run Time Today",
        "id_key": "chlorine_run_today_time",
        "unit": "h",
        "icon": "mdi:clock-outline",
        "state_class": "total_increasing",
        "device_class": "duration",
        "formula": "time_hours",
        "time_key": "HybChl_TodayTime",
    },
    "chlorine_run_total_time": {
        "name": "Chlorine Run Time Total",
        "id_key": "chlorine_run_total_time",
        "unit": "h",
        "icon": "mdi:clock-check-outline",
        "state_class": "total_increasing",
        "device_class": "duration",
        "formula": "time_hours",
        "time_key": "HybChl_TotalTime",
    },
    "electrolysis_gram_production": {
        "name": "Electrolysis Production",
        "id_key": "elec_gram_production",
        "unit": "g",
        "icon": "mdi:scale",
        "state_class": "total_increasing",
        "formula": "gram_production",
        "param_key": "Elec_GramDone",
    },
}

# --- Status sensor definitions ---
# Maps param key -> {name, id_key, icon, value_map}
STATUS_SENSORS = {
    "PoolMode": {
        "name": "Pool Mode",
        "id_key": "pool_mode",
        "icon": "mdi:pool",
        "enabled_default": False,
        "value_map": {
            0: "Stop",
            1: "Summer",
            2: "Winter",
            3: "Away",
        },
    },
    "TraitMode": {
        "name": "Treatment Mode",
        "id_key": "treatment_mode",
        "icon": "mdi:water-plus",
        "enabled_default": False,
        "value_map": {
            0: "Stop",
            1: "Auto",
            2: "Manual",
            8: "Hybrid",
        },
    },
    "pHMode": {
        "name": "pH Mode",
        "id_key": "ph_mode",
        "icon": "mdi:ph",
        "enabled_default": False,
        "value_map": {
            0: "Stop",
            1: "Auto",
            2: "Manual",
        },
    },
    "HeaterMode": {
        "name": "Heater Mode",
        "id_key": "heater_mode",
        "icon": "mdi:radiator",
        "enabled_default": False,
        "value_map": {
            0: "Stop",
            1: "Auto",
            2: "Cooling",
            3: "Heating",
        },
    },
}

# --- Setpoint definitions ---
# param_key -> {name, id_key, unit, min, max, step, icon}
SETPOINT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "ConsigneEau": {
        "name": "Water Temp Setpoint",
        "id_key": "setpoint_water_temp",
        "unit": "°C",
        "min": 10.0,
        "max": 40.0,
        "step": 0.5,
        "icon": "mdi:thermometer-water",
    },
    "ConsignePH": {
        "name": "pH Setpoint",
        "id_key": "setpoint_ph",
        "unit": None,
        "min": 6.0,
        "max": 8.0,
        "step": 0.1,
        "icon": "mdi:ph",
    },
    "ConsigneRedox": {
        "name": "Redox Setpoint",
        "id_key": "setpoint_redox",
        "unit": "mV",
        "min": 400,
        "max": 900,
        "step": 10,
        "icon": "mdi:chemical-weapon",
    },
    "ConsigneChlore": {
        "name": "Chlorine Setpoint",
        "id_key": "setpoint_chlorine",
        "unit": "mg/L",
        "min": 0.0,
        "max": 5.0,
        "step": 0.1,
        "icon": "mdi:flask-outline",
    },
}

# --- Output translation keys (for icons.json / strings.json) ---
OUTPUT_TRANSLATION_KEYS = {
    0: "output_lighting",
    1: "output_filtration",
    2: "output_ph_minus",
    3: "output_ph_plus",
    4: "output_chlorine",
    5: "output_electrolysis",
    6: "output_heating",
    7: "output_auxiliary_1",
    8: "output_auxiliary_2",
    9: "output_auxiliary_3",
    10: "output_auxiliary_4",
    11: "output_cover",
    12: "output_counter_current",
    13: "output_alarm",
    14: "output_water_fill",
    15: "output_backwash",
}

# --- Heating mode constants ---
HEATING_MODE_OPTIONS = ["off", "auto", "cooling", "heating"]
HEATING_MODE_TO_VALUE = {
    "off": 0,
    "auto": 1,
    "cooling": 2,
    "heating": 3,
}
HEATING_VALUE_TO_MODE = {v: k for k, v in HEATING_MODE_TO_VALUE.items()}
HEATING_OUTPUT_INDEX = 6

# --- Alert codes (reverse-engineered from Klereo app) ---
ALERT_CODES = {
    10: "Sonde temperature eau deconnectee",
    11: "Sonde pH deconnectee",
    12: "Sonde redox deconnectee",
    13: "Sonde pression deconnectee",
    20: "pH trop bas",
    21: "pH trop haut",
    22: "Redox trop bas",
    23: "Redox trop haut",
    30: "Pression filtre basse",
    31: "Pression filtre haute",
    40: "Volume pH journalier depasse",
    41: "Volume traitement journalier depasse",
    50: "Erreur communication tableau",
    51: "Erreur communication afficheur",
    60: "Ecran de la pompe verrouille",
    70: "Sel insuffisant",
    80: "Temperature hors gel",
}

# --- Container tracking definitions (for reset buttons) ---
CONTAINER_TRACKING: dict[str, dict[str, Any]] = {
    "ph_minus": {
        "id_key": "reset_ph_container",
        "debit_key": "PHMinus_Debit",
        "total_time_key": "PHMinus_TotalTime",
        "today_time_key": "PHMinus_TodayTime",
        "reset_option": "ph_container_reset_at",
        "reset_date_option": "ph_container_reset_date",
        "capacity_option": "ph_container_capacity",
        "capacity_default": 20.0,
        "capacity_min": 1.0,
        "capacity_max": 200.0,
        "capacity_step": 0.5,
    },
    "chlorine": {
        "id_key": "reset_chlorine_container",
        "debit_key": "Chlore_Debit",
        "total_time_key": "HybChl_TotalTime",
        "today_time_key": "HybChl_TodayTime",
        "reset_option": "chlorine_container_reset_at",
        "reset_date_option": "chlorine_container_reset_date",
        "capacity_option": "chlorine_container_capacity",
        "capacity_default": 25.0,
        "capacity_min": 1.0,
        "capacity_max": 200.0,
        "capacity_step": 0.5,
    },
}
