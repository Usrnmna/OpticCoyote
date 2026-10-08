# Nano four-sensor pinout and interface reference

For the complete assembly, see the [project wiring scheme](project-wiring.md)
and [controller/module pinouts](component-pinouts.md). This reference
covers the sensor Nano, mux, and sensor interface in detail.

Project Optic Coyote — wiring and firmware reference, 2026-10-02.

Applies to the **ATmega328P Nano with a CH340 USB serial bridge**, four
**RCWL-1655 or compatible AJ-SR04M modules in I2C mode**, and a **TCA9548A multiplexer**. Firmware:
[`optic_coyote_ultrasonic.ino`](../optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino).

This is a signal-name wiring reference, not a manufacturer-certified datasheet
or a verified PCB schematic. Match the printed labels on your actual boards;
the diagrams do not represent physical header order or viewing orientation.

AJ-SR04M is interchangeable on any mux channel when the exact variant supports
the same I2C operations: address `0x57`, trigger byte `0x01`, and a three-byte
big-endian distance in micrometres. Mixed sensor types use the same firmware
and USB commands. Verify the board's I2C mode setting, SCL/SDA labels, voltage,
conversion/retrigger timing, and distance range before substitution. The sketch
defaults to a 100 ms conversion wait and 10 ms per-sensor post-read cooldown.
RCWL-1655 pin aliases and R7 settings below are specific to that module; do not
assume they describe every AJ-SR04M revision. AJ-SR04M compatibility has not
been bench-tested in this project.

## Rear-bumper OLED installation

The Pi can forward this sensor Nano's CSV to a second ELEGOO Nano driving
the SSD1306 display; see the [OLED setup guide](oled-display.md). The
sensor wiring below is unchanged. In the rear-bumper installation, sensors
1-4 are all on the rear bumper, ordered left to right on the OLED. The
front/rear names below are legacy firmware labels, not physical placement
requirements. The Pi bridge can remap the four column positions.

## Signal wiring graph

```text
RASPBERRY PI / USB HOST
        | USB data cable (USB-A to board's USB-C connector)
        | Commands down / distance CSV up
        v
  NANO: ATmega328P / CH340                    TCA9548A
  +---------------------------+          +-------------------------+
  | USB <-> CH340 <-> MCU UART |          | Address: 0x70           |
  |                           |          |                         |
  | A4 / SDA                  |<-------->| SDA (upstream)          |
  | A5 / SCL                  |--------->| SCL (upstream)          |
  | GND                       |----------| GND                     |
  |                           |          |                         |
  | D8: optional alarm output |          | SC0 / SD0: to SENSOR 1  |
  | D13: onboard heartbeat LED|          | SC1 / SD1: to SENSOR 2  |
  +---------------------------+          | SC2 / SD2: to SENSOR 3  |
                                         | SC3 / SD3: to SENSOR 4  |
  No external D0/D1 wiring needed.        | Channels 4-7: unused    |
                                         +-------------------------+

EACH CHANNEL'S TWO SEPARATE WIRES:

  TCA9548A SCn ------------------> RCWL-1655 Trig / RX / SCL
  TCA9548A SDn <-----------------> RCWL-1655 Echo / TX / SDA

  Sensor 1: channel 0, front_left,  fixed address 0x57
  Sensor 2: channel 1, front_right, fixed address 0x57
  Sensor 3: channel 2, rear_left,   fixed address 0x57
  Sensor 4: channel 3, rear_right,  fixed address 0x57

  Set R7 = 100 kOhm on EACH RCWL-1655 to select I2C mode.
  The firmware selects one mux channel at a time.
```

The Nano's hardware I2C signals are A4/SDA and A5/SCL; D13 carries its built-in
LED. These are classic Nano signal assignments; the official Nano uses a
different USB bridge/connector from the specified CH340 board.
[Arduino Nano pinout](https://docs.arduino.cc/resources/pinouts/A000005-full-pinout.pdf)

## Connection table

| From | To | Purpose |
| --- | --- | --- |
| Nano A4 | TCA9548A upstream SDA | I2C data |
| Nano A5 | TCA9548A upstream SCL | I2C clock, firmware default 100 kHz |
| Nano GND | Mux GND and all sensor GND pins | Common signal reference |
| Mux SC0 | Sensor 1 Trig/RX/SCL | Front-left clock |
| Mux SD0 | Sensor 1 Echo/TX/SDA | Front-left data |
| Mux SC1 | Sensor 2 Trig/RX/SCL | Front-right clock |
| Mux SD1 | Sensor 2 Echo/TX/SDA | Front-right data |
| Mux SC2 | Sensor 3 Trig/RX/SCL | Rear-left clock |
| Mux SD2 | Sensor 3 Echo/TX/SDA | Rear-left data |
| Mux SC3 | Sensor 4 Trig/RX/SCL | Rear-right clock |
| Mux SD3 | Sensor 4 Echo/TX/SDA | Rear-right data |
| Peripheral supply rail | Mux supply input and all sensor VCC pins | See power notes below |

All four sensors have the same address. Keep each SDA/SCL pair on its assigned
mux channel; do not join the four downstream buses together. TCA9548A channel
isolation resolves this address conflict.
[TI TCA9548A datasheet](https://www.ti.com/lit/ds/symlink/tca9548a.pdf)

## Power and mux configuration

```text
USB host --------------------------> Nano USB power input

REGULATED +5 V PERIPHERAL RAIL (*) --+--> TCA9548A supply input (**)
                                   +--> Sensor 1 VCC
                                   +--> Sensor 2 VCC
                                   +--> Sensor 3 VCC
                                   +--> Sensor 4 VCC

COMMON GROUND ----------------------+--> Nano GND
                                   +--> TCA9548A GND
                                   +--> Sensor 1/2/3/4 GND

TCA9548A ADDRESS SETTINGS: A2 = LOW, A1 = LOW, A0 = LOW -> 0x70
TCA9548A /RESET: keep HIGH during normal operation.
```

`(*)` The peripheral rail's source is an assembly choice, not established by
the firmware. A Nano 5 V pin feed requires confirmation of the exact board's
USB power path and available current. Alternatively, use a separate regulated
peripheral supply with common ground; do not connect its positive rail to the
USB-powered Nano's 5 V rail without a suitable power-sharing design. Do not
use Nano VIN as a regulated 5 V peripheral output.

`(**)` This reference assumes a mux breakout whose supply input accepts 5 V.
Check its schematic and supply label before connection. The TCA9548A chip
supports 1.65–5.5 V; breakout components can impose additional constraints.
Tie its address inputs low for `0x70`, using the breakout's existing straps
where fitted. Keep active-low RESET pulled up to the mux's own VCC; use its
existing pull-up or fit one if absent. The firmware does not drive RESET.
[TI supply, address, and reset specification](https://www.ti.com/lit/ds/symlink/tca9548a.pdf)

Use pull-ups on SDA and SCL for the upstream bus and each used downstream
segment. Check which are already fitted before adding more. For the common
5 V logic arrangement shown, pull-ups belong on the appropriate 5 V rails;
do not add 3.3 V pull-ups to the same segment. Resistor values depend on wiring
capacitance and existing parallel resistors. The firmware uses 100 kHz I2C.

The RCWL-1655 datasheet lists a 2.8–5.5 V operating range, I2C mode selected by
R7 = 100 kOhm, and fixed 7-bit address `0x57`. Connect by signal label, not an
assumed connector pin order.
[RCWL-1655 datasheet, pages 2 and 5](https://makerhero.com/img/files/download/RCWL-1655-Datasheet.pdf)

Place a 0.1 uF bypass capacitor near each sensor supply connection and a
10–47 uF bulk capacitor near the peripheral distribution point, consistent
with the project wiring guidance. Verify supply stability on the actual build.

## Other Nano pins

| Pin(s) | Current firmware use |
| --- | --- |
| D0/RX, D1/TX | UART shared with the onboard USB serial bridge; leave external connections free for this USB setup |
| D8 | Optional active-high alarm logic output; HIGH for filtered WARNING or CRITICAL |
| D13 / LED_BUILTIN | Onboard heartbeat; toggles every 500 ms |
| D2–D7, D9–D12 | Not used by this sketch |
| A0–A3, A6, A7 | Not used by this sketch |
| AREF, 3V3, VIN, RESET | No external connection required for this USB-powered reference |

D8 is a logic signal, not a supply for a siren, relay coil, or motor. Use a
suitable driver for an external load. No external alarm load is specified
here. Set `kAlarmPin = 255` to disable that output. The heartbeat indicates
loop activity, not successful ranging. No Raspberry Pi GPIO connection is
required for this USB interface.

## USB serial interface

| Property | Firmware behavior |
| --- | --- |
| Serial settings | 115200 baud, 8 data bits, no parity, 1 stop bit |
| Boot/reset | No header or distance output until START |
| Begin transmission | Send uppercase `START` followed by LF, CR, or CRLF |
| Stop transmission | Send uppercase `STOP` followed by a line ending |
| Duplicate START | No effect while already streaming |
| Invalid command | Ignored; does not enable streaming |
| While stopped | Sensor polling, alarm decisions, and heartbeat continue |
| Restart after board reset | Send START again after the bootloader finishes |

```text
Host -> Nano: START\n
Nano -> Host:
time_ms,front_left_mm,front_right_mm,rear_left_mm,rear_right_mm,nearest_zone,nearest_mm,state
1680,742,515,1204,980,front_right,515,WARNING

Host -> Nano: STOP\n
```

`\n` above means a newline byte, not the two literal characters backslash and
`n`. Output rows end with CRLF. The example distances are illustrative.
Each successful sensor read requests one row containing all four sensors' latest successful, unfiltered integer millimetres. Only the responding sensor's cache changes. The other fields retain their last returned values; `-1` means no successful reading since reset. Missing, partial, or out-of-range replies preserve the cache and do not send a packet. The accepted range is 200�5000 mm. Caches survive STOP/START; reset clears them. Cached values can be old indefinitely, and this format has no per-sensor age fields.

`nearest_zone`, `nearest_mm`, and `state` use the retained three-sample filter and exclude sensors whose latest attempt failed. The alarm updates after every attempt. States are CLEAR, WARNING, CRITICAL, and NO_VALID_SENSORS, with thresholds of 600 mm and 300 mm. No valid sensors turns the alarm off, but failed attempts do not send packets, so total failure produces silence rather than a NO_VALID_SENSORS row. After STOP, an already-started line finishes and buffered bytes may still arrive; no further data frames are started. The host must frame rows by newline, not assume one USB read equals one packet.

The sender freezes each packet before queuing its bytes and uses only available UART space. New captured readings during cooldown or transmission remain pending. After the current frame is fully queued, the next loop sends the latest cached set if a reading is pending or the four distances differ from the previous queued snapshot. Finishing an older packet never clears newer pending readings. Under sustained backpressure, intermediate pending readings merge into the latest value per sensor; this is not an unbounded sample history. An unchanged successful reading still requests a packet. "Queued" means accepted by the Nano UART, not acknowledged by the USB host. STOP cancels pending/unstarted frames, finishes any partly queued line, and a subsequent START places its header after that line.

This protects values already captured by the Nano. The existing I2C mode still reads after its conversion wait and does not capture unsolicited acoustic echoes during cooldown.

## Per-reading timing and cooldown

The current I2C implementation triggers one sensor, waits at least 100 ms, reads its result, and disables the mux. It then enforces at least **10 ms from completed I2C processing before retriggering that same sensor**. Other eligible sensors and USB serial continue during that cooldown. A sensor reports without waiting for the other three to return values. START enables the next successful read, including one already in progress.

The sensor module produces its own **40 kHz acoustic burst**. This is separate from the 100 kHz I2C clock and the measurement repetition rate. I2C reading still uses the 100 ms conversion wait; no early-echo interrupt is implemented.

```cpp
constexpr uint32_t kPollingIntervalMs = 400;  // Minimum full-round interval.
constexpr uint16_t kMeasurementTimeMs = 100; // Trigger-to-read wait.
constexpr uint8_t kSensorCooldownMs = 10;  // Per-sensor post-read cooldown; no USB delay.
```

With four responding sensors, packets arrive roughly every 100 ms plus overhead, with each sensor revisited roughly every 400 ms. Raising the full-round interval slows revisits; it never delays publication of an already completed reading. Compile-time checks prevent reducing the conversion wait below 100 ms or the cooldown below 10 ms. Failed attempts advance without requiring a valid return. Synchronous Wire calls and a stuck shared bus can still delay the loop; UART output uses only currently available buffer space.
[RCWL-1655 I2C timing, page 5](https://makerhero.com/img/files/download/RCWL-1655-Datasheet.pdf)

## Investigated alternative: direct trigger/echo GPIO

Status: **proposal only**. The user authorized investigating an interface change; the implemented firmware and wiring above remain I2C. The RCWL-1655 datasheet describes GPIO trigger/echo mode as an alternative to I2C. Its publicly readable [datasheet mirror](https://www.scribd.com/document/901894038/RCWL-1655-Datasheet) has incomplete OCR; the linked original PDF could not be retrieved during investigation. Verify the exact module revision, GPIO mode resistor setting, trigger pulse specification, no-echo behavior, and minimum retrigger interval against a readable datasheet before conversion. No specific resistor modification is approved here.

A candidate Nano pin assignment would bypass the TCA9548A for sensor signals:

| Zone | Nano trigger output | Nano echo input |
| --- | --- | --- |
| front_left | D9 | D2 / PCINT18 |
| front_right | D10 | D3 / PCINT19 |
| rear_left | D11 | D4 / PCINT20 |
| rear_right | D12 | D5 / PCINT21 |

The [Arduino Nano pinout](https://docs.arduino.cc/resources/pinouts/A000005-full-pinout.pdf) confirms those pin-change interrupt inputs. This assignment retains D0/D1 for USB serial, D8 for the alarm, and D13 for heartbeat. Each sensor would need its own direct trigger and echo wire to the Nano, suitable GPIO mode configuration, and the established supply/common ground.

The proposed firmware would timestamp echo edges with pin-change interrupts, calculate distance when the echo pulse ends, and publish the same four-value cached packet from the main loop. Serial writes would stay outside interrupts. One sensor would be triggered at a time to limit cross-talk. A finite no-echo deadline would advance polling without requiring a response; that sensor would then have a minimum 10 ms cooldown. Other eligible sensors and serial would remain independent of its cooldown. Any additional manufacturer minimum per-sensor retrigger interval would also be enforced. The sensor would still generate the 40 kHz acoustic burst itself.

This could remove the fixed I2C read delay, but it does not establish physical response latency, accuracy, or valid acoustic attribution. Conversion requires explicit implementation approval plus confirmation of the module-specific timing/mode details above; it has not been implemented or bench-tested.

## Verification boundary

Connections and settings were checked against the current sketch and the
linked component references. The exact Nano and breakout header layouts,
power budget, pull-up population, wiring, ultrasonic interference, and USB
operation have not been inspected or measured on hardware. Before use, verify
each sensor's physical position against its CSV column and confirm START/STOP
behavior with the assembled system.
