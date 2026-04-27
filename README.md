# SkyRC MC3000 Home Assistant Integration

Custom Home Assistant integration for monitoring and controlling a SkyRC MC3000 battery charger over BLE.

## Current status

Development version.

Tested features:

- Read MC3000 basic data over BLE
- Read slot data for 4 channels
- Start a slot using the program already configured on the charger
- Stop one slot
- Stop all slots
- Expected chemistry dropdown per slot
- Chemistry interlock before starting a slot
- Button entities for start, stop, stop all, and refresh

## Entities

Device-level:

- Input voltage

Per slot:

- Status
- Battery type
- Mode
- Voltage
- Current
- Capacity
- Temperature
- Internal resistance
- Elapsed time
- Count
- LED
- Expected chemistry
- Start button
- Stop button

## Services

### skyrc_mc3000.refresh

Force an immediate data refresh.

### skyrc_mc3000.start_slot

Start the currently configured MC3000 program on one slot.

Example:

    action: skyrc_mc3000.start_slot
    data:
      slot: 1

The integration does not set charge current, battery chemistry, voltage limits, or program parameters. These must be configured on the MC3000 itself.

Before starting, the integration compares the selected expected chemistry with the actual chemistry reported by the charger. If they do not match, the start command is refused.

### skyrc_mc3000.stop_slot

Example:

    action: skyrc_mc3000.stop_slot
    data:
      slot: 1

### skyrc_mc3000.stop_all

Example:

    action: skyrc_mc3000.stop_all

## Configuration

Configuration is done through the Home Assistant UI.

Go to Settings -> Devices & services -> Add integration -> SkyRC MC3000.

The setup flow scans for BLE devices named Charger, SimpleBLEPeripheral, or HitecCharger. If the charger is not discovered, enter the BLE address manually.

## Safety model

This integration starts only the program already configured on the MC3000. It does not program battery chemistry or charging parameters.

Check chemistry, cell count, current, voltage limits, and battery condition on the charger before use.

## Installation through HACS custom repository

Add this repository as a custom repository in HACS with type Integration, then install and restart Home Assistant.

## Example Lovelace dashboard card

The example below uses standard Home Assistant cards only. Entity IDs may differ slightly on existing installations if Home Assistant has already assigned entity names before installing newer versions of the integration.

```yaml
type: vertical-stack
cards:
  - type: entities
    title: SkyRC MC3000
    show_header_toggle: false
    entities:
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
      - entity: button.skyrc_mc3000_refresh_2
        name: Refresh
      - entity: button.skyrc_mc3000_stop_all_2
        name: Stop all

  - type: grid
    columns: 2
    square: false
    cards:
      - type: entities
        title: Slot 1
        entities:
          - sensor.slot_1_status
          - sensor.slot_1_battery_type
          - sensor.slot_1_mode
          - sensor.slot_1_voltage
          - sensor.slot_1_current
          - sensor.slot_1_capacity
          - sensor.slot_1_temperature
          - sensor.slot_1_internal_resistance
          - sensor.slot_1_elapsed_time
          - sensor.slot_1_count
          - sensor.slot_1_led
          - select.skyrc_mc3000_slot_1_expected_chemistry_2
          - type: divider
          - button.skyrc_mc3000_slot_1_start_2
          - button.skyrc_mc3000_slot_1_stop_2

      - type: entities
        title: Slot 2
        entities:
          - sensor.slot_2_status
          - sensor.slot_2_battery_type
          - sensor.slot_2_mode
          - sensor.slot_2_voltage
          - sensor.slot_2_current
          - sensor.slot_2_capacity
          - sensor.slot_2_temperature
          - sensor.slot_2_internal_resistance
          - sensor.slot_2_elapsed_time
          - sensor.slot_2_count
          - sensor.slot_2_led
          - select.skyrc_mc3000_slot_2_expected_chemistry_2
          - type: divider
          - button.skyrc_mc3000_slot_2_start_2
          - button.skyrc_mc3000_slot_2_stop_2

      - type: entities
        title: Slot 3
        entities:
          - sensor.slot_3_status
          - sensor.slot_3_battery_type
          - sensor.slot_3_mode
          - sensor.slot_3_voltage
          - sensor.slot_3_current
          - sensor.slot_3_capacity
          - sensor.slot_3_temperature
          - sensor.slot_3_internal_resistance
          - sensor.slot_3_elapsed_time
          - sensor.slot_3_count
          - sensor.slot_3_led
          - select.skyrc_mc3000_slot_3_expected_chemistry_2
          - type: divider
          - button.skyrc_mc3000_slot_3_start_2
          - button.skyrc_mc3000_slot_3_stop_2

      - type: entities
        title: Slot 4
        entities:
          - sensor.slot_4_status
          - sensor.slot_4_battery_type
          - sensor.slot_4_mode
          - sensor.slot_4_voltage
          - sensor.slot_4_current
          - sensor.slot_4_capacity
          - sensor.slot_4_temperature
          - sensor.slot_4_internal_resistance
          - sensor.slot_4_elapsed_time
          - sensor.slot_4_count
          - sensor.slot_4_led
          - select.skyrc_mc3000_slot_4_expected_chemistry_2
          - type: divider
          - button.skyrc_mc3000_slot_4_start_2
          - button.skyrc_mc3000_slot_4_stop_2
