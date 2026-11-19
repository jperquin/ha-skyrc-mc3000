# MC3000 BLE protocol and feature coverage

This integration implements the eight ordinary BLE commands used by SkyRC's Android app. Two destructive reset commands are intentionally omitted. It retains Home Assistant's Bluetooth transport, including supported Bluetooth proxies; an additional ESP32 client is not required.

This document separates wire-protocol coverage from optional workflows implemented by other projects. Source support does not mean every chemistry, firmware revision and operating mode has been tested on hardware.

## Sources

- **Official SkyRC MC3000 Android app 4.1.2**, obtained from the [SkyRC download endpoint](https://soft.skyrc.com/download/?id=20&key=skyrc_mc3000). SHA-256: `D661C1BD123CE8D795B34643EC4E14BCC4F15BD18B06F41BF5699489016F433D`. Its packet construction, numeric limits and response handling were inspected independently. The download URL can change its contents; the hash identifies the inspected artifact.
- **studiotijn's ESP32/HA implementation**, pinned to commit `9ab9e4b17b31bcf3b67a90e7e8dc61d5c0d0c7de`: [protocol definitions](https://github.com/studiotijn/SkyRC-MC3000-HA-github/blob/9ab9e4b17b31bcf3b67a90e7e8dc61d5c0d0c7de/esphome/components/mc3000/mc3000_protocol.h), [encoder/decoder](https://github.com/studiotijn/SkyRC-MC3000-HA-github/blob/9ab9e4b17b31bcf3b67a90e7e8dc61d5c0d0c7de/esphome/components/mc3000/mc3000_protocol.cpp), [ESPHome workflows](https://github.com/studiotijn/SkyRC-MC3000-HA-github/blob/9ab9e4b17b31bcf3b67a90e7e8dc61d5c0d0c7de/esphome/SkyRC-MC3000.yaml), and [HA workflows](https://github.com/studiotijn/SkyRC-MC3000-HA-github/blob/9ab9e4b17b31bcf3b67a90e7e8dc61d5c0d0c7de/ha/packages/mc3000.yaml).
- **nietonchique's firmware/protocol research**, pinned to commit `73a4acda4fe61b4c691b119fa14ebd1b47b53a70`: [reverse-engineering notes](https://github.com/nietonchique/mc3000-mcp/blob/73a4acda4fe61b4c691b119fa14ebd1b47b53a70/docs/reverse-notes.md). Firmware-dependent observations are treated as observations, not universal guarantees.
- [Official MC3000 manual V1.17](https://www.skyrc.com/download/MC3000_Instruction_Manual_V1.17.pdf) and [product specifications](https://www.skyrc.com/MC3000_Charger).

## Transport and commands

The BLE service is `0000ffe0-0000-1000-8000-00805f9b34fb`; writes and notifications use characteristic `0000ffe1-0000-1000-8000-00805f9b34fb`. Commands use write-without-response and are serialized. Normal frames are 20 bytes: `0x0f`, opcode, payload/padding, then the sum of bytes 0–18 modulo 256.

| Opcode | Operation | Coverage and response |
|---|---|---|
| `0x05` | Start configured slot program | Implemented. Byte 2 is a slot mask. HA checks reported state after starting. |
| `0xFE` | Stop slots | Implemented. HA sends individual slot stops and verifies the result. This avoids firmware differences reported for the all-slot mask. |
| `0x11` | Write a complete work program | Implemented. One 40-byte structure, sent as two consecutive 20-byte writes with a short gap. The checksum is byte 39. Applying a profile does not implicitly start it. |
| `0x55` | Read slot telemetry | Implemented. Request byte 2 is a zero-based slot index, not a mask. |
| `0x56` | Read voltage curve | Implemented. The response is 245 bytes, including 120 voltage samples; it has no trailing checksum. |
| `0x57` | Read firmware/hardware version | Implemented. The known version-response checksum quirk is handled separately. |
| `0x61` | Read basic settings | Implemented. Returns the six settings listed below. |
| `0x63` | Write basic settings | Implemented. Read/modify/write preserves other settings; subsequent `0x61` readback verifies the result. ACK byte 2 must be `1`. |
| `0x65` | Restore factory settings | **Intentionally omitted.** Destructive maintenance operation. |
| `0x66` | Restore calibration data | **Intentionally omitted.** Can discard calibration; not a routine control. |

Slot masks are `1`, `2`, `4`, `8`; telemetry/curve indices are `0`–`3`. Responses are matched by opcode and, where applicable, slot/mask. Partial or timed-out exchanges discard the connection so late fragments cannot confirm a later command.

An upload ACK confirms receipt, not a complete parameter readback. The integration can subsequently check reported chemistry, mode and running state; **reading all programmed settings back over BLE is not supported**. Firmware 1.13 and 1.27 have been reported to behave differently for `0x11`; intermediate firmware behavior is not assumed.

## Work-program fields: `0x11`

All multi-byte numeric fields are unsigned big-endian. Main-current API values use amperes; other API values use the wire units below. The editor converts voltage values between volts and millivolts.

| Bytes | Meaning | Units / notes |
|---|---|---|
| 2 | Target slots | Bitmask |
| 3 | Chemistry | Code below |
| 4 | Operation | Chemistry-dependent code below |
| 5–6 | Capacity limit | mAh; zero disables the limit outside Break-in |
| 7–8 | Charge current | mA |
| 9–10 | Discharge current | mA |
| 11–12 | Charge termination voltage | mV; also the target voltage for Storage |
| 13–14 | Discharge cutoff voltage | mV |
| 15–16 | Charge termination current | mA |
| 17–18 | Discharge reduction/end current | mA |
| 19 | Rest after charge | Minutes |
| 20 | Cycle repetitions | 1–99 |
| 21 | Cycle sequence | Normally `0=C>D`, `1=C>D>C`, `2=D>C`, `3=D>C>D`; Break-in uses `0=C>D>C`, `1=D>C>D` |
| 22 | Negative delta-V | mV; applicable nickel modes only |
| 23 | Trickle current | Value × 10 mA; applicable nickel modes only |
| 24–25 | Restart-charge threshold | mV; zero disables restart |
| 26 | Battery temperature cutoff | °C, irrespective of the display temperature unit |
| 27–28 | Safety time limit | Minutes; zero disables it; Android sends zero for Break-in |
| 29 | Rest after discharge | Minutes |
| 30–38 | Reserved | Zero-filled; no documented settings are assigned here |
| 39 | Checksum | Sum of bytes 0–38 modulo 256 |

The Android parameter ranges and mode-dependent restrictions are enforced by [`program_validation.py`](../custom_components/skyrc_mc3000/program_validation.py). Every program field is required: omitted values are not silently filled in. Break-in derives charge/discharge currents from nominal capacity. Nickel-only delta-V/trickle fields are cleared when inactive. Eneloop subtype presets affect capacity/current defaults; they are not an additional wire field.

### Chemistry and operation codes

| Chemistry code | Chemistry | Operation codes |
|---|---|---|
| 0, 1, 2, 8, 9 | Li-ion, LiFePO₄, Li-ion 4.35 V, LTO, Na-ion | `0=Charge`, `1=Refresh`, `2=Storage`, `3=Discharge`, `4=Cycle` |
| 3, 4, 6 | NiMH, NiCd, Eneloop | `0=Charge`, `1=Refresh`, `2=Break-in`, `3=Discharge`, `4=Cycle` |
| 5, 7 | NiZn, RAM | **`0=Charge`, `1=Refresh`, `2=Discharge`, `3=Cycle`** |

NiZn/RAM require the compact mode mapping on both encoding and decoding. Na-ion exists in the inspected Android version; no minimum supporting firmware version is asserted here. A reported chemistry is the selected program chemistry, not automatic identification of the physical cell.

## Telemetry fields: `0x55`

| Bytes | Meaning | HA representation |
|---|---|---|
| 2 | Slot index | Slot 1–4 entities |
| 3 | Chemistry code | Named chemistry or preserved unknown numeric code |
| 4 | Operation code | Chemistry-aware operation or preserved unknown code |
| 5 | Cycle counter | Neutral “Cycle counter” label; not asserted to mean completed cycles |
| 6 | Status/error code | Named status or preserved unknown numeric code |
| 7–8 | Elapsed seconds | Formatted duration; the raw field is only 16 bits |
| 9–10 | Voltage, mV | Volts, retaining millivolt resolution |
| 11–12 | Current, mA | Positive amperes; charge/discharge direction comes from status |
| 13–14 | Current phase capacity, mAh | Capacity sensor; separate observed charge/discharge phase values are retained |
| 15 | Slot/battery temperature | Converted to °C using the global temperature unit |
| 16–17 | Internal resistance, mΩ | `0`, `1` and `65535` mean unavailable, not measured resistance |
| 18 | LED mask | Bits 0–3 red, bits 4–7 green; per-slot red/green/off display, raw evidence in diagnostics |
| 19 | Checksum | Validated before accepting normal telemetry |

Unknown chemistry, mode or status codes do not discard otherwise valid readings. Controls reject unsupported states. Retained phase capacities are **observations**, not guaranteed final capacity results: missed transitions, removal, resets, observation gaps and HA restarts affect continuity. Their attributes explain scope and continuity. They are separate from the explicit quality-test result.

Power in watts is calculated as voltage × current. The BLE frame does not contain separate energy, fan RPM, charger-case temperature or measured supply-voltage fields. The cycle counter's exact completed-versus-current semantics and elapsed-counter overflow behavior are not claimed beyond the received values.

### Known status/error codes

| Codes | Meaning |
|---|---|
| 0 / 1 / 2 / 3 / 4 | Standby / Charge / Discharge / Rest or pause / Done |
| 128 / 129 | Input voltage too low / too high |
| 130 / 131 | MCP3424 measurement errors 1 / 2 |
| 132 / 133 | Cell connection interrupted / Check voltage |
| 134 / 135 | Capacity protection / Time protection |
| 136 / 137 | Charger temperature high / Battery temperature high |
| 138 / 139 | Short circuit / Reverse polarity |
| Other | Unknown numeric code; preserved for diagnosis |

“Done” does not provide a separate normal-termination-reason payload. Error codes are not additional temperature or voltage measurements.

## Basic settings and versions

The `0x61` response and `0x63` write share these offsets:

| Bytes | Setting | Values |
|---|---|---|
| 2 | Temperature unit | `0=°C`, `1=°F` |
| 3 | System beep | `0=off`, `1=on` |
| 4 | Display backlight policy | `0=off`, `1=auto`, `2=1 min`, **`3=3 min`**, `4=5 min`, `5=always on` |
| 5 | Screensaver | `0=off`, `1=on` |
| 6 | Cooling-fan policy | `0=auto`, `1=off`, `2=on`, `3..9=20/25/30/35/40/45/50°C` |
| 7–8 | Input low-voltage cutoff | 10–12 V in 0.1 V steps, encoded as mV |
| 9–18 | Reserved | No supported interpretation; zero-filled on writes |

These are configuration values. Fan policy is not fan speed, backlight policy is not measured display state, and input cutoff is **not actual adapter voltage**. Settings writes are serialized, require idle slots and verify all six values after writing.

The `0x57` response reports firmware in bytes 14–15 and hardware in byte 16. Other bytes are not assigned undocumented meanings. Diagnostic capture omits raw version-response bytes because they may contain identifying data. Manual/document version numbers must not be used as firmware feature gates.

## Curves, final observations and diagnostics

`0x56` returns a 5-byte header followed by 120 big-endian millivolt samples. Bytes 3–4 contain the interval in seconds. There is no trailing checksum. Zero buffer entries are not plotted as sudden voltage drops. CSV export preserves the full received buffer and elapsed sample times; it is not a wall-clock history export.

Manual curve reading works for idle/completed slots as well as active ones. When automatic reading is enabled, an observed run reaching Idle or Done schedules a final curve read; an intermediate rest does not. Reads are throttled, failed final reads can be retried, and a new run supersedes the old pending buffer. This cannot reconstruct an operation never observed while connected. Current-stop markers are derived from polling, not hardware timestamps for the completion of an entire multi-stage cycle.

Protocol diagnostics retain a bounded set of recent response evidence and counters for checksum errors, malformed/unmatched responses, timeouts and transport failures. They do not send probing commands. Raw reserved bytes are evidence, not decoded new features. Quality-test reports offer JSON, CSV, Markdown and SVG; ordinary curve CSV and a quality-test report have different contents and purposes.

## Workflows: coverage and deliberate differences

The ESP32 project's advanced behavior also lives in its [ESPHome YAML](https://github.com/studiotijn/SkyRC-MC3000-HA-github/blob/9ab9e4b17b31bcf3b67a90e7e8dc61d5c0d0c7de/esphome/SkyRC-MC3000.yaml) and [HA package](https://github.com/studiotijn/SkyRC-MC3000-HA-github/blob/9ab9e4b17b31bcf3b67a90e7e8dc61d5c0d0c7de/ha/packages/mc3000.yaml). These are not additional charger opcodes.

| Workflow | This integration |
|---|---|
| Named full profiles, per-slot/group apply and start/stop | Supported; apply and start are separate actions. |
| Physical-cell records, slot assignments, notes, favorites and colors | Supported. Model/type text is stored per cell; there is no shared normalized model catalog. |
| Explicit capacity, IR and multi-stage quality tests | Supported, including rest phases and optional 24-hour voltage-drift observation. Voltage drift is not converted into percentage capacity loss. |
| Last observed charge/discharge capacities | Supported with continuity metadata; not a guarantee of an unobserved final result. |
| Hardware Storage mode | Supported through the normal program payload. |
| ESP “Storage now” with I×R compensation and repeated rest/correction | Not implemented as an equivalent external control loop. Hardware Storage is a different algorithm. |
| Automatic IR test on cell insertion | Not implemented; IR requires an explicit action. Insertion alone does not identify chemistry or allowable current. |
| Independent host temperature stop for every manual/front-panel program | Not implemented as a universal policy. Profiles have the device cutoff, and quality tests have their own supervision. |
| Automatic cooling/reduced-current retries after faults | Not implemented as an equivalent unattended recovery policy. Tests stop or pause and require explicit recovery. |
| ESP condition verdicts from capacity and reference resistance | Not claimed equivalent. Reports expose measurements and measured/rated capacity ratio, not a safety certification. |

The charger supports up to 3 A charge and 2 A discharge per slot, with shared limits of 50 W charging and 15 W discharging. The official manual specifies four lithium cells at up to 1 A each, or one lithium cell above 1 A with no other slot busy. Requested current and measured current must remain distinct; battery permission for a larger current does not change hardware capability.

## Unsupported reads and other transports

- No BLE command for listing the charger's numbered program catalog or reading all slot-program settings back was established in the inspected Android/ESP implementations. Android profiles are local app records sent as complete programs; they are not a BLE view of charger programs 01–30.
- Internal MCU-to-MCU UART commands and USB HID commands are different interfaces. In particular, references to `0x5F` profile reads or upgrade commands do not establish a usable BLE GATT API. They are not sent speculatively.
- USB descriptions include additional settings, program numbers, energy and higher-resolution measurements. Their offsets and semantics must not be copied into the shorter BLE frames.
- Reserved bytes, unfamiliar codes and unknown timing behavior remain explicitly unknown. Factory reset, calibration reset and firmware-update operations are outside routine integration controls.
