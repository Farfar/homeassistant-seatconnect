# -*- coding: utf-8 -*-
"""
Seat Connect integration

Read more at https://github.com/farfar/homeassistant-seatconnect/
"""
import re
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Union
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, SOURCE_REAUTH, SOURCE_IMPORT
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_RESOURCES,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME, EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.icon import icon_for_battery_level
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from seatconnect import Connection
from seatconnect.vehicle import Vehicle
from seatconnect.exceptions import (
    SeatConfigException,
    SeatAuthenticationException,
    SeatAccountLockedException,
    SeatTokenExpiredException,
    SeatException,
    SeatEULAException,
    SeatThrottledException,
    SeatLoginFailedException,
    SeatInvalidRequestException,
    SeatRequestInProgressException
)

from .const import (
    PLATFORMS,
    CONF_MUTABLE,
    CONF_SCANDINAVIAN_MILES,
    CONF_SPIN,
    CONF_VEHICLE,
    CONF_INSTRUMENTS,
    DATA,
    DATA_KEY,
    MIN_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SIGNAL_STATE_UPDATED,
    UNDO_UPDATE_LISTENER, UPDATE_CALLBACK, CONF_DEBUG, DEFAULT_DEBUG, CONF_CONVERT, CONF_NO_CONVERSION,
    CONF_IMPERIAL_UNITS,
    SERVICE_SET_SCHEDULE,
    SERVICE_SET_MAX_CURRENT,
    SERVICE_SET_CHARGE_LIMIT,
    SERVICE_SET_CLIMATER,
    SERVICE_SET_PHEATER_DURATION,
)

SERVICE_SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): vol.All(cv.string, vol.Length(min=32, max=32)),
        vol.Required("id"): vol.In([1,2,3]),
        vol.Required("time"): cv.string,
        vol.Required("enabled"): cv.boolean,
        vol.Required("recurring"): cv.boolean,
        vol.Optional("date"): cv.string,
        vol.Optional("days"): cv.string,
        vol.Optional("temp"): vol.All(vol.Coerce(int), vol.Range(min=16, max=30)),
        vol.Optional("climatisation"): cv.boolean,
        vol.Optional("charging"): cv.boolean,
        vol.Optional("charge_current"): vol.Any(
            vol.Range(min=1, max=254),
            vol.In(['Maximum', 'maximum', 'Max', 'max', 'Minimum', 'minimum', 'Min', 'min', 'Reduced', 'reduced'])
        ),
        vol.Optional("charge_target"): vol.In([0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
        vol.Optional("off_peak_active"): cv.boolean,
        vol.Optional("off_peak_start"): cv.string,
        vol.Optional("off_peak_end"): cv.string,
    }
)
SERVICE_SET_MAX_CURRENT_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): vol.All(cv.string, vol.Length(min=32, max=32)),
        vol.Required("current"): vol.Any(
            vol.Range(min=1, max=255),
            vol.In(['Maximum', 'maximum', 'Max', 'max', 'Minimum', 'minimum', 'Min', 'min', 'Reduced', 'reduced'])
        ),
    }
)
SERVICE_SET_CHARGE_LIMIT_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): vol.All(cv.string, vol.Length(min=32, max=32)),
        vol.Required("limit"): vol.In([0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
    }
)
SERVICE_SET_CLIMATER_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): vol.All(cv.string, vol.Length(min=32, max=32)),
        vol.Required("enabled", default=True): cv.boolean,
        vol.Optional("temp"): vol.All(vol.Coerce(int), vol.Range(min=16, max=30)),
        vol.Optional("battery_power"): cv.boolean,
        vol.Optional("aux_heater"): cv.boolean,
        vol.Optional("spin"): vol.All(cv.string, vol.Match(r"^[0-9]{4}$"))
    }
)
SERVICE_SET_PHEATER_DURATION_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): vol.All(cv.string, vol.Length(min=32, max=32)),
        vol.Required("duration"): vol.In([10, 20, 30, 40, 50, 60]),
    }
)

# Set max parallel updates to 2 simultaneous (1 poll and 1 request waiting)
#PARALLEL_UPDATES = 2

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Setup Seat Connect component from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    if entry.options.get(CONF_SCAN_INTERVAL):
        update_interval = timedelta(seconds=entry.options[CONF_SCAN_INTERVAL])
    else:
        update_interval = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
    if update_interval < timedelta(seconds=MIN_SCAN_INTERVAL):
        update_interval = timedelta(seconds=MIN_SCAN_INTERVAL)

    coordinator = SeatCoordinator(hass, entry, update_interval)

    try:
        if not await coordinator.async_login():
            await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_REAUTH},
                data=entry,
            )
            return False
    except (SeatAuthenticationException, SeatAccountLockedException, SeatLoginFailedException) as e:
        raise ConfigEntryAuthFailed(e) from e
    except Exception as e:
        raise ConfigEntryNotReady(e) from e

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, coordinator.async_logout)
    )

    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    # Get parent device
    try:
        identifiers={(DOMAIN, entry.unique_id)}
        registry = device_registry.async_get(hass)
        device = registry.async_get_device(identifiers)
        # Get user configured name for device
        name = device.name_by_user if not device.name_by_user is None else None
    except:
        name = None

    data = SeatData(entry.data, name, coordinator)
    instruments = coordinator.data

    conf_instruments = entry.data.get(CONF_INSTRUMENTS, {}).copy()
    if entry.options.get(CONF_DEBUG, False) is True:
        _LOGGER.debug(f"Configured data: {entry.data}")
        _LOGGER.debug(f"Configured options: {entry.options}")
        _LOGGER.debug(f"Resources from options are: {entry.options.get(CONF_RESOURCES, [])}")
        _LOGGER.debug(f"All instruments (data): {conf_instruments}")
    new_instruments = {}

    def is_enabled(attr):
        """Return true if the user has enabled the resource."""
        return attr in entry.data.get(CONF_RESOURCES, [attr])

    components = set()

    # Check if new instruments
    for instrument in (
        instrument
        for instrument in instruments
        if not instrument.attr in conf_instruments
    ):
            _LOGGER.info(f"Discovered new instrument {instrument.name}")
            new_instruments[instrument.attr] = instrument.name

    # Update config entry with new instruments
    if len(new_instruments) > 0:
        conf_instruments.update(new_instruments)
        # Prepare data to update config entry with
        update = {
            'data': {
                CONF_INSTRUMENTS: dict(sorted(conf_instruments.items(), key=lambda item: item[1]))
            },
            'options': {
                CONF_RESOURCES: entry.options.get(
                    CONF_RESOURCES,
                    entry.data.get(CONF_RESOURCES, ['none']))
            }
        }

        # Enable new instruments if "activate newly enable entitys" is active
        if hasattr(entry, "pref_disable_new_entities"):
            if not entry.pref_disable_new_entities:
                _LOGGER.debug(f"Enabling new instruments {new_instruments}")
                for item in new_instruments:
                    update['options'][CONF_RESOURCES].append(item)

        _LOGGER.debug(f"Updating config entry data: {update.get('data')}")
        _LOGGER.debug(f"Updating config entry options: {update.get('options')}")
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, **update['data']},
            options={**entry.options, **update['options']}
        )

    for instrument in (
        instrument
        for instrument in instruments
        if instrument.component in PLATFORMS and is_enabled(instrument.slug_attr)
    ):
        data.instruments.add(instrument)
        components.add(PLATFORMS[instrument.component])

    for component in components:
        coordinator.platforms.append(component)
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )

    hass.data[DOMAIN][entry.entry_id] = {
        UPDATE_CALLBACK: update_callback,
        DATA: data,
        UNDO_UPDATE_LISTENER: entry.add_update_listener(_async_update_listener),
    }

    # Service functions
    async def get_car(service_call):
        """Get VIN associated with HomeAssistant device ID."""
        # Get device entry
        dev_id = service_call.data.get("device_id")
        dev_reg = device_registry.async_get(hass)
        dev_entry = dev_reg.async_get(dev_id)

        # Get vehicle VIN from device identifiers
        seat_identifiers = [
            identifier
            for identifier in dev_entry.identifiers
            if identifier[0] == DOMAIN
        ]
        vin_identifier = next(iter(seat_identifiers))
        vin = vin_identifier[1]

        # Get coordinator handling the device entry
        conf_entry = next(iter(dev_entry.config_entries))
        try:
            dev_coordinator = hass.data[DOMAIN][conf_entry]['data'].coordinator
        except:
            raise SeatConfigException('Could not find associated coordinator for given vehicle')

        # Return with associated Vehicle class object
        return dev_coordinator.connection.vehicle(vin)

    async def set_schedule(service_call=None):
        """Set departure schedule."""
        try:
            # Prepare data
            id = service_call.data.get("id", 0)
            temp = None

            # Convert datetime objects to simple strings or check that strings are correctly formatted
            try:
                time = service_call.data.get("time").strftime("%H:%M")
            except:
                if re.match('^[0-9]{2}:[0-9]{2}$', service_call.data.get('time', '')):
                    time = service_call.data.get("time", "08:00")
                else:
                    raise SeatInvalidRequestException(f"Invalid time string: {service_call.data.get('time')}")
            if service_call.data.get("off_peak_start", False):
                try:
                    peakstart = service_call.data.get("off_peak_start").strftime("%H:%M")
                except:
                    if re.match('^[0-9]{2}:[0-9]{2}$', service_call.data.get("off_peak_start", "")):
                        time = service_call.data.get("off_peak_start", "00:00")
                    else:
                        raise SeatInvalidRequestException(f"Invalid value for off peak start hours: {service_call.data.get('off_peak_start')}")
            if service_call.data.get("off_peak_end", False):
                try:
                    peakend = service_call.data.get("off_peak_end").strftime("%H:%M")
                except:
                    if re.match('^[0-9]{2}:[0-9]{2}$', service_call.data.get("off_peak_end", "")):
                        time = service_call.data.get("off_peak_end", "00:00")
                    else:
                        raise SeatInvalidRequestException(f"Invalid value for off peak end hours: {service_call.data.get('off_peak_end')}")

            # Convert to parseable data
            schedule = {
                "id": service_call.data.get("id", 1),
                "enabled": service_call.data.get("enabled"),
                "recurring": service_call.data.get("recurring"),
                "date": service_call.data.get("date"),
                "time": time,
                "days": service_call.data.get("days", "nnnnnnn"),
            }
            # Set optional values
            # Night rate
            if service_call.data.get("climatisation", None) is not None:
                schedule["nightRateActive"] = service_call.data.get("climatisation")
            if service_call.data.get("off_peak_start", None) is not None:
                schedule["nightRateTimeStart"] = service_call.data.get("off_peak_start")
            if service_call.data.get("off_peak_end", None) is not None:
                schedule["nightRateTimeEnd"] = service_call.data.get("off_peak_end")
            # Climatisation and charging options
            if service_call.data.get("climatisation", None) is not None:
                schedule["operationClimatisation"] = service_call.data.get("climatisation")
            if service_call.data.get("charging", None) is not None:
                schedule["operationCharging"] = service_call.data.get("charging")
            if service_call.data.get("charge_target", None) is not None:
                schedule["targetChargeLevel"] = service_call.data.get("charge_target")
            if service_call.data.get("charge_current", None) is not None:
                schedule["chargeMaxCurrent"] = service_call.data.get("charge_current")
            # Global optional options
            if service_call.data.get("temp", None) is not None:
                schedule["targetTemp"] = service_call.data.get("temp")

            # Find the correct car and execute service call
            car = await get_car(service_call)
            _LOGGER.info(f'Set departure schedule {id} with data {schedule} for car {car.vin}')
            if await car.set_timer_schedule(id, schedule) is True:
                _LOGGER.debug(f"Service call 'set_schedule' executed without error")
                await coordinator.async_request_refresh()
            else:
                _LOGGER.warning(f"Failed to execute service call 'set_schedule' with data '{service_call}'")
        except (SeatInvalidRequestException) as e:
            _LOGGER.warning(f"Service call 'set_schedule' failed {e}")
        except Exception as e:
            raise

    async def set_charge_limit(service_call=None):
        """Set minimum charge limit."""
        try:
            car = await get_car(service_call)

            # Get charge limit and execute service call
            limit = service_call.data.get("limit", 50)
            if await car.set_charge_limit(limit) is True:
                _LOGGER.debug(f"Service call 'set_charge_limit' executed without error")
                await coordinator.async_request_refresh()
            else:
                _LOGGER.warning(f"Failed to execute service call 'set_charge_limit' with data '{service_call}'")
        except (SeatInvalidRequestException) as e:
            _LOGGER.warning(f"Service call 'set_schedule' failed {e}")
        except Exception as e:
            raise

    async def set_current(service_call=None):
        """Set departure schedule."""
        try:
            car = await get_car(service_call)

            # Get charge current and execute service call
            current = service_call.data.get('current', None)
            if await car.set_charger_current(current) is True:
                _LOGGER.debug(f"Service call 'set_current' executed without error")
                await coordinator.async_request_refresh()
            else:
                _LOGGER.warning(f"Failed to execute service call 'set_current' with data '{service_call}'")
        except (SeatInvalidRequestException) as e:
            _LOGGER.warning(f"Service call 'set_schedule' failed {e}")
        except Exception as e:
            raise

    async def set_pheater_duration(service_call=None):
        """Set duration for parking heater."""
        try:
            car = await get_car(service_call)
            car.pheater_duration = service_call.data.get("duration", car.pheater_duration)
            _LOGGER.debug(f"Service call 'set_pheater_duration' executed without error")
            await coordinator.async_request_refresh()
        except (SeatInvalidRequestException) as e:
            _LOGGER.warning(f"Service call 'set_schedule' failed {e}")
        except Exception as e:
            raise

    async def set_climater(service_call=None):
        """Start or stop climatisation with options."""
        try:
            car = await get_car(service_call)

            if service_call.data.get('enabled'):
                action = 'auxiliary' if service_call.data.get('aux_heater', False) else 'electric'
                temp = service_call.data.get('temp', None)
                hvpower = service_call.data.get('battery_power', None)
                spin = service_call.data.get('spin', None)
            else:
                action = 'off'
                temp = hvpower = spin = None
            # Execute service call
            if await car.set_climatisation(action, temp, hvpower, spin) is True:
                _LOGGER.debug(f"Service call 'set_climater' executed without error")
                await coordinator.async_request_refresh()
            else:
                _LOGGER.warning(f"Failed to execute service call 'set_current' with data '{service_call}'")
        except (SeatInvalidRequestException) as e:
            _LOGGER.warning(f"Service call 'set_schedule' failed {e}")
        except Exception as e:
            raise

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        set_schedule,
        schema = SERVICE_SET_SCHEDULE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MAX_CURRENT,
        set_current,
        schema = SERVICE_SET_MAX_CURRENT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CHARGE_LIMIT,
        set_charge_limit,
        schema = SERVICE_SET_CHARGE_LIMIT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CLIMATER,
        set_climater,
        schema = SERVICE_SET_CLIMATER_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PHEATER_DURATION,
        set_pheater_duration,
        schema = SERVICE_SET_PHEATER_DURATION_SCHEMA
    )

    return True


def update_callback(hass, coordinator):
    _LOGGER.debug("CALLBACK!")
    hass.async_create_task(
        coordinator.async_request_refresh()
    )


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the component from configuration.yaml."""
    hass.data.setdefault(DOMAIN, {})

    if hass.config_entries.async_entries(DOMAIN):
        return True

    if DOMAIN in config:
        _LOGGER.info("Found existing Seat Connect configuration.")
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data=config[DOMAIN],
            )
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    _LOGGER.debug("Unloading services")
    hass.services.async_remove(DOMAIN, SERVICE_SET_SCHEDULE)
    hass.services.async_remove(DOMAIN, SERVICE_SET_MAX_CURRENT)
    hass.services.async_remove(DOMAIN, SERVICE_SET_CHARGE_LIMIT)
    hass.services.async_remove(DOMAIN, SERVICE_SET_CLIMATER)
    hass.services.async_remove(DOMAIN, SERVICE_SET_PHEATER_DURATION)

    _LOGGER.debug("Unloading update listener")
    hass.data[DOMAIN][entry.entry_id][UNDO_UPDATE_LISTENER]()

    return await async_unload_coordinator(hass, entry)


async def async_unload_coordinator(hass: HomeAssistant, entry: ConfigEntry):
    """Unload auth token based entry."""
    _LOGGER.debug("Unloading coordinator")
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA].coordinator

    _LOGGER.debug("Log out from Seat Connect")
    await coordinator.async_logout()
    unloaded = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
                if platform in coordinator.platforms
            ]
        )
    )
    if unloaded:
        _LOGGER.debug("Unloading entry")
        del hass.data[DOMAIN][entry.entry_id]

    if not hass.data[DOMAIN]:
        _LOGGER.debug("Unloading data")
        del hass.data[DOMAIN]

    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


def get_convert_conf(entry: ConfigEntry):
    return CONF_SCANDINAVIAN_MILES if entry.options.get(
        CONF_SCANDINAVIAN_MILES,
        entry.data.get(
            CONF_SCANDINAVIAN_MILES,
            False
        )
    ) else CONF_NO_CONVERSION

async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Migrate configuration from old version to new."""
    _LOGGER.debug(f'Migrating from version {entry.version}')

    # Migrate data from version 1
    if entry.version == 1:
        # Make a copy of old config
        new = {**entry.data}

        # Convert from minutes to seconds for poll interval
        minutes = entry.options.get("update_interval", 1)
        seconds = minutes*60
        new.pop("update_interval", None)
        new[CONF_SCAN_INTERVAL] = seconds

        # Save "new" config
        entry.data = {**new}

        entry.version = 2

    _LOGGER.info("Migration to version %s successful", entry.version)
    return True

class SeatData:
    """Hold component state."""

    def __init__(self, config, name=None, coordinator=None):
        """Initialize the component state."""
        self.vehicles = set()
        self.instruments = set()
        self.config = config.get(DOMAIN, config)
        self.name = name
        self.coordinator = coordinator

    def instrument(self, vin, component, attr):
        """Return corresponding instrument."""
        return next(
            (
                instrument
                for instrument in (
                    self.coordinator.data
                    if self.coordinator is not None
                    else self.instruments
                )
                if instrument.vehicle.vin == vin
                and instrument.component == component
                and instrument.attr == attr
            ),
            None,
        )

    def vehicle_name(self, vehicle):
        """Provide a friendly name for a vehicle."""
        try:
            # Return name if configured by user
            if isinstance(self.name, str):
                if len(self.name) > 0:
                    return self.name
        except:
            pass

        # Default name to nickname if supported, else vin number
        try:
            if vehicle.is_nickname_supported:
                return vehicle.nickname
            elif vehicle.vin:
                return vehicle.vin
        except:
            _LOGGER.info(f"Name set to blank")
            return ""


class SeatEntity(Entity):
    """Base class for all Seat entities."""

    def __init__(self, data, vin, component, attribute, callback=None):
        """Initialize the entity."""

        def update_callbacks():
            if callback is not None:
                callback(self.hass, data.coordinator)

        self.data = data
        self.vin = vin
        self.component = component
        self.attribute = attribute
        self.coordinator = data.coordinator
        self.instrument.callback = update_callbacks
        self.callback = callback

    async def async_update(self) -> None:
        """Update the entity.

        Only used by the generic entity update service.
        """

        # Ignore manual update requests if the entity is disabled
        if not self.enabled:
            return

        await self.coordinator.async_request_refresh()

    async def async_added_to_hass(self):
        """Register update dispatcher."""
        if self.coordinator is not None:
            self.async_on_remove(
                self.coordinator.async_add_listener(self.async_write_ha_state)
            )
        else:
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
    def extra_state_attributes(self):
        """Return extra state attributes."""
        attributes = dict(
            self.instrument.attributes,
            model=f"{self.vehicle.model}/{self.vehicle.model_year}",
        )

        # Return model image as picture attribute for position entity
        if "position" in self.attribute:
            # Try to use small thumbnail first hand, else fallback to fullsize
            if self.vehicle.is_model_image_small_supported:
                attributes["entity_picture"] = self.vehicle.model_image_small
            elif self.vehicle.is_model_image_large_supported:
                attributes["entity_picture"] = self.vehicle.model_image_large

        return attributes

    @property
    def device_info(self):
        """Return the device_info of the device."""
        return {
            "identifiers": {(DOMAIN, self.vin)},
            "name": self._vehicle_name,
            "manufacturer": "Seat",
            "model": self.vehicle.model,
            "sw_version": self.vehicle.model_year,
        }

    @property
    def available(self):
        """Return if sensor is available."""
        if self.data.coordinator is not None:
            return self.data.coordinator.last_update_success
        return True

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self.vin}-{self.component}-{self.attribute}"


class SeatCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, entry, update_interval: timedelta):
        self.vin = entry.data[CONF_VEHICLE].upper()
        self.entry = entry
        self.platforms = []
        self.report_last_updated = None
        self.connection = Connection(
            session=async_get_clientsession(hass),
            username=self.entry.data[CONF_USERNAME],
            password=self.entry.data[CONF_PASSWORD],
            fulldebug=self.entry.options.get(CONF_DEBUG, self.entry.data.get(CONF_DEBUG, DEFAULT_DEBUG)),
        )

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

    async def _async_update_data(self):
        """Update data via library."""
        vehicle = await self.update()

        if not vehicle:
            raise UpdateFailed("No vehicles found.")

        # Backward compatibility
        default_convert_conf = get_convert_conf(self.entry)

        convert_conf = self.entry.options.get(
            CONF_CONVERT,
            self.entry.data.get(
                CONF_CONVERT,
                default_convert_conf
            )
        )

        dashboard = vehicle.dashboard(
            mutable=self.entry.options.get(CONF_MUTABLE),
            spin=self.entry.options.get(CONF_SPIN),
            miles=convert_conf == CONF_IMPERIAL_UNITS,
            scandinavian_miles=convert_conf == CONF_SCANDINAVIAN_MILES,
        )

        return dashboard.instruments

    async def async_logout(self, event=None):
        """Logout from Seat Connect"""
        _LOGGER.debug("Shutdown Seat Connect")
        try:
            await self.connection.terminate()
            self.connection = None
        except Exception as ex:
            _LOGGER.error("Failed to log out and revoke tokens for Seat Connect. Some tokens might still be valid.")
            return False
        return True

    async def async_login(self):
        """Login to Seat Connect"""
        # Check if we can login
        try:
            if await self.connection.doLogin() is False:
                _LOGGER.warning(
                    "Could not login to Seat Connect, please check your credentials and verify that the service is working"
                )
                return False
            # Get associated vehicles before we continue
            await self.connection.get_vehicles()
            return True
        except (SeatAccountLockedException, SeatAuthenticationException) as e:
            # Raise auth failed error in config flow
            raise ConfigEntryAuthFailed(e) from e
        except:
            raise

    async def update(self) -> Union[bool, Vehicle]:
        """Update status from Seat Connect"""

        # Update vehicle data
        _LOGGER.debug("Updating data from Seat Connect")
        try:
            # Get Vehicle object matching VIN number
            vehicle = self.connection.vehicle(self.vin)
            if await vehicle.update():
                return vehicle
            else:
                _LOGGER.warning("Could not query update from Seat Connect")
                return False
        except Exception as error:
            _LOGGER.warning(f"An error occured while requesting update from Seat Connect: {error}")
            return False
