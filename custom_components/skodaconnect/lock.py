"""
Support for Skoda Connect Platform
"""
import logging

from homeassistant.components.lock import LockEntity
from homeassistant.helpers.dispatcher import async_dispatcher_send

from . import DATA_KEY, SkodaEntity
from .const import DOMAIN

SIGNAL_STATE_UPDATED = f"{DOMAIN}.updated"

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """ Setup the skoda lock """
    if discovery_info is None:
        return

    async_add_entities([SkodaLock(hass.data[DATA_KEY], *discovery_info)])


class SkodaLock(SkodaEntity, LockEntity):
#class SkodaLock(SkodaEntity, LockDevice):
    """Represents a Skoda Connect Lock."""

    @property
    def is_locked(self):
        """Return true if lock is locked."""
        _LOGGER.debug("Getting state of %s" % self.instrument.attr)
        return self.instrument.is_locked

    async def async_lock(self, **kwargs):
        """Lock the car."""
        await self.instrument.lock()
        async_dispatcher_send(self.hass, SIGNAL_STATE_UPDATED)

    async def async_unlock(self, **kwargs):
        """Unlock the car."""
        await self.instrument.unlock()
        async_dispatcher_send(self.hass, SIGNAL_STATE_UPDATED)
