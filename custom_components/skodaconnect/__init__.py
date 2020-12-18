    # -*- coding: utf-8 -*-
import logging
from datetime import date, datetime, timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_RESOURCES,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.helpers import discovery
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.icon import icon_for_battery_level
from homeassistant.util.dt import utcnow
from skodaconnect import Connection

from .const import DOMAIN

__version__ = "1.0.18-test"
_LOGGER = logging.getLogger(__name__)

#DOMAIN = "skodaconnect"
DATA_KEY = DOMAIN
#CONF_REGION = "region" # Not needed?
#DEFAULT_REGION = "CZ" # Not needed?
CONF_MUTABLE = "mutable"
CONF_SPIN = "spin"
CONF_DEFAULTCLIMATISATIONDURATION = "climatisation_duration"
CONF_SCANDINAVIAN_MILES = "scandinavian_miles"
CONF_IMPERIAL_UNITS = "imperial_units"

SIGNAL_STATE_UPDATED = f"{DOMAIN}.updated"

MIN_UPDATE_INTERVAL = timedelta(minutes=1)
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=5)

COMPONENTS = {
    "sensor": "sensor",
    "binary_sensor": "binary_sensor",
    "lock": "lock",
    "device_tracker": "device_tracker",
    "switch": "switch",
    "climate": "climate",
}

RESOURCES = [
    "nickname",
    "deactivated",
    "position",
    "distance",
    "last_connected",
    "outside_temperature",
    "window_heater",
    "climatisation_target_temperature",
    "climatisation_without_external_power",
    "electric_climatisation",
    "auxiliary_climatisation",
    "pheater_climatisation",
    "pheater_heating",
    "pheater_status",
    "external_power",
    "energy_flow",
    "charging",
    "charge_max_ampere",
    "charging_time_left",
    "charging_cable_connected",
    "charging_cable_locked",
    "adblue_level",
    "battery_level",
    "fuel_level",
    "electric_range",
    "combustion_range",
    "combined_range",
    "parking_light",
    "door_locked",
    "door_closed_left_front",
    "door_closed_right_front",
    "door_closed_left_back",
    "door_closed_right_back",
    "trunk_locked",
    "trunk_closed",
    "hood_closed",
    "windows_closed",
    "window_closed_left_front",
    "window_closed_right_front",
    "window_closed_left_back",
    "window_closed_right_back",
    "sunroof_closed",
    "trip_last_average_speed",
    "trip_last_average_electric_consumption",
    "trip_last_average_fuel_consumption",
    "trip_last_duration",
    "trip_last_length",
    "service_inspection",
    "oil_inspection",
    "service_inspection_distance",
    "oil_inspection_distance",
    "request_in_progress",
    "requests_remaining",
    "request_result",
    "pheater_duration",
]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                #vol.Optional(CONF_REGION, default=DEFAULT_REGION): cv.string,
                vol.Optional(CONF_MUTABLE, default=True): cv.boolean,
                vol.Optional(CONF_SPIN, default=""): cv.string,
                vol.Optional(CONF_DEFAULTCLIMATISATIONDURATION, default=30): vol.In([10,20,30,40,50,60]),
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): (
                    vol.All(cv.time_period, vol.Clamp(min=MIN_UPDATE_INTERVAL))
                ),
                # vol.Optional(CONF_NAME, default={}): vol.Schema(
                #     {cv.slug: cv.string}),
                vol.Optional(CONF_NAME, default={}): cv.schema_with_slug_keys(
                    cv.string
                ),
                vol.Optional(CONF_RESOURCES): vol.All(
                    cv.ensure_list, [vol.In(RESOURCES)]
                ),
                vol.Optional(CONF_SCANDINAVIAN_MILES, default=False): cv.boolean,
                vol.Optional(CONF_IMPERIAL_UNITS, default=False): cv.boolean,
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

TIMER = vol.Schema(
    {
                vol.Required("id"): vol.In([1,2,3]),
                vol.Optional("recurring"): vol.All(
                    cv.ensure_list, [
                        vol.In(["mon","tue","wed","thu","fri","sat","sun"])
                    ]
                ),
                vol.Optional("single"): cv.date,
                vol.Optional("departureTimeOfDay"): cv.time,
                vol.Optional("operationCharging"): cv.boolean,
                vol.Optional("chargeMaxCurrent"): vol.In(["Max", "Reduced"]),
                vol.Optional("targetChargeLevel"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
                vol.Optional("operationClimatisation"): cv.boolean,
                vol.Optional("heaterSource"): vol.In(["electric","automatic"]),
                vol.Optional("timerProgrammedStatus", default="programmed"): vol.In(["notProgrammed","programmed"]),
    }, extra=vol.ALLOW_EXTRA
)
SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_SET_PHEATER_DURATION = "set_pheater_duration"
SERVICE_SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("vin"): cv.string,
        vol.Optional("temp"): vol.In([16,17,18,19,20,21,22,23,24,25,26,27,28,29,30]),
        vol.Optional("timers"):
            vol.All(
                cv.ensure_list, [vol.All(TIMER)]
            )
    }
)
SERVICE_SET_PHEATER_DURATION_SCHEMA = vol.Schema(
    {
        vol.Required("vin"): cv.string,
        vol.Required("duration"): vol.In([10,20,30,40,50,60]),
    }
)


async def async_setup(hass, config):
    """Setup skoda connect component"""
    session = async_get_clientsession(hass)

    _LOGGER.info(f"Starting Skoda Connect, version {__version__}")
    _LOGGER.debug("Creating connection to skoda connect")
    connection = Connection(
        session=session,
        username=config[DOMAIN].get(CONF_USERNAME),
        password=config[DOMAIN].get(CONF_PASSWORD),
    )
    skodaconn = connection

    interval = config[DOMAIN].get(CONF_SCAN_INTERVAL)
    data = hass.data[DATA_KEY] = SkodaData(config)

    def is_enabled(attr):
        """Return true if the user has enabled the resource."""
        return attr in config[DOMAIN].get(CONF_RESOURCES, [attr])

    async def schedule_prepare(call):
        _LOGGER.debug("Prepare data from service call: %s" % call.data)
        # Prepare data in a way that service can accept
        servicedata = [{"timerBasicSetting": {}}, {}, {}, {}]
        mask = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

        # Convert temperature (if set) to Kelvin and multiply by 10
        if call.data.get("temp", False):
            servicedata[0]["timerBasicSetting"] = {"targetTemperature": int((call.data.get("temp") + 273)*10)}

        for timer in call.data['timers']:
            days = []
            schedule = []
            id = timer["id"]
            servicedata[id] = timer

            # Convert Max/Reduced to corresponding int values
            if timer.get('chargeMaxCurrent', False):
                if timer['chargeMaxCurrent'] == 'Max':
                   timer['chargeMaxCurrent'] = 254
                elif timer['chargeMaxCurrent'] == 'Reduced':
                   timer['chargeMaxCurrent'] = 252
            # Prepare recurring/single data conversion
            time = timer.get("departureTimeOfDay", "08:00")
            # Recurring schedule
            if timer.get("recurring", False):
                timer["departureTimeOfDay"] = time.strftime("%H:%M")
                timer["timerFrequency"] = "cyclic"
                timer["departureWeekdayMask"] = ""
                for day in timer.get("recurring"):
                    days.append(mask[day.lower()])
                for i in range(0,7):
                    timer["departureWeekdayMask"] += "y" if i in days else "n"
            # Single fire date
            else:
                now_date = date.today()
                now_time = datetime.now().time()
                schedule_time = timer.get("departureTimeOfDay", datetime.now().time())
                schedule_date = call.data.get("single") if call.data.get("single", False) else date.today()
                timer["departureTimeOfDay"] = "00:00"
                timer["timerFrequency"] = "single"
                if schedule_date <= now_date:
                    if now_time >= schedule_time:
                        schedule_date = now_date + timedelta(days=1)
                    else:
                        schedule_date = now_date
                schedule_datetime = datetime.combine(schedule_date, schedule_time)
                timer["departureDateTime"] = schedule_datetime.strftime("%Y-%m-%dT%H:%M")

        _LOGGER.debug("Successfully prepared data: %s" % servicedata)
        try:
            vin = call.data.get("vin")
            _LOGGER.debug("Try to fetch object for VIN: %s" % vin)
            car = connection.vehicle(vin)
            _LOGGER.debug("Executing set schedule")
            result = await car.set_schedule(servicedata)
            async_dispatcher_send(hass, SIGNAL_STATE_UPDATED)
        except Exception as err:
            _LOGGER.warning("Couldn't execute, error: %s" % err)
            async_dispatcher_send(hass, SIGNAL_STATE_UPDATED)
            return False
        return False

    async def set_pheater_duration(call):
        try:
            _LOGGER.debug("Try to fetch object for VIN: %s" % call.data.get("vin", ""))
            vin = call.data.get("vin")
            car = connection.vehicle(vin)
            _LOGGER.debug("Found car: %s" % car.nickname)
            _LOGGER.debug("Set climatisation duration to: %s" % call.data.get("duration", 0))
            car.pheater_duration = call.data.get("duration")
            async_dispatcher_send(hass, SIGNAL_STATE_UPDATED)
        except Exception as err:
            _LOGGER.warning("Couldn't execute, error: %s" % err)
            async_dispatcher_send(hass, SIGNAL_STATE_UPDATED)
            return False
        return False

    def discover_vehicle(vehicle):
        """Load relevant platforms."""
        data.vehicles.add(vehicle.vin)

        dashboard = vehicle.dashboard(
            mutable=config[DOMAIN][CONF_MUTABLE],
            spin=config[DOMAIN][CONF_SPIN],
            scandinavian_miles=config[DOMAIN][CONF_SCANDINAVIAN_MILES],
            climatisation_duration=config[DOMAIN][CONF_DEFAULTCLIMATISATIONDURATION],
            imperial_units=config[DOMAIN][CONF_IMPERIAL_UNITS],
        )

        for instrument in (
            instrument
            for instrument in dashboard.instruments
            if instrument.component in COMPONENTS and is_enabled(instrument.slug_attr)
        ):

            data.instruments.add(instrument)
            hass.async_create_task(
                discovery.async_load_platform(
                    hass,
                    COMPONENTS[instrument.component],
                    DOMAIN,
                    (vehicle.vin, instrument.component, instrument.attr),
                    config,
                )
            )

    async def update(now):
        """Update status from skoda connect"""
        try:
            # check if we can login
            if not connection.logged_in:
                await connection._login()
                if not connection.logged_in:
                    _LOGGER.warning(
                        "Could not login to skoda connect, please check your credentials and verify that the service is working"
                    )
                    return False

            # update vehicles
            if not await connection.update():
                _LOGGER.warning("Could not query update from skoda connect")
                return False

            _LOGGER.debug("Updating data from skoda connect")
            for vehicle in connection.vehicles:
                if vehicle.vin not in data.vehicles:
                    _LOGGER.info(f"Adding data for VIN: {vehicle.vin}")
                    discover_vehicle(vehicle)

            async_dispatcher_send(hass, SIGNAL_STATE_UPDATED)
            return True

        finally:
            async_track_point_in_utc_time(hass, update, utcnow() + interval)

    _LOGGER.info("Starting skodaconnect component")

    # Register HASS Service calls
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        schedule_prepare,
        schema=SERVICE_SET_SCHEDULE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PHEATER_DURATION,
        set_pheater_duration,
        schema=SERVICE_SET_PHEATER_DURATION_SCHEMA
    )

    return await update(utcnow())


class SkodaData:
    """Hold component state."""

    def __init__(self, config):
        """Initialize the component state."""
        self.vehicles = set()
        self.instruments = set()
        self.config = config[DOMAIN]
        self.names = self.config.get(CONF_NAME)

    def instrument(self, vin, component, attr):
        """Return corresponding instrument."""
        return next(
            (
                instrument
                for instrument in self.instruments
                if instrument.vehicle.vin == vin
                and instrument.component == component
                and instrument.attr == attr
            ),
            None,
        )

    def vehicle_name(self, vehicle):
        """Provide a friendly name for a vehicle."""
        if vehicle.vin and vehicle.vin.lower() in self.names:
            return self.names[vehicle.vin.lower()]
        elif vehicle.is_nickname_supported:
            return vehicle.nickname
        elif vehicle.vin:
            return vehicle.vin
        else:
            return ""


class SkodaEntity(Entity):
    """Base class for all Skoda entities."""

    def __init__(self, data, vin, component, attribute):
        """Initialize the entity."""
        self.data = data
        self.vin = vin
        self.component = component
        self.attribute = attribute

    async def async_added_to_hass(self):
        """Register update dispatcher."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_STATE_UPDATED, self.async_write_ha_state
            )
        )

    @property
    def instrument(self):
        """Return corresponding instrument."""
        return self.data.instrument(self.vin, self.component, self.attribute)

    @property
    def icon(self):
        """Return the icon."""
        if self.instrument.attr in ["battery_level", "charging"]:
            return icon_for_battery_level(
                battery_level=self.instrument.state, charging=self.vehicle.charging
            )
        else:
            return self.instrument.icon

    @property
    def vehicle(self):
        """Return vehicle."""
        return self.instrument.vehicle

    @property
    def _entity_name(self):
        return self.instrument.name

    @property
    def _vehicle_name(self):
        return self.data.vehicle_name(self.vehicle)

    @property
    def name(self):
        """Return full name of the entity."""
        return f"{self._vehicle_name} {self._entity_name}"

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def assumed_state(self):
        """Return true if unable to access real state of entity."""
        return True

    @property
    def device_state_attributes(self):
        """Return device specific state attributes."""
        return dict(
            self.instrument.attributes,
            model=f"{self.vehicle.model}/{self.vehicle.model_year}",
        )

    @property
    def device_info(self):
        """Return the device_info of the device."""
        return {
            "identifiers": {(DOMAIN, self.vin)},
            "name": self._vehicle_name,
            "manufacturer": "Skoda",
            "model": self.vehicle.model,
            "sw_version": self.vehicle.model_year,
        }

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self.vin}-{self.component}-{self.attribute}"
