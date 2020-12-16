![Version](https://img.shields.io/github/v/release/lendy007/homeassistant-skodaconnect?include_prereleases)
![PyPi](https://img.shields.io/pypi/v/skodaconnect?label=latest%20pypi)
![Downloads](https://img.shields.io/github/downloads/lendy007/homeassistant-skodaconnect/total)

# Skoda Connect - An home assistant plugin to add integration with your car

# v1.0.18-test

## This is fork of [robinostlund/homeassistant-volkswagencarnet](https://github.com/robinostlund/homeassistant-volkswagencarnet) where I am trying to modify the code to support Skoda Connect.

### What is working
- odometer
- fuel level, range, adblue level
- lock status, window status
- last trip info
- position - gps coordinates, vehicleMoving, parkingTime 
- parking heater heating/ventilation control
- electric engine related information thanks to @Farfar
- electric climatisation and window_heater information thanks to @Farfar
- auxiliary heating/ventilation control (for vehicles with electric climatisation)
- start/stop electric climatisation and window_heater thanks to @Farfar
- lock/unlock car thanks to @tanelvakker
- trigger force refresh, VWG servers will try to wake car so it reports back new status
- request result and requests remaining until throttled.
- fetch nickname for car from servers
- a toggle of a switch should now trigger a status refresh in HA after request completes
- exposed services, set_schedule and set_pheater_duration, to set departure schedules and duration of parking heater

### What is NOT working / under development
- when vehicleMoving=yes device_tracker GPS stays on old values until parked
- all values seems to be metric, no matter what region. Conversion between values needs to be implemented.

### Install
Clone or copy the repository and copy the folder 'homeassistant-skodaconnect/custom_component/skodaconnect' into '<config dir>/custom_components'
    
## Configure

Add a skodaconnect configuration block to your `<config dir>/configuration.yaml`:
```yaml
skodaconnect:
    username: <username for skoda connect>
    password: <password for skoda connect>
    spin: <S-PIN for skoda connect>
    # combustion_engine_heating_duration: <allowed values 10,20,30,40,50,60 (minutes)>
    # combustion_engine_climatisation_duration: <allowed values 10,20,30,40,50,60 (minutes)>
    climatisation_duration: <allowed values 10,20,30,40,50,60 (minutes)>
    scandinavian_miles: false
    scan_interval:
        minutes: 5
    name:
        wvw1234567812356: 'Kodiaq'
    resources:
        - pheater_status
        - pheater_heating         
        - pheater_climatisation
        - pheater_duration
        - distance
        - position
        - vehicleMoving
        - parkingTime
        - request_in_progress
        - requests_remaining
        - request_result
        - fuel_level        
        - adblue_level
        - battery_level
        - last_connected
        - combustion_range
        - electric_range
        - combined_range
        - trip_last_average_speed
        - trip_last_average_fuel_consumption
        - trip_last_average_electric_consumption
        - trip_last_duration
        - trip_last_length
        - parking_light
        - door_locked
        - door_closed_left_front        
        - door_closed_left_back
        - door_closed_right_front
        - door_closed_right_back
        - hood_closed
        - trunk_locked
        - trunk_closed
        - windows_closed        
        - window_closed_left_front
        - window_closed_left_back
        - window_closed_right_front
        - window_closed_right_back
        - sunroof_closed
        - service_inspection
        - oil_inspection
        - service_inspection_km
        - oil_inspection_km
        - outside_temperature
        - electric_climatisation
        - auxiliary_climatisation
        - climatisation_target_temperature
        - climatisation_without_external_power
        - window_heater
        - charging
        - charging_cable_connected
        - charging_cable_locked
        - charging_time_left
        - charge_max_ampere
        - external_power
        - energy_flow
```

* **resources:** if not specified, it will create all supported entities

* **spin:** (optional) required for supporting combustion engine heating start/stop.

* **climatisation_duration:** (optional) Heating/Ventilation duration for parking heater (Note: not aux heater for EV/PHEV cars). (default 30 minutes, valid values: 10, 20, 30, 40, 50, 60)

* **scan_interval:** (optional) specify in minutes how often to fetch status data from servers. (default 5 min, minimum 1 min)

* **scandinavian_miles:** (optional) specify true if you want to change from km to mil on sensors

* **name:** (optional) map the vehicle identification number (VIN) to a friendly name of your car. This name is then used for naming all entities. See the configuration example. (by default, the nickname from portal is used and VIN if no nickname is set). VIN need to be entered lower case

## Automations

In this example we are sending notifications to an ios device

Save these automations in your automations file `<config dir>/automations.yaml`

### Get notification when your car is on a new place and show a map with start position and end position
```yaml
- id: notify_skoda_position_change
  description: Notify when position has been changed
  alias: Skoda position changed notification
  trigger:
    - platform: state
      entity_id: device_tracker.kodiaq
  action:
    - service: notify.ios_my_ios_device
      data_template:
        title: "Kodiaq Position Changed"
        message: |
          🚗 Skoda Car is now on a new place.
        data:
          url: /lovelace/car
          apns_headers:
            'apns-collapse-id': 'car_position_state_{{ trigger.entity_id.split(".")[1] }}'
          push:
            category: map
            thread-id: "HA Car Status"
          action_data:
            latitude: "{{trigger.from_state.attributes.latitude}}"
            longitude: "{{trigger.from_state.attributes.longitude}}"
            second_latitude: "{{trigger.to_state.attributes.latitude}}"
            second_longitude: "{{trigger.to_state.attributes.longitude}}"
            shows_traffic: true
```

### Announce when your car is unlocked but no one is home
```yaml
- id: 'notify_skoda_car_is_unlocked'
  alias: Skoda is at home and unlocked
  trigger:
    - entity_id: binary_sensor.vw_carid_external_power
      platform: state
      to: 'on'
      for: 00:10:00
  condition:
    - condition: state
      entity_id: lock.kodiaq_door_locked
      state: unlocked
    - condition: state
      entity_id: device_tracker.kodiaq
      state: home
    - condition: time
      after: '07:00:00'
      before: '21:00:00'
  action:
    # Notification via push message to smartphone
    - service: notify.device
      data:
        message: "The car is unlocked!"
        target:
          - device/my_device
    # Notification via smart speaker (kitchen)
    - service: media_player.volume_set
      data:
        entity_id: media_player.kitchen
        volume_level: '0.6'
    - service: tts.google_translate_say
      data:
        entity_id: media_player.kitchen
        message: "My Lord, the car is unlocked. Please attend this this issue at your earliest inconvenience!"
```
### Set climatisation duration from input_select
```yaml
input_select:
  skoda_climatisation_duration:
    name: "Parking heater duration"
    options:
      - '10'
      - '20'
      - '30'
      - '40'
      - '50'
      - '60'
```
```yaml
- id: 'set_skoda_climatisation_duration'
  alias: Set climatisation duration
  trigger:
  - platform: state
    entity_id: input_select.skoda_climatisation_duration
  action:
  - service: skodaconnect.set_pheater_duration
    data:
      vin: ABCDE9FG0H1234567
      duration: '{{ trigger.to_state.state | int }}'
```

## Enable debug logging
```yaml
logger:
    default: info
    logs:
        skodaconnect: debug        
        custom_components.skodaconnect: debug
        custom_components.skodaconnect.climate: debug
        custom_components.skodaconnect.lock: debug
        custom_components.skodaconnect.device_tracker: debug
        custom_components.skodaconnect.switch: debug
        custom_components.skodaconnect.binary_sensor: debug
        custom_components.skodaconnect.sensor: debug
 ```

