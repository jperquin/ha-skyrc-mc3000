# SkyRC MC3000 Home Assistant Integration

Custom Home Assistant integration for monitoring and basic control of a SkyRC MC3000 battery charger over BLE.

This integration is intended to make the MC3000 visible and controllable from Home Assistant while keeping the charger itself responsible for battery profiles, chemistry settings, current limits, voltage limits and safety cut-offs.

## Current status

Development version, tested on one SkyRC MC3000 installation.

Working features:

- UI setup through Home Assistant config flow
- BLE discovery by advertised MC3000 charger name
- manual BLE address entry when discovery does not find the charger
- read MC3000 basic device data
- read live data from all 4 slots
- start the program already configured on the charger for one slot
- stop one slot
- stop all slots
- button entities for start, stop, stop all and refresh
- expected-chemistry dropdown per slot
- chemistry interlock before starting a slot
- Companion App Mode to release the BLE connection for the SkyRC app
- 10 second polling interval
- slot voltage display precision suggested at 3 decimals
- elapsed time formatted as `H:MM:SS`

## Installation through HACS custom repository

Add this repository as a HACS custom repository with type `Integration`.

Repository:

```text
https://github.com/jperquin/ha-skyrc-mc3000
```

Then install the integration and restart Home Assistant.

## Configuration

Configuration is done through the Home Assistant UI.

Go to:

```text
Settings → Devices & services → Add integration → SkyRC MC3000
```

The setup flow scans for BLE devices named:

- `Charger`
- `SimpleBLEPeripheral`
- `HitecCharger`

If the charger is not discovered, enter the BLE address manually.

Example BLE address format:

```text
34:14:B5:3F:92:3D
```

## Entities

### Device-level entities

- `sensor.input_voltage`
- `sensor.skyrc_mc3000_temperature_unit`
- `sensor.skyrc_mc3000_display_mode`
- `sensor.skyrc_mc3000_cooling_fan_mode`
- `sensor.skyrc_mc3000_system_beep`
- `sensor.skyrc_mc3000_screensaver`
- `switch.skyrc_mc3000_companion_app_mode`
- `button.skyrc_mc3000_refresh`
- `button.skyrc_mc3000_stop_all`

Depending on Home Assistant entity registry history, button entities may have suffixes such as `_2`. Always check the actual entity IDs under:

```text
Settings → Devices & services → SkyRC MC3000 → Entities
```

### Per-slot entities

For each slot 1–4:

- `sensor.slot_X_status`
- `sensor.slot_X_battery_type`
- `sensor.slot_X_mode`
- `sensor.slot_X_voltage`
- `sensor.slot_X_current`
- `sensor.slot_X_capacity`
- `sensor.slot_X_temperature`
- `sensor.slot_X_internal_resistance`
- `sensor.slot_X_elapsed_time`
- `select.skyrc_mc3000_slot_X_expected_chemistry`
- `button.skyrc_mc3000_slot_X_start`
- `button.skyrc_mc3000_slot_X_stop`

Replace `X` with the slot number.

Example:

```text
sensor.slot_1_voltage
select.skyrc_mc3000_slot_1_expected_chemistry
button.skyrc_mc3000_slot_1_start
```

## Companion App Mode

The MC3000 appears to allow only one BLE client at a time. If Home Assistant is connected, the SkyRC companion app may not be able to connect.

Use:

```text
switch.skyrc_mc3000_companion_app_mode
```

When Companion App Mode is enabled:

- Home Assistant disconnects from the MC3000
- polling is paused
- sensor values remain at their last known state
- start/stop commands are blocked
- the SkyRC app can connect to the charger

When Companion App Mode is disabled:

- Home Assistant resumes polling
- the integration reconnects to the charger
- live sensor updates continue

Recommended workflow:

1. Enable Companion App Mode in Home Assistant.
2. Open the SkyRC app.
3. Change charger programs or settings in the SkyRC app.
4. Fully close or disconnect the SkyRC app.
5. Disable Companion App Mode in Home Assistant.
6. Let Home Assistant reconnect and refresh the charger state.

## Services

### `skyrc_mc3000.refresh`

Force an immediate data refresh.

```yaml
action: skyrc_mc3000.refresh
```

### `skyrc_mc3000.start_slot`

Start the currently configured MC3000 program on one slot.

```yaml
action: skyrc_mc3000.start_slot
data:
  slot: 1
```

Before starting, the integration compares the selected expected chemistry with the actual chemistry reported by the charger. If they do not match, the start command is refused.

### `skyrc_mc3000.stop_slot`

Stop one slot.

```yaml
action: skyrc_mc3000.stop_slot
data:
  slot: 1
```

### `skyrc_mc3000.stop_all`

Stop all slots.

```yaml
action: skyrc_mc3000.stop_all
```

## Safety model

This integration starts only the program already configured on the MC3000. It does not program battery chemistry, charge current, discharge current, voltage limits, capacity cut-off, temperature cut-off, time cut-off or other charger profile parameters.

Those settings must be configured on the MC3000 itself or through the SkyRC app.

Before starting a slot from Home Assistant, check on the charger that the correct battery type, cell count, mode, current, voltage limits and safety limits are configured.

The expected-chemistry dropdown in Home Assistant is a start interlock only. It does not change the charger profile.

## Example Lovelace dashboard card

The example below uses standard Home Assistant cards only. No custom frontend cards are required.

Check your actual entity IDs before using this YAML. Existing installations may have suffixes such as `_2` if entities were created before a later integration upgrade.

```yaml
type: vertical-stack
cards:
  - type: entities
    title: SkyRC MC3000
    show_header_toggle: false
    entities:
      - entity: switch.skyrc_mc3000_companion_app_mode
        name: Companion App Mode
      - type: divider
      - entity: sensor.input_voltage
        name: Input voltage
      - entity: sensor.skyrc_mc3000_cooling_fan_mode
        name: Cooling fan
      - entity: sensor.skyrc_mc3000_display_mode
        name: Display
      - entity: sensor.skyrc_mc3000_temperature_unit
        name: Temperature unit
      - entity: sensor.skyrc_mc3000_system_beep
        name: System beep
      - entity: sensor.skyrc_mc3000_screensaver
        name: Screensaver
      - type: divider
      - entity: button.skyrc_mc3000_refresh
        name: Refresh
      - entity: button.skyrc_mc3000_stop_all
        name: Stop all

  - type: grid
    columns: 2
    square: false
    cards:
      - type: entities
        title: Slot 1
        show_header_toggle: false
        entities:
          - entity: sensor.slot_1_status
            name: Status
          - entity: sensor.slot_1_battery_type
            name: Battery
          - entity: sensor.slot_1_mode
            name: Mode
          - entity: sensor.slot_1_voltage
            name: Voltage
          - entity: sensor.slot_1_current
            name: Current
          - entity: sensor.slot_1_capacity
            name: Capacity
          - entity: sensor.slot_1_temperature
            name: Temperature
          - entity: sensor.slot_1_internal_resistance
            name: Resistance
          - entity: sensor.slot_1_elapsed_time
            name: Elapsed time
          - entity: select.skyrc_mc3000_slot_1_expected_chemistry
            name: Expected chemistry
          - type: divider
          - entity: button.skyrc_mc3000_slot_1_start
            name: Start
          - entity: button.skyrc_mc3000_slot_1_stop
            name: Stop

      - type: entities
        title: Slot 2
        show_header_toggle: false
        entities:
          - entity: sensor.slot_2_status
            name: Status
          - entity: sensor.slot_2_battery_type
            name: Battery
          - entity: sensor.slot_2_mode
            name: Mode
          - entity: sensor.slot_2_voltage
            name: Voltage
          - entity: sensor.slot_2_current
            name: Current
          - entity: sensor.slot_2_capacity
            name: Capacity
          - entity: sensor.slot_2_temperature
            name: Temperature
          - entity: sensor.slot_2_internal_resistance
            name: Resistance
          - entity: sensor.slot_2_elapsed_time
            name: Elapsed time
          - entity: select.skyrc_mc3000_slot_2_expected_chemistry
            name: Expected chemistry
          - type: divider
          - entity: button.skyrc_mc3000_slot_2_start
            name: Start
          - entity: button.skyrc_mc3000_slot_2_stop
            name: Stop

      - type: entities
        title: Slot 3
        show_header_toggle: false
        entities:
          - entity: sensor.slot_3_status
            name: Status
          - entity: sensor.slot_3_battery_type
            name: Battery
          - entity: sensor.slot_3_mode
            name: Mode
          - entity: sensor.slot_3_voltage
            name: Voltage
          - entity: sensor.slot_3_current
            name: Current
          - entity: sensor.slot_3_capacity
            name: Capacity
          - entity: sensor.slot_3_temperature
            name: Temperature
          - entity: sensor.slot_3_internal_resistance
            name: Resistance
          - entity: sensor.slot_3_elapsed_time
            name: Elapsed time
          - entity: select.skyrc_mc3000_slot_3_expected_chemistry
            name: Expected chemistry
          - type: divider
          - entity: button.skyrc_mc3000_slot_3_start
            name: Start
          - entity: button.skyrc_mc3000_slot_3_stop
            name: Stop

      - type: entities
        title: Slot 4
        show_header_toggle: false
        entities:
          - entity: sensor.slot_4_status
            name: Status
          - entity: sensor.slot_4_battery_type
            name: Battery
          - entity: sensor.slot_4_mode
            name: Mode
          - entity: sensor.slot_4_voltage
            name: Voltage
          - entity: sensor.slot_4_current
            name: Current
          - entity: sensor.slot_4_capacity
            name: Capacity
          - entity: sensor.slot_4_temperature
            name: Temperature
          - entity: sensor.slot_4_internal_resistance
            name: Resistance
          - entity: sensor.slot_4_elapsed_time
            name: Elapsed time
          - entity: select.skyrc_mc3000_slot_4_expected_chemistry
            name: Expected chemistry
          - type: divider
          - entity: button.skyrc_mc3000_slot_4_start
            name: Start
          - entity: button.skyrc_mc3000_slot_4_stop
            name: Stop
```

## Known limitations

- No charger profile editing from Home Assistant.
- No setting of charge current, discharge current, chemistry, voltage limits or cut-offs from Home Assistant.
- No voltage curve support yet.
- Tested on one MC3000 installation only.

## Development notes

This integration currently uses the public `skyrc-ble` library API for connecting, polling, starting and stopping the MC3000.

Profile editing is intentionally not exposed until the BLE profile/program write protocol is properly understood and validated.
