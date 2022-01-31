from datetime import timedelta

DOMAIN = "seatconnect"
DATA_KEY = DOMAIN

# Configuration definitions
DEFAULT_DEBUG = False
CONF_MUTABLE = "mutable"
CONF_SPIN = "spin"
CONF_SCANDINAVIAN_MILES = "scandinavian_miles"
CONF_IMPERIAL_UNITS = "imperial_units"
CONF_NO_CONVERSION = "no_conversion"
CONF_CONVERT = "convert"
CONF_VEHICLE = "vehicle"
CONF_INSTRUMENTS = "instruments"
CONF_DEBUG = "debug"

# Service definitions
SERVICE_SET_SCHEDULE = "set_departure_schedule"
SERVICE_SET_MAX_CURRENT = "set_charger_max_current"
SERVICE_SET_CHARGE_LIMIT = "set_charge_limit"
SERVICE_SET_CLIMATER = "set_climater"
SERVICE_SET_PHEATER_DURATION = "set_pheater_duration"

UPDATE_CALLBACK = "update_callback"
DATA = "data"
UNDO_UPDATE_LISTENER = "undo_update_listener"

SIGNAL_STATE_UPDATED = f"{DOMAIN}.updated"

MIN_SCAN_INTERVAL = 10
DEFAULT_SCAN_INTERVAL = 60

CONVERT_DICT = {
    CONF_NO_CONVERSION: "No conversion",
    CONF_IMPERIAL_UNITS: "Imperial units",
    CONF_SCANDINAVIAN_MILES: "km to mil",
}

PLATFORMS = {
    "sensor": "sensor",
    "binary_sensor": "binary_sensor",
    "lock": "lock",
    "device_tracker": "device_tracker",
    "switch": "switch",
    "climate": "climate",
}