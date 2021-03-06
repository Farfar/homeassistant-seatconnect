"""
Support for Seat Connect Platform
"""
import logging

from homeassistant.components.device_tracker import SOURCE_TYPE_GPS
from homeassistant.helpers.dispatcher import async_dispatcher_connect

# from homeassistant.helpers.dispatcher import (dispatcher_connect, dispatcher_send)
from homeassistant.util import slugify

from . import DATA_KEY, SIGNAL_STATE_UPDATED

_LOGGER = logging.getLogger(__name__)


async def async_setup_scanner(hass, config, async_see, discovery_info=None):
    """Set up the Seat tracker."""
    if discovery_info is None:
        return

    vin, component, attr = discovery_info
    data = hass.data[DATA_KEY]
    instrument = data.instrument(vin, component, attr)

    async def see_vehicle():
        """Handle the reporting of the vehicle position."""
        host_name = data.vehicle_name(instrument.vehicle)
        dev_id = "{}".format(slugify(host_name))
        _LOGGER.debug("Getting location of %s" % host_name)
        if instrument.state[0] is None:
            _LOGGER.debug("No GPS location data available.")
            await async_see(
                dev_id=dev_id,
                host_name=host_name,
                location_name="not_home",
                source_type=SOURCE_TYPE_GPS,
                icon="mdi:car",
            )
        else:
            await async_see(
                dev_id=dev_id,
                host_name=host_name,
                source_type=SOURCE_TYPE_GPS,
                gps=instrument.state,
                icon="mdi:car",
            )

    async_dispatcher_connect(hass, SIGNAL_STATE_UPDATED, see_vehicle)

    return True
