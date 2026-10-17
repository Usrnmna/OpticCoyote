# Ultrasonic sensing (Arduino)

[Documentation index](index.md) · [Project overview](../README.md)

See the [Nano pinout and interface reference](nano-ultrasonic-pinout.md)
for a text wiring graph, pin connections, power notes, and USB commands.

This Nano sketch polls four fixed-address RCWL-1655 or compatible AJ-SR04M I2C ultrasonic sensors through a TCA9548A I2C multiplexer. It reads one sensor at a time. The default reverse build publishes session-tagged snapshots with per-sensor ages while a reverse lease is active. The explicit standalone build publishes cached distances as CSV after `START`. A separate three-reading median filter supplies nearest-object and alarm decisions.

## Base ultrasonic connectivity architecture

```text
Raspberry Pi 5, 4 GB RAM (SBC / USB host, USB-A)
    |
    | USB-A to USB-C data cable
    v
ELEGOO Nano / Arduino-compatible board (USB-C)
    CH340 USB-to-serial bridge <-> ATmega328P microcontroller
    5 V, 16 MHz, 32 KB flash
    |
    | I2C
    v
TCA9548A multiplexer (0x70), one sensor per channel 0-3 by default
    |
    | Isolated downstream I2C channels
    v
4 x RCWL-1655 or compatible AJ-SR04M I2C ultrasonic object-detection modules
```

The specified controller is an **ATmega328P-based Nano**, with a CH340 USB-to-serial bridge. [ELEGOO's Nano specifications](https://eu.elegoo.com/en-be/products/elegoo-nano-v3-0) identify the ATmega328P and CH340 combination. The specified board variant uses USB-C; connector type must match the actual board, since Nano variants also exist with other USB connectors.

The specified SBC is the **Raspberry Pi 5, 4 GB RAM model**. It communicates with the Nano through USB serial. The Nano owns the I2C connection to the four ultrasonic modules. This diagram establishes component roles and communication links; it does not specify the sensor power distribution or constitute a verified electrical schematic. Board reference: [Raspberry Pi 5 product specifications](https://www.raspberrypi.com/products/raspberry-pi-5/).

### Existing implementation and details still to resolve

- **I2C fan-out:** the Nano uses the TCA9548A at mux address `0x70`, with one RCWL-1655 at `0x57` on each of channels 0-3. Devices with the same fixed address remain isolated on separate channels.
- **Pi OLED integration:** the [USB OLED bridge](../rpi-oled-bridge/bridge.py) qualifies reverse GPIO, controls actual sensor acquisition, and forwards four fresh distances at 115200 baud to a second ELEGOO Nano running the [SSD1306 display sketch](../optic_coyote_display/optic_coyote_display.ino). The camera selector's USB input expects JSON camera commands; this display bridge does not select cameras.
- **Earlier GPIO draft:** `draft-gpio-link/` documents a separate Arduino-to-Pi GPIO prototype. It is retained for reference and is outside this base USB connectivity path.

During an active reverse lease, the Nano sends periodic four-zone snapshots with individual sample ages. It retains the I2C conversion wait and enforces at least 10 ms after each read before retriggering that same sensor. The OLED USB path is implemented; physical hardware validation remains required.

Reverse sensor ranging continues when the OLED Nano is absent or its USB link
fails. The display link retries independently and requires a fresh display
session and acknowledgement before receiving current, age-checked distances.
Reverse LOW still stops acquisition and releases distance ownership. Camera
selection, reverse control, and the optional Pi buzzer have independent failure
boundaries; the [combined guide](combined-triggers.md) describes recovery
and the remaining shared power, USB, and scheduling limits.

## Required hardware

- One Arduino-compatible controller
- Four RCWL-1655 or compatible AJ-SR04M modules configured for I2C mode (see below)
- One TCA9548A I2C multiplexer at its default `0x70` address
- A regulated supply appropriate for the Arduino logic voltage
- I2C pull-up resistors if they are not already present on the TCA9548A breakout
- One `0.1 uF` bypass capacitor at each sensor, plus a bulk `10-47 uF` capacitor near the power distribution point

## Sensor configuration

**AJ-SR04M interchangeability:** an AJ-SR04M variant supporting the same I2C protocol can replace an RCWL-1655 on any mux channel, including in a mixed set, without a firmware change. The required operations are 7-bit address `0x57`, write `0x01` to trigger a measurement, wait for conversion (the sketch defaults to `100 ms`), then read three bytes containing a big-endian distance in micrometres and divide by `1000` for millimetres. The same polling, per-sensor cooldown, filtering, and selected reverse/standalone serial protocol apply.

Compatibility depends on the exact AJ-SR04M board revision supporting those operations; its model name alone does not establish I2C support. Confirm its mode-selection setting, SCL/SDA pins, supply/logic levels, measurement time, retrigger limits, and distance range against that board's documentation. The RCWL-1655 R7 setting below is not an AJ-SR04M mode-setting specification. AJ-SR04M interchangeability has not been bench-tested in this project.

Install `100 kOhm` at the RCWL-1655 `R7` position to select I2C mode. The four sensor signals are wired to separate mux channels:

| RCWL-1655 pin/function | TCA9548A connection |
| --- | --- |
| VCC | Common regulated supply |
| GND | Common ground |
| Trig / RX / SCL | `SC0`, `SC1`, `SC2`, or `SC3` |
| Echo / TX / SDA | `SD0`, `SD1`, `SD2`, or `SD3` |

The TCA9548A upstream `SCL` and `SDA` connect to the Arduino's hardware I2C pins. All grounds must be connected together. Keep all I2C pull-ups tied to the selected logic supply; do not mix 3.3 V and 5 V pull-ups.

## Build and upload

The supplied sensor and display builds default to **reverse control**:
no ranging or distance view at boot. Upload both updated sketches and follow
the [reverse-trigger guide](reverse-trigger.md). Its editable JSON provides
100 ms HIGH qualification, immediate observed LOW release, GPIO assignment,
leases, and freshness timing. Standalone CSV behavior below requires
`OPTIC_COYOTE_STANDALONE=1` in the sensor's `reverse_config.h` and rebuilt sensor
firmware. A complete standalone OLED path additionally requires that setting in
the display's `reverse_config.h`, rebuilt display firmware, and the
[standalone bridge procedure](oled-display.md#run-the-pi-bridge-in-standalone-mode).

Open [`optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino`](../optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino) in the Arduino IDE, choose **Arduino Nano**, **ATmega328P**, and the board's serial port, then upload it. If the Nano has the older bootloader, select **ATmega328P (Old Bootloader)**. The sketch only needs the standard `Wire` library. Nano I2C pins are **A4 = SDA** and **A5 = SCL**, connected to the mux upstream pins.

The defaults suit a classic Arduino Uno/Nano:

- Serial rate: `115200`
- Requested minimum full-round interval: `400 ms`, edited with `Config::kPollingIntervalMs`; reverse snapshots are sent every 100 ms while active, standalone CSV per successful reading
- Alarm output: digital pin `8`, active high
- Status heartbeat: built-in LED
- TCA9548A channels: `0`, `1`, `2`, `3`
- Warning threshold: `600 mm`
- Critical threshold: `300 mm`
- Accepted sensor range: `200-5000 mm`

These sensor values are grouped in `Config` near the top of the sketch. Acquisition
leases, reverse report/freshness intervals, and Wire timeout settings are in
[`reverse_config.h`](../optic_coyote_ultrasonic/reverse_config.h).

## Serial output

This subsection describes the explicit **standalone build**. Default reverse
builds use session-tagged `R/K/X/S` packets and do not accept START/STOP as
acquisition control; see [reverse protocol and stale-data protection](reverse-trigger.md#session-protocol-and-stale-data-protection).

Open USB serial at **115200 baud, 8N1**. The program starts silent, including no CSV header. Send uppercase `START` terminated by LF, CR, or CRLF (in Serial Monitor, select a line-ending option). It prints a header and then one record for every successful sensor read, including a measurement already in progress when START arrives. Send `STOP` with a line ending to stop requesting records; an already-started line finishes to preserve CSV framing, and buffered bytes may still arrive. Repeated `START` while streaming has no effect. Unknown, oversized, and incomplete commands do not start streaming. After a board reset, send `START` again; opening the USB port can reset a Nano, so allow its bootloader to finish before sending commands.

Example output after `START`:

```text
time_ms,rear_far_left_mm,rear_left_middle_mm,rear_middle_mm,rear_far_right_mm,nearest_zone,nearest_mm,state
100,742,-1,-1,-1,rear_far_left,742,CLEAR
210,742,515,-1,-1,rear_left_middle,515,WARNING
320,742,515,1204,-1,rear_left_middle,515,WARNING
430,742,515,1204,980,rear_left_middle,515,WARNING
```

The four distance columns hold each sensor's latest successful, unfiltered integer millimetres, in physical sensor order 1-4. The default mux channels are 0-3; `kMuxChannels` can change the channel assignment without changing physical sensor identities. Each successful read replaces only that sensor's cache and requests a packet with all four values, even if the distance is unchanged or no other sensor has responded. A sensor with no successful reading since reset is `-1`. Missing, incomplete, or out-of-range results preserve its last successful value and do not generate a packet. Caches survive STOP/START and clear on reset. Values may be old indefinitely; this eight-column format does not include per-sensor ages or identify which sensor updated.

`nearest_zone`, `nearest_mm`, and `state` use filtered readings from sensors whose latest attempt succeeded. They may differ from the raw cached distance columns, which can include failed sensors' older values. States are `CLEAR`, `WARNING`, `CRITICAL`, and `NO_VALID_SENSORS`. The accepted range remains 200-5000 mm; an out-of-range result is invalid, not automatically `CRITICAL`.

The alarm updates after every attempt, activating for `WARNING` or `CRITICAL`. Failed sensors are excluded from alarm decisions, while earlier successful filter samples are retained for recovery. With no valid sensors, the alarm turns off; because failed attempts send no packet, an all-failed condition does not produce a `NO_VALID_SENSORS` row. There is no separate fault alarm or motor-stop action.

`START`/`STOP` control USB transmission only. Polling, caching, heartbeat, and alarm decisions continue while silent. After START, the next successful read sends a packet without waiting for the rest of the round. A packet is one CSV line ending in CRLF; the USB host must accumulate bytes through the newline because transport reads can split or combine lines.

The sender freezes each packet before queuing its bytes and uses only available UART space. New captured readings during cooldown or transmission remain pending. After the current frame is fully queued, the next loop sends the latest cached set if a reading is pending or the four distances differ from the previous queued snapshot. Finishing an older packet never clears newer pending readings. Under sustained backpressure, intermediate pending readings merge into the latest value per sensor; this is not an unbounded sample history. An unchanged successful reading still requests a packet. "Queued" means accepted by the Nano UART, not acknowledged by the USB host. STOP cancels pending/unstarted frames, finishes any partly queued line, and a subsequent START places its header after that line.

This protects values already captured by the Nano. The existing I2C mode still reads after its conversion wait and does not capture unsolicited acoustic echoes during cooldown.

## Timing and control integration

The Nano triggers one RCWL-1655 at a time with I2C command `0x01`, waits at least 100 ms, then reads the three-byte micrometre result and converts it to millimetres. The module generates its own **40 kHz acoustic burst**; 40 kHz is not the trigger repetition rate or the I2C bus clock. The existing I2C interface does not provide an implemented early-echo notification: these are pushes on completed I2C reads, not interrupts at the instant the echo reaches the transducer.

After the read transaction and mux isolation complete, the Nano records a **10 ms cooldown for that sensor only**. The cooldown uses a fresh clock reading so time spent inside I2C cannot consume it. Another eligible sensor can trigger immediately; USB serial has no cooldown. Failed attempts also cool only the affected sensor, and polling advances without requiring a successful response.

With all sensors responding and serial keeping up, standalone CSV packets arrive
roughly every 100 ms plus processing overhead and each sensor is revisited
roughly every 400 ms. Reverse mode instead schedules snapshots every 100 ms
while its acquisition lease is active, including unavailable or aged readings;
each snapshot need not correspond to a new successful measurement. The
configurable minimum full-round interval remains:

```cpp
constexpr uint32_t kPollingIntervalMs = 400;
```

Increasing this setting delays the next round, not the packet for a completed read. Lowering it cannot bypass conversion or cooldown waits. `kSensorCooldownMs` must be at least 10; `kMeasurementTimeMs` must be at least 100 for the current I2C protocol. See the [RCWL-1655 datasheet, I2C mode on page 5](https://makerhero.com/img/files/download/RCWL-1655-Datasheet.pdf). The older GPIO draft retains its own timing and reporting behavior.

Scheduling uses no `delay()`. Serial writes are limited to `availableForWrite()` space, so a full UART buffer does not block polling. `Wire` calls remain synchronous; supported Wire implementations use the configured operation timeout. A stuck shared I2C bus can still affect all sensors. Physical timing, acoustic interference, and recovery require bench testing; application logic added to `loop()` must return promptly.

## First-power-up checks

Default reverse builds require the [reverse bench checks](reverse-trigger.md#verification).
The following serial-monitor procedure applies to the explicit standalone build.

1. Power the bench assembly with an isolated target for each sensor. In the vehicle installation, all four sensors face directly rearward; confirm their left-to-right identities before mounting.
2. Confirm that the TCA9548A responds at `0x70`.
3. Confirm that `0x57` appears only after selecting one mux channel.
4. Open Serial Monitor at `115200` baud with a newline setting. Confirm silence after reset, send `START`, and verify a header and packets roughly every 100 ms plus overhead when all sensors return readings; check that one working sensor still reports when the others return no result. Send `STOP`, allow buffered bytes to drain, and confirm silence. Send `START` again to resume.
5. Move a broad, flat target through each zone and verify its reported direction.
6. Tune the range and warning constants for the installation.

Do not fire all four sensors simultaneously. Reflections from one transducer can be received by another and create false detections.

Configuration constants and function descriptions are listed in the
[development reference](development.md#arduino-settings-reference).
