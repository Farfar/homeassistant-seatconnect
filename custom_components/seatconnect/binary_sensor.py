"""
Support for Seat Connect.
"""
import logging

from homeassistant.components.binary_sensor import DEVICE_CLASSES, BinarySensorEntity

from . import DATA_KEY, SeatEntity


_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Seat binary sensors."""
    if discovery_info is None:
        return
    async_add_entities([SeatBinarySensor(hass.data[DATA_KEY], *discovery_info)])


class SeatBinarySensor(SeatEntity, BinarySensorEntity):
    """Representation of a Seat Binary Sensor """

    @property
    def is_on(self):
        """Return True if the binary sensor is on."""
        _LOGGER.debug("Getting state of %s" % self.instrument.attr)
        return self.instrument.is_on

    @property
    def device_class(self):
        """Return the class of this sensor, from DEVICE_CLASSES."""
        if self.instrument.device_class in DEVICE_CLASSES:
            return self.instrument.device_class
        return None
