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
