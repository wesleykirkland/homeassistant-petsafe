import datetime
import time

import pytz
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

import petsafe

from . import PetSafeCoordinator, PetSafeData
from .const import (
    CAT_IN_BOX,
    DOMAIN,
    ERROR_SENSOR_BLOCKED,
    FEEDER_MODEL_GEN1,
    FEEDER_MODEL_GEN2,
    MANUFACTURER,
    RAKE_BUTTON_DETECTED,
    RAKE_FINISHED,
    RAKE_NOW,
)


class PetSafeSensorEntity(CoordinatorEntity, SensorEntity):
    def __init__(
        self,
        hass: HomeAssistant,
        api_name: str,
        name: str,
        coordinator: PetSafeCoordinator,
        device_type: str,
        icon: str = None,
        device_class: str = None,
        entity_category: str = None,
    ):
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_has_entity_name = True
        self._coordinator = coordinator
        self._api_name = api_name
        self._attr_unique_id = api_name + "_" + device_type
        self._attr_icon = icon
        self._device_type = device_type
        self._attr_entity_category = entity_category

        if device_class == "signal_strength":
            self._attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
        elif device_class == "battery":
            self._attr_native_unit_of_measurement = PERCENTAGE


class PetSafeLitterboxSensorEntity(PetSafeSensorEntity):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        coordinator: PetSafeCoordinator,
        device_type: str,
        device: petsafe.devices.DeviceScoopfree,
        icon: str = None,
        device_class: str = None,
        entity_category: str = None,
    ):
        self._litterbox = device

        super().__init__(
            hass,
            device.api_name,
            name,
            coordinator,
            device_type,
            icon,
            device_class,
            entity_category,
        )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.api_name)},
            manufacturer=MANUFACTURER,
            name=device.friendly_name,
            model=device.product_name,
            sw_version=device.firmware,
        )

        if self._device_type == "last_cleaning" or self._device_type == "rake_status":
            self._attr_should_poll = True
        else:
            self._attr_should_poll = False

    def _handle_coordinator_update(self) -> None:
        data: PetSafeData = self.coordinator.data
        litterbox: petsafe.devices.DeviceScoopfree = next(
            x for x in data.litterboxes if x.api_name == self._api_name
        )
        if self._device_type == "rake_counter":
            self._attr_native_value = litterbox.data["shadow"]["state"]["reported"][
                "rakeCount"
            ]
        elif self._device_type == "signal_strength":
            self._attr_native_value = litterbox.data["shadow"]["state"]["reported"][
                "rssi"
            ]
        if self._attr_should_poll:
            self.schedule_update_ha_state(True)
        else:
            self.async_write_ha_state()
        return super()._handle_coordinator_update()

    async def async_update(self) -> None:
        if self._device_type == "last_cleaning":
            data: PetSafeData = self.coordinator.data
            litterbox: petsafe.devices.DeviceScoopfree = next(
                x for x in data.litterboxes if x.api_name == self._api_name
            )
            events = await litterbox.get_activity()
            self._attr_native_value = self._get_last_cleaning_time(events["data"])
        elif self._device_type == "rake_status":
            data: PetSafeData = self.coordinator.data
            litterbox: petsafe.devices.DeviceScoopfree = next(
                x for x in data.litterboxes if x.api_name == self._api_name
            )
            events = await litterbox.get_activity()
            self._attr_native_value = self._get_rake_status(events["data"], litterbox)
        return await super().async_update()

    def _get_last_cleaning_time(self, events):
        for item in reversed(events):
            if item["payload"]["code"] == RAKE_FINISHED:
                return datetime.datetime.fromtimestamp(
                    int(item["payload"]["timestamp"]) / 1000, pytz.timezone("UTC")
                )
        return self._attr_native_value

    def _get_rake_status(self, events, litterbox: petsafe.devices.DeviceScoopfree):
        for item in reversed(events):
            code = item["payload"]["code"]
            if code == RAKE_FINISHED:
                return "idle"
            if code == CAT_IN_BOX:
                timestamp = int(item["payload"]["timestamp"]) / 1000
                delay = litterbox.data["shadow"]["state"]["reported"]["rakeDelayTime"] * 60
                return "raking" if timestamp + delay <= time.time() else "timing"
            if code in (RAKE_BUTTON_DETECTED, RAKE_NOW):
                return "raking"
            if code == ERROR_SENSOR_BLOCKED:
                return "jammed"
        return None


class PetSafeFeederSensorEntity(PetSafeSensorEntity):
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        coordinator: PetSafeCoordinator,
        device_type: str,
        device: petsafe.devices.DeviceSmartFeed,
        icon: str = None,
        device_class: str = None,
        entity_category: str = None,
    ):
        self._feeder = device

        super().__init__(
            hass,
            device.api_name,
            name,
            coordinator,
            device_type,
            icon,
            device_class,
            entity_category,
        )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.api_name)},
            manufacturer=MANUFACTURER,
            name=device.friendly_name,
            sw_version=device.firmware,
            # NB: Gen1 smart feeders do not report a product_name
            model=device.product_name or FEEDER_MODEL_GEN1,
        )

        if self._device_type == "last_feeding" or self._device_type == "next_feeding":
            self._attr_should_poll = True
        else:
            self._attr_should_poll = False

    def _handle_coordinator_update(self) -> None:
        data: PetSafeData = self.coordinator.data
        feeder: petsafe.devices.DeviceSmartFeed = next(
            x for x in data.feeders if x.api_name == self._api_name
        )
        if self._device_type == "battery":
            self._attr_native_value = feeder.battery_level
        elif self._device_type == "food_level":
            if feeder.food_low_status == 0:
                status = "full"
            elif feeder.food_low_status == 1:
                status = "low"
            else:
                status = "empty"
            self._attr_native_value = status
        elif self._device_type == "signal_strength":
            self._attr_native_value = feeder.data["network_rssi"]

        if self._attr_should_poll:
            self.schedule_update_ha_state(True)
        else:
            self.async_write_ha_state()
        return super()._handle_coordinator_update()

    async def async_update(self) -> None:

        if self._device_type == "last_feeding":
            data: PetSafeData = self.coordinator.data
            feeder: petsafe.devices.DeviceSmartFeed = next(
                x for x in data.feeders if x.api_name == self._api_name
            )
            messages = await feeder.get_messages_since(days=7)
            # Messages are sorted oldest-first; iterate in reverse to find the most recent FEED_DONE
            for message in reversed(messages):
                if message.get("message_type") == "FEED_DONE":
                    ts = message.get("payload", {}).get("time")
                    if ts is not None:
                        self._attr_native_value = datetime.datetime.fromtimestamp(
                            ts, pytz.timezone("UTC")
                        )
                    break
        if self._device_type == "next_feeding":
            data: PetSafeData = self.coordinator.data
            feeder: petsafe.devices.DeviceSmartFeed = next(
                x for x in data.feeders if x.api_name == self._api_name
            )
            if self._attr_native_value is None or dt_util.now() > self._attr_native_value:
                schedules = await feeder.get_schedules()
                self._attr_native_value = self._get_next_feeding_time(schedules)
        return await super().async_update()
    
    def _get_next_feeding_time(self, schedules):
        now = dt_util.now()
        time_fmt = "%H:%M"
        
        # Convert schedule times to datetime objects for today
        today = now.date()
        feeding_times = []
        for schedule in schedules:
            time_obj = datetime.datetime.strptime(schedule["time"], time_fmt).time()
            feeding_time = dt_util.as_local(datetime.datetime.combine(today, time_obj))
            feeding_times.append(feeding_time)
        
        sorted_feeding_times = sorted(feeding_times)
        # Find the next feeding time
        for time in sorted_feeding_times:
            if time > now:
                return time
                
        # If no times found today, return first feeding time for tomorrow
        return dt_util.as_local(sorted_feeding_times[0] + datetime.timedelta(days=1))
