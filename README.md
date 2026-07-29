# SkyRC MC3000 Home Assistant Integration

Custom Home Assistant integration for the SkyRC MC3000 charger.

This integration exposes MC3000 charger status, slot data, start/stop controls, Companion App Mode, and voltage curve data in Home Assistant.

Current release track:

    v1.1.0

This release adds:

- Home Assistant Bluetooth API support
- ESPHome Bluetooth Proxy support
- manual voltage curve fetching
- automatic voltage curve fetching for active slots
- voltage curve timing metadata
- an ApexCharts dashboard example
- Companion App Mode to release the BLE connection for the SkyRC companion app
- quiet recovery from transient BLE disconnects and response timeouts
- safe, explicit upload of complete MC3000 work programs
- a chemistry-checked Start all dashboard control

Recoverable BLE disconnects keep the last known sensor data and reconnect on
the next poll. They are logged at debug level. Initial connection failures and
failures without usable cached data remain visible through Home Assistant's
coordinator error reporting.

---

## Status

This integration is functional but still under active development.

The current implementation can:

- discover/connect through Home Assistant Bluetooth
- use ESPHome Bluetooth Proxy
- poll MC3000 status
- expose charger and slot sensors
- start/stop slots using the program already configured on the charger
- fetch voltage curves manually
- auto-fetch voltage curves for active slots
- display voltage curves in Lovelace through ApexCharts

Complete charger profiles can be uploaded through the `write_program` service.
The service requires every safety-critical setting and never starts a slot
automatically.

---

## Requirements

- Home Assistant
- SkyRC MC3000 with Bluetooth enabled
- Bluetooth access through one of:
  - local Home Assistant Bluetooth adapter
  - ESPHome Bluetooth Proxy

Python dependency:

    skyrc-ble @ https://github.com/jperquin/skyrc-ble/archive/refs/tags/v3.0.0.zip

MC3000 voltage-curve parsing and complete program writes are provided by the
immutable `skyrc-ble` v3.0.0 GitHub release tag.

---

## Bluetooth support

The integration uses Home Assistant's Bluetooth manager first.

That means the MC3000 can be reached through:

    Home Assistant Bluetooth API
    -> local Bluetooth adapter or ESPHome Bluetooth Proxy
    -> SkyRC MC3000

Direct Bleak scanning remains available as a fallback for local BlueZ adapters.

This is important for HAOS/VM/container setups where the charger is not reachable by a directly attached Bluetooth adapter but is visible through an ESPHome Bluetooth Proxy.

---

## ESPHome Bluetooth Proxy

A minimal ESPHome Bluetooth Proxy configuration:

    esphome:
      name: skyrc-bt-proxy
      friendly_name: SkyRC BT Proxy

    esp32:
      board: esp32dev
      framework:
        type: esp-idf

    logger:

    api:

    ota:
      - platform: esphome

    wifi:
      ssid: !secret wifi_ssid
      password: !secret wifi_password

    esp32_ble_tracker:
      scan_parameters:
        interval: 1100ms
        window: 1100ms
        active: true

    bluetooth_proxy:
      active: true
      cache_services: true

After the ESPHome device is online, add it to Home Assistant through the ESPHome integration. Home Assistant should then expose it as a Bluetooth source.

The MC3000 typically advertises as:

    name: Charger
    service UUID: 0000ffe0-0000-1000-8000-00805f9b34fb

---

## Installation

Copy the integration to:

    /config/custom_components/skyrc_mc3000

Then restart Home Assistant.

Add the integration through:

    Settings -> Devices & services -> Add integration -> SkyRC MC3000

If Bluetooth discovery is working, the MC3000 should appear as a discovered device.

Manual setup is also possible by entering the MC3000 Bluetooth MAC address.

---

## Entities

### Device-level sensors

The integration exposes charger-level data such as:

- input voltage
- temperature unit
- display mode
- cooling fan mode
- system beep
- screensaver

Example entity IDs may include:

    sensor.input_voltage
    sensor.skyrc_mc3000_temperature_unit
    sensor.skyrc_mc3000_display_mode
    sensor.skyrc_mc3000_cooling_fan_mode
    sensor.skyrc_mc3000_system_beep
    sensor.skyrc_mc3000_screensaver

Entity IDs can differ if Home Assistant already had older entities registered. Check your entity registry if in doubt.

### Slot sensors

For each of the four slots:

- status
- battery type
- mode
- voltage
- current
- capacity
- temperature
- internal resistance
- elapsed time

Typical entity IDs:

    sensor.skyrc_mc3000_slot_1_status
    sensor.skyrc_mc3000_slot_1_battery_type
    sensor.skyrc_mc3000_slot_1_mode
    sensor.skyrc_mc3000_slot_1_voltage
    sensor.skyrc_mc3000_slot_1_current
    sensor.skyrc_mc3000_slot_1_capacity
    sensor.skyrc_mc3000_slot_1_temperature
    sensor.skyrc_mc3000_slot_1_internal_resistance
    sensor.skyrc_mc3000_slot_1_elapsed_time

Repeat for slots 2, 3, and 4.

Voltage sensors use suggested display precision of 3 decimals.

Elapsed time is formatted as:

    H:MM:SS

### Buttons

The integration exposes buttons for:

- refresh charger state
- start all slots, with the per-slot Expected Chemistry checks
- stop all slots
- start slot 1-4
- stop slot 1-4
- fetch voltage curve slot 1-4

Typical entity IDs:

    button.skyrc_mc3000_refresh
    button.skyrc_mc3000_start_all
    button.skyrc_mc3000_stop_all
    button.skyrc_mc3000_slot_1_start
    button.skyrc_mc3000_slot_1_stop
    button.skyrc_mc3000_slot_1_fetch_voltage_curve

Repeat for slots 2, 3, and 4.

The start buttons start the program already configured on the MC3000 for that slot.
They do not program charge parameters.

Use the `skyrc_mc3000.write_program` service to upload a complete program first.
The charger protocol cannot change only the battery chemistry: every upload also
contains the currents, voltage limits and protection values. The write service
therefore requires all safety-critical fields and never starts the program
automatically.

The existing Expected Chemistry selects remain a start-time safety policy. They
do not write to the charger.

### Switches

The integration exposes:

    switch.skyrc_mc3000_companion_app_mode
    switch.skyrc_mc3000_auto_fetch_voltage_curves

---

## Companion App Mode

The MC3000 BLE connection is effectively single-client.

Companion App Mode:

- pauses Home Assistant polling
- disconnects BLE
- allows the SkyRC companion app to connect

Turn Companion App Mode off to resume Home Assistant polling.

Use this when you want to modify charger programs or settings through the official SkyRC app.

---

## Auto Fetch Voltage Curves

Voltage curves are not fetched continuously by default.

You can fetch them manually with the per-slot fetch buttons, or enable:

    switch.skyrc_mc3000_auto_fetch_voltage_curves

When enabled, the integration:

- fetches voltage curves only for active slots
- considers a slot active when current is above 0.001 A
- throttles curve fetching to avoid excessive BLE traffic
- updates the voltage curve sensors and attributes

This avoids constant 0x56 curve polling while still keeping active charge curves reasonably fresh.

---

## Voltage curve support

The MC3000 voltage curve command is read-only.

The integration exposes one diagnostic sensor per slot:

    sensor.skyrc_mc3000_slot_1_voltage_curve_points
    sensor.skyrc_mc3000_slot_2_voltage_curve_points
    sensor.skyrc_mc3000_slot_3_voltage_curve_points
    sensor.skyrc_mc3000_slot_4_voltage_curve_points

The sensor state is the number of non-zero voltage samples.

The curve itself is stored in attributes:

    sample_count: 120
    nonzero_sample_count: 70
    min_nonzero_mv: 1458
    max_nonzero_mv: 1547
    interval_seconds: 1
    unknown_3: 0
    checksum_ok: true
    plot_until_index: 69
    plot_reason: last_nonzero_sample
    samples_mv:
      - 1458
      - 1458
      - 1478
    samples_v:
      - 1.458
      - 1.458
      - 1.478
    last_fetched: "2026-04-28T12:42:25"

The voltage curve frame has been observed as:

    total frame length: 246 bytes
    byte 0:       0x0f magic
    byte 1:       0x56 command
    byte 2:       channel index 0..3
    byte 3:       unknown, observed 0
    byte 4:       seconds per sample
    byte 5-244:   120 samples, uint16 big-endian, millivolts
    byte 245:     checksum = sum(frame[0:245]) & 0xff

Observed interval_seconds values:

    1, 2, 4, 8

The charger appears to downsample longer curves by increasing the seconds-per-sample interval.

---

## Dashboard

An example dashboard is included:

    examples/skyrc-mc3000-dashboard.yaml

The dashboard uses ApexCharts Card to plot voltage curves.

---

## Installing ApexCharts Card without HACS

Download the card JavaScript file:

    mkdir -p /config/www

    wget -O /config/www/apexcharts-card.js \
      https://github.com/RomRider/apexcharts-card/releases/latest/download/apexcharts-card.js

Add the Lovelace resource:

    url: /local/apexcharts-card.js
    type: module

In the Home Assistant UI this is usually under:

    Settings -> Dashboards -> Resources

If you use YAML Lovelace configuration, merge the resource into your Lovelace configuration.

---

## Example dashboard setup

A minimal YAML dashboard registration in configuration.yaml:

    lovelace:
      mode: storage
      resources:
        - url: /local/apexcharts-card.js
          type: module
      dashboards:
        skyrc-test:
          mode: yaml
          title: SkyRC Test
          icon: mdi:battery-charging
          show_in_sidebar: true
          filename: skyrc-test.yaml

Then copy the example dashboard to:

    /config/skyrc-test.yaml

or use the included example as a starting point:

    examples/skyrc-mc3000-dashboard.yaml

---

## Dashboard notes

The curve chart uses:

    sample index * interval_seconds

to build the X-axis. This is more accurate than projecting all curves over a fixed time window.

The chart filters out zero samples so empty tail values do not pull the graph down to 0 V.

---

## Writing programs

The `skyrc_mc3000.write_program` service uploads a complete program to one slot.
It implements the official two-frame `0x11` protocol:

- slot selection is a bitmask
- each frame is 20 bytes
- the delay between frames is 50 milliseconds
- the final checksum is cumulative over both frames
- the MC3000 must acknowledge the upload before the service succeeds

Example using the official app's saved `NiMH Charge` values:

```yaml
action: skyrc_mc3000.write_program
data:
  slot: 1
  battery_type: nimh
  operation: charge
  capacity: 3500
  charge_current: 1.0
  discharge_current: 0.2
  charge_voltage: 1650
  discharge_voltage: 1000
  charge_end_current: 990
  discharge_end_current: 200
  cycle_time: 0
  cycle_count: 1
  cycle_type: 0
  delta_v: 10
  trickle_current: 10
  maintenance_voltage: 4150
  protection_temperature: 19
  protection_time: 0
  discharge_time: 0
```

Review every value for the actual battery before calling the service. Use
`skyrc_mc3000.start_slot` separately after the upload and chemistry verification.

---

## Known behavior

### Single-client BLE behavior

The MC3000 does not behave well with multiple simultaneous BLE clients.

Avoid connecting these at the same time:

- Home Assistant integration
- SkyRC companion app
- separate BLE debug scripts

Use Companion App Mode when switching from Home Assistant to the official app.

### Voltage curves are volatile

Voltage curve data can reset or change depending on charger state, slot state, and program activity.

Empty slots or inactive slots may return 120 zero samples.

### Entity IDs

Home Assistant preserves entity IDs in the entity registry.

If you changed integration versions during development, you may see duplicate entities with _2 suffixes. This is usually caused by changed unique IDs during development.

Prefer keeping stable entity IDs and removing stale duplicate entities through:

    Settings -> Devices & services -> Entities

---

## Development notes

Validated protocol commands:

    0x57 version info
    0x61 basic data
    0x55 channel data
    0x56 voltage curve
    0x05 start charge
    0xfe stop charge

Start/stop uses a channel bitmask:

    slot 1 = 0x01
    slot 2 = 0x02
    slot 3 = 0x04
    slot 4 = 0x08
    all    = 0x0f

Voltage-curve parsing is provided by `skyrc-ble==3.0.0` through:

    async def get_voltage_curve_data(channel: int) -> Mc3000VoltageCurveData

The integration retains its older raw-protocol fallback for defensive
compatibility, but the pinned library normally handles this path.

---

## Troubleshooting

### The charger is not found

Check whether Home Assistant sees Bluetooth advertisements for the charger.

The MC3000 usually advertises as:

    Charger
    34:14:B5:xx:xx:xx
    0000ffe0-0000-1000-8000-00805f9b34fb

If you use ESPHome Bluetooth Proxy, ensure:

- the ESPHome device is added to Home Assistant
- Bluetooth Proxy is enabled
- the proxy is close enough to the MC3000
- the SkyRC app is not already connected

### ApexCharts says custom element does not exist

Check that:

    /config/www/apexcharts-card.js

exists and that the Lovelace resource is registered as:

    /local/apexcharts-card.js
    JavaScript module

Then hard-refresh the browser.

### Voltage curve chart is empty

Check:

- the slot has fetched curve data
- the curve sensor has samples_v attributes
- nonzero_sample_count is above 0
- the slot is not empty
- the dashboard entity IDs match your Home Assistant entity registry

### Companion app cannot connect

Enable Companion App Mode in Home Assistant first.

This pauses polling and releases the BLE connection.

---

## License

MIT
