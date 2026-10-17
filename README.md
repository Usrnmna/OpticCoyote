# Project Optic Coyote

Release: **v0.5.1-beta**. Debian packaging uses **`0.5.1~beta`**.
The Debian package and Trixie arm64 offline bundle use this beta version.
See the [installation package guide](docs/installation-package.md) for setup
and verification boundaries.

## Recommended Raspberry Pi OS

Use **Raspberry Pi OS Lite (64-bit), Debian 13 Trixie**, on the
**Raspberry Pi 5 with 4 GB RAM**. The [Pi 5 setup guide](docs/rpi5-setup.md)
covers image installation, packages, permissions, console HDMI output, component
configuration, and hardware acceptance checks. This recommendation is not a
completed hardware compatibility qualification.

The [installation package guide](docs/installation-package.md) covers the
Debian package, offline dependency bundle, installed CLI commands, configuration,
and separate camera/reverse systemd services. Initial package installation leaves
services disabled. Successful `sudo optic-coyote-setup` enables both for boot
without starting them immediately; failed configuration leaves both disabled.

## Wiring and pinout documentation

- [Project wiring scheme](docs/project-wiring.md): whole-project text diagram,
  wire-by-wire sensor/OLED connections, power and ground, cameras, and the
  optional GPIO draft and protected blinker trigger inputs.
- [Component pinouts](docs/component-pinouts.md): Nano header diagram,
  ATmega328P signal mapping, TCA9548A package diagram, sensor/OLED signal maps,
  and the Raspberry Pi header pins used by the draft.
- [Reverse trigger](docs/reverse-trigger.md): qualified GPIO activation, leased
  sensor acquisition, per-sensor freshness, and temporary OLED ownership.
- [Reverse diagnostics](docs/reverse-diagnostics.md): Pi-side GPIO/USB checks,
  editable test limits, and separate software and hardware evidence.
- [Combined reverse/blinker operation](docs/combined-triggers.md): GPIO/USB
  conflict checks, independent output ownership, and software integration tests.
- [Optional Pi buzzer](docs/pi-buzzer.md): DIYables passive module at 3.3 V DC,
  active-low PWM defaults, callable finite patterns, cancellation, and editable
  JSON; playback disabled until a BCM pin and wiring are configured. Active
  buzzer support remains available.
- [Sensor interface reference](docs/nano-ultrasonic-pinout.md) and
  [OLED installation guide](docs/oled-display.md): firmware-specific setup and
  operating details.

These references distinguish firmware-defined signals from board-dependent
connector layouts and supply requirements. Physical wiring remains unverified.

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
4 x RCWL-1655 or compatible AJ-SR04M I2C ultrasonic object-detection modules
```

The specified controller is an **ATmega328P-based Nano**, with a CH340 USB-to-serial bridge. The phrase "arduino style esp32" in the request is interpreted using those explicit part numbers: the controller is ATmega328P, not ESP32. [ELEGOO's Nano specifications](https://eu.elegoo.com/en-be/products/elegoo-nano-v3-0) identify the ATmega328P and CH340 combination. USB-C here is the user-specified board variant; connector type must match the actual board, since Nano variants also exist with other USB connectors.

The installed SBC is the **Raspberry Pi 5, 4 GB RAM model**. It communicates with the Nano through USB serial. The Nano owns the I2C connection to the four ultrasonic modules. This diagram establishes component roles and communication links; it does not specify the sensor power distribution or constitute a verified electrical schematic. Board reference: [Raspberry Pi 5 product specifications](https://www.raspberrypi.com/products/raspberry-pi-5/).

### Existing implementation and details still to resolve

- **I2C fan-out:** the Nano uses the TCA9548A at mux address `0x70`, with one RCWL-1655 at `0x57` on each of channels 0-3. Devices with the same fixed address remain isolated on separate channels.
- **Pi OLED integration:** the [USB OLED bridge](rpi-oled-bridge/bridge.py) qualifies reverse GPIO, controls actual sensor acquisition, and forwards four fresh distances at 115200 baud to a second ELEGOO Nano running the [SSD1306 display sketch](optic_coyote_display/optic_coyote_display.ino). The camera selector's USB input expects JSON camera commands; this display bridge does not select cameras.
- **Earlier GPIO draft:** `draft-gpio-link/` documents a separate Arduino-to-Pi GPIO prototype. It is retained for reference and is outside this base USB connectivity path.

During an active reverse lease, the Nano sends periodic four-zone snapshots with individual sample ages. It retains the I2C conversion wait and enforces at least 10 ms after each read before retriggering that same sensor. The OLED USB path is implemented; physical hardware validation remains required.

Reverse sensor ranging continues when the OLED Nano is absent or its USB link
fails. The display link retries independently and requires a fresh display
session and acknowledgement before receiving current, age-checked distances.
Reverse LOW still stops acquisition and releases distance ownership. Camera
selection, reverse control, and the optional Pi buzzer have independent failure
boundaries; the [combined guide](docs/combined-triggers.md) describes recovery
and the remaining shared power, USB, and scheduling limits.

## Rear-bumper OLED display

The [OLED setup guide](docs/oled-display.md) covers the second Nano's wiring,
firmware upload, Pi dependencies, USB port selection, and verification commands.
Both Nanos connect to separate Pi USB-A ports using USB-A-to-USB-C data cables.
The new display Nano drives a 0.91-inch **SSD1306 128x32 I2C OLED** on A4/SDA and
A5/SCL. Its four fixed columns show sensors **1, 2, 3, 4 from left to right**, in
feet with one decimal place, for example `1.0 2.0 3.0 4.0`.

The default order follows sensor positions 1-4 (mux channels 0-3). The existing
front/rear CSV labels remain in standalone mode; this installation places all
four sensors on the rear bumper. `--sensor-order` adjusts the physical cable
mapping. Reverse mode displays `--.-` for failed or stale sensors and releases
the OLED to its idle renderer on LOW. The explicitly selected standalone mode
retains the original CSV's per-sensor freshness limitation.

## Existing components

This repository contains ultrasonic sensing, a Pi-to-Nano OLED display path,
camera selection, and a separate draft GPIO camera connection. The display bridge
consumes tagged sensor snapshots in reverse mode or CSV in standalone mode. The camera program remains independent; the
draft provides an alternative Arduino sketch and Pi camera-warning listener.

| Component | Purpose | Files |
| --- | --- | --- |
| Ultrasonic sensing | Poll four RCWL-1655 or compatible AJ-SR04M I2C sensors through an I2C multiplexer and report distances over serial. | [`optic_coyote_ultrasonic/`](optic_coyote_ultrasonic/) |
| OLED display | Receive four distances on a second Nano and display decimal feet in sensor order. | [`optic_coyote_display/`](optic_coyote_display/) |
| Pi USB distance bridge | Gate ranging/OLED distance ownership from reverse GPIO, or explicitly run standalone CSV forwarding. | [`rpi-oled-bridge/`](rpi-oled-bridge/) |
| AHD camera selection | Show one of four AHD cameras on a Raspberry Pi HDMI display, selected manually through GPIO/serial/stdin or by an optional two-input blinker mode. | [`rpi-ahd-selector/`](rpi-ahd-selector/) |
| Optional Pi buzzer | Explicitly play configurable active-buzzer rhythms or passive PWM tones; no automatic trigger bindings. | [`rpi-buzzer/`](rpi-buzzer/), [configuration](rpi-buzzer/buzzer.json), [API and wiring limits](docs/pi-buzzer.md) |
| Draft GPIO connection | Send the nearest warning's camera number from Arduino; receive it in a separate Pi listener. | [`draft-gpio-link/`](draft-gpio-link/) |

Start with the [manual review and adjustment guide](#manual-review-and-adjustment-guide) for a file map, setting tables, function descriptions, and checks to run after editing. Hardware setup follows below for [Arduino sensing](#ultrasonic-sensing-arduino) and [Raspberry Pi cameras](#ahd-camera-selection-raspberry-pi).

## Draft Arduino-to-Pi GPIO connection

This draft establishes a local wired connection with no network communication or recording. Upload its standalone Arduino sketch instead of the sensor-only sketch, then run the Pi listener. The listener can report camera numbers by itself or send JSON commands through the camera selector's standard input.

The Pi listener must already be running to read GPIO. A wire changing level does not itself launch a Linux program. Start the listener once using the command below; it then reacts to incoming warnings until stopped. Automatic boot startup and launching a new process for each warning are outside this draft.

### Draft files and manual adjustment

| File | Review and edit here |
| --- | --- |
| [`arduino_camera_warning.ino`](draft-gpio-link/arduino_camera_warning/arduino_camera_warning.ino) | `Config` contains the sensor settings. `CameraLink` contains output pins and the sensor-to-camera map. `setupCameraLink()` initializes outputs; `publishCameraWarning()` updates them from `publishCompletedScan()`. This self-contained reference prototype retains automatic filtered CSV output; it does not implement the Nano USB stream protocol. |
| [`warning_receiver.py`](draft-gpio-link/warning_receiver.py) | Top-level defaults and `--help` expose GPIO and timing settings. `decode_camera()` reads the logical selection, `StableCamera` filters short transitions, `report_camera()` formats it, and `listen()` owns GPIO setup/cleanup. |
| [`test_warning_receiver.py`](draft-gpio-link/test_warning_receiver.py) | Software checks for all 16 wire combinations, transitions, cleanup, settings, and command acceptance by the camera selector. |

### Signal and camera mapping

Four signal wires encode one camera number by holding **exactly one** active. This is a held selection, not binary encoding, a pulse count, or a distance measurement. Both WARNING and CRITICAL select the nearest valid sensor's associated camera. Equal distances favor the earlier sensor in the configured order. A complete scan updates the selection, approximately every 420 ms plus processing overhead with default settings when all triggers succeed. Failed triggers skip the measurement wait.

| Sensor zone | Camera number | Arduino output | Pi BCM input | Pi physical header pin |
| --- | --- | --- | --- | --- |
| front_left | 1 | D4 | GPIO17 | 11 |
| front_right | 2 | D5 | GPIO27 | 13 |
| rear_left | 3 | D6 | GPIO22 | 15 |
| rear_right | 4 | D7 | GPIO23 | 16 |

Camera numbers refer to entries 1-4 in the existing camera configuration's `sources` list. Edit `CameraLink::kCameraForSensor` to match where the physical cameras actually face. Multiple zones may share a camera. The output pins always remain ordered camera 1, 2, 3, 4. Pins D4-D7 assume a classic Uno/Nano; check availability on your actual Arduino board.

At startup, `cameraLinkSettingsValid()` checks that output pins are distinct, within the board's digital-pin range, and do not overlap serial pins 0/1, SDA/SCL, alarm, or heartbeat. Each sensor must map to camera 1-4. Invalid settings print `ERROR: check CameraLink pins and sensor-to-camera map` and halt before GPIO setup or measurements. Valid settings initialize all camera outputs LOW. On a selection change, the sketch clears every output before setting the selected output HIGH; repeated selections do not rewrite the pins.

The default listener prints a number on each stable change:

- `1` through `4`: that camera has the nearest warning.
- `0`: all lines inactive. This includes clear readings, no valid sensors, Arduino reset/power loss, or disconnected wiring; these conditions cannot be distinguished by this link.
- `-1`: multiple lines are active, an invalid combination. A diagnostic also goes to standard error.

The default warning threshold is 600 mm and the critical threshold is 300 mm, inherited from the sensor sketch. Invalid sensors are excluded. There is no fault wire, acknowledgement, link heartbeat, or timeout: a frozen Arduino output can look like a continuing warning. This is a connection prototype, not a validated protective control.

### Wiring the draft link

**Never connect a 5 V Arduino GPIO directly to a Pi input.** Pi GPIO uses 3.3 V logic; see the [official Raspberry Pi GPIO voltage documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#voltage-specifications). The following draft interface uses four NPN transistor stages, one per camera, to keep Arduino voltage off the Pi GPIO and make Pi LOW mean active.

For each row in the mapping table, wire a small-signal NPN transistor (for example a 2N3904; verify its actual collector/base/emitter pinout):

```text
Arduino D4/D5/D6/D7 ---- 10 kOhm ---- NPN base
                                     |
                                  100 kOhm
                                     |
Common GND --------------------------+---- NPN emitter

Pi 3.3 V ---- 10 kOhm ----+---- corresponding Pi GPIO input
                         |
                         +---- NPN collector

Arduino GND ------------------ Pi GND (for example physical pin 6)
```

Repeat all three resistors and the transistor for each of the four channels. The collector pull-up goes to **Pi 3.3 V**, physical pin 1 or 17, never Arduino 5 V. Grounds are shared; do not join the boards' 5 V supply rails. The base pull-down holds each transistor off while the Arduino output is an input during reset. Arduino HIGH turns that channel on, making its Pi input LOW. Inactive Pi inputs read HIGH. Keep the default receiver polarity for this circuit; `--active-high` is only for a separately designed non-inverting 3.3 V interface.

Wire with power removed. Before attaching the signal inputs to the Pi, power the interface and check that each collector is near 3.3 V when inactive and near 0 V when selected. Check transistor pinouts and all four channels. Keep prototype wires short; long cable noise and vehicle electrical protection are not addressed by this draft.

### Upload and run the standalone draft

1. Open [`draft-gpio-link/arduino_camera_warning/arduino_camera_warning.ino`](draft-gpio-link/arduino_camera_warning/arduino_camera_warning.ino) in Arduino IDE. Choose your board and port; upload this sketch **instead of** the original. It requires only the board's standard `Wire` library. Sensor wiring remains as documented below. This older standalone draft streams filtered CSV automatically at boot; it does not implement the Nano firmware's `START`/`STOP` commands or polling interval setting.
2. Copy this project to the Pi, for example `~/ProjectOpticCoyote`. Provide `python3-gpiozero` and `python3-lgpio` using the existing Pi installation instructions, or provision packages offline. The receiver uses [GPIO Zero's input device API](https://gpiozero.readthedocs.io/en/stable/api_input.html#digitalinputdevice) and [lgpio pin factory](https://gpiozero.readthedocs.io/en/stable/api_pins.html#lgpio).
3. Start the listener from a Pi terminal:

```sh
cd ~/ProjectOpticCoyote
python3 draft-gpio-link/warning_receiver.py
```

The listener samples every 10 ms and accepts a state after 30 ms of stability. It reports an already-held warning at startup, prints changes only, and releases GPIO on Ctrl+C or SIGTERM. The listener does not start or switch the camera program in its default mode.

To change wiring or timing without editing Python:

```sh
python3 draft-gpio-link/warning_receiver.py --pins 17 27 22 23 --debounce-seconds 0.05
```

### Receiver options

Run `python3 draft-gpio-link/warning_receiver.py --help` from the project root for the command-line interface.

| Option | Default | Behavior |
| --- | --- | --- |
| `--pins BCM BCM BCM BCM` | `17 27 22 23` | Four distinct BCM numbers in 0-27, ordered camera 1-4; check board availability separately. |
| `--sample-seconds` | `0.01` | Finite polling interval from 0.001 to 1 second. |
| `--debounce-seconds` | `0.03` | Finite stable-state interval from 0 to 5 seconds. Zero accepts the current state on its first sample. |
| `--active-high` | Off | Use HIGH-active inputs with pull-downs; requires a compatible interface instead of the documented NPN circuit. |
| `--selector-json` | Off | Emit JSON for camera 1-4 only; suppress clear/conflict commands. |
| `--simulate STATE ...` | Off | Immediately report supplied values from -1 through 4 without GPIO or debounce; repeated values are printed too. |

### Optional connection to the camera program

After the standalone wiring test, pipe the listener's optional JSON output into the existing selector's standard input:

```sh
cd ~/ProjectOpticCoyote
python3 draft-gpio-link/warning_receiver.py --selector-json | python3 rpi-ahd-selector/selector.py
```

The receiver sends commands such as `{"camera": 2}` only for valid warnings. Clear or conflicting inputs send no camera command; the selector in manual mode keeps displaying its last selected camera. The pipe uses the selector's standard-input interface. The supplied camera configuration has `gpio_pins: []`, `serial_port: null`, and `trigger_enabled: false`. Keep those settings for this test, and stop any other running selector instance first: only the draft listener should own these GPIO inputs. The draft is separate from blinker trigger mode and does not provide its BOTH/stop behavior. Capture device configuration and video dependencies still need to match the installation.

Use Ctrl+C in the foreground terminal to stop both programs. If the listener exits alone, the existing selector deliberately continues displaying its last camera after input closes; stop it separately if needed. This draft does not supervise the camera process or automatically restart either program.

### Draft checks and validation boundary

Run software tests and a simulated report from the project root (use `python` instead of `python3` on Windows if needed):

```sh
python3 -m unittest discover -s draft-gpio-link -p "test_*.py" -v
python3 draft-gpio-link/warning_receiver.py --simulate 0 1 2 3 4 0
python3 draft-gpio-link/warning_receiver.py --selector-json --simulate 0 1 2 3 4 0
```

Simulation checks output formatting only; it does not read GPIO or exercise timing. On hardware, test clear startup, an object in each zone, overlapping warnings, warning removal, Arduino reset, and receiver restart during a held warning. Compare Arduino CSV `nearest_zone` with the Pi camera number. In camera mode, verify each number displays the intended physical camera. Expect sensor scan/filter delay plus GPIO debounce; software timing does not establish actual end-to-end response time.

The receiver tests use simulated inputs and fake GPIO resources. They cover decoding, debounce transitions, output formatting, selector command acceptance, argument validation, and cleanup. They do not validate Arduino firmware execution, electrical behavior, sensor response, or live camera switching. Compile the draft for your actual board and perform the wiring checks before use.

## Ultrasonic sensing (Arduino)

See the [Nano pinout and interface reference](docs/nano-ultrasonic-pinout.md)
for a text wiring graph, pin connections, power notes, and USB commands.

This Nano sketch polls four fixed-address RCWL-1655 or compatible AJ-SR04M I2C ultrasonic sensors through a TCA9548A I2C multiplexer. It reads one sensor at a time and, when commanded to stream, publishes all four sensors' cached distances in one CSV record per successful sensor reading. A separate three-reading median filter supplies nearest-object and alarm decisions.

### Required hardware

- One Arduino-compatible controller
- Four RCWL-1655 or compatible AJ-SR04M modules configured for I2C mode (see below)
- One TCA9548A I2C multiplexer at its default `0x70` address
- A regulated supply appropriate for the Arduino logic voltage
- I2C pull-up resistors if they are not already present on the TCA9548A breakout
- One `0.1 uF` bypass capacitor at each sensor, plus a bulk `10-47 uF` capacitor near the power distribution point

### Sensor configuration

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

### Build and upload

The supplied sensor and display builds now default to **reverse control**:
no ranging or distance view at boot. Upload both updated sketches and follow
the [reverse-trigger guide](docs/reverse-trigger.md). Its editable JSON provides
100 ms HIGH qualification, immediate observed LOW release, GPIO assignment,
leases, and freshness timing. Standalone CSV behavior below requires
`OPTIC_COYOTE_STANDALONE=1` in both `reverse_config.h` files and rebuilt firmware.

Open [`optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino`](optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino) in the Arduino IDE, choose **Arduino Nano**, **ATmega328P**, and the board's serial port, then upload it. If your Nano has the older bootloader, select **ATmega328P (Old Bootloader)**. The sketch only needs the standard `Wire` library. Nano I2C pins are **A4 = SDA** and **A5 = SCL**, connected to the mux upstream pins.

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
[`reverse_config.h`](optic_coyote_ultrasonic/reverse_config.h).

### Serial output

This subsection describes the explicit **standalone build**. Default reverse
builds use session-tagged `R/K/X/S` packets and do not accept START/STOP as
acquisition control; see [reverse protocol and stale-data protection](docs/reverse-trigger.md#session-protocol-and-stale-data-protection).

Open USB serial at **115200 baud, 8N1**. The program starts silent, including no CSV header. Send uppercase `START` terminated by LF, CR, or CRLF (in Serial Monitor, select a line-ending option). It prints a header and then one record for every successful sensor read, including a measurement already in progress when START arrives. Send `STOP` with a line ending to stop requesting records; an already-started line finishes to preserve CSV framing, and buffered bytes may still arrive. Repeated `START` while streaming has no effect. Unknown, oversized, and incomplete commands do not start streaming. After a board reset, send `START` again; opening the USB port can reset a Nano, so allow its bootloader to finish before sending commands.

Example output after `START`:

```text
time_ms,front_left_mm,front_right_mm,rear_left_mm,rear_right_mm,nearest_zone,nearest_mm,state
100,742,-1,-1,-1,front_left,742,CLEAR
210,742,515,-1,-1,front_right,515,WARNING
320,742,515,1204,-1,front_right,515,WARNING
430,742,515,1204,980,front_right,515,WARNING
```

The four distance columns hold each sensor's latest successful, unfiltered integer millimetres, in mux channel order 0-3. Each successful read replaces only that sensor's cache and requests a packet with all four values, even if the distance is unchanged or no other sensor has responded. A sensor with no successful reading since reset is `-1`. Missing, incomplete, or out-of-range results preserve its last successful value and do not generate a packet. Caches survive STOP/START and clear on reset. Values may be old indefinitely; this eight-column format does not include per-sensor ages or identify which sensor updated.

`nearest_zone`, `nearest_mm`, and `state` use filtered readings from sensors whose latest attempt succeeded. They may differ from the raw cached distance columns, which can include failed sensors' older values. States are `CLEAR`, `WARNING`, `CRITICAL`, and `NO_VALID_SENSORS`. The accepted range remains 200-5000 mm; an out-of-range result is invalid, not automatically `CRITICAL`.

The alarm updates after every attempt, activating for `WARNING` or `CRITICAL`. Failed sensors are excluded from alarm decisions, while earlier successful filter samples are retained for recovery. With no valid sensors, the alarm turns off; because failed attempts send no packet, an all-failed condition does not produce a `NO_VALID_SENSORS` row. There is no separate fault alarm or motor-stop action.

`START`/`STOP` control USB transmission only. Polling, caching, heartbeat, and alarm decisions continue while silent. After START, the next successful read sends a packet without waiting for the rest of the round. A packet is one CSV line ending in CRLF; the USB host must accumulate bytes through the newline because transport reads can split or combine lines.

The sender freezes each packet before queuing its bytes and uses only available UART space. New captured readings during cooldown or transmission remain pending. After the current frame is fully queued, the next loop sends the latest cached set if a reading is pending or the four distances differ from the previous queued snapshot. Finishing an older packet never clears newer pending readings. Under sustained backpressure, intermediate pending readings merge into the latest value per sensor; this is not an unbounded sample history. An unchanged successful reading still requests a packet. "Queued" means accepted by the Nano UART, not acknowledged by the USB host. STOP cancels pending/unstarted frames, finishes any partly queued line, and a subsequent START places its header after that line.

This protects values already captured by the Nano. The existing I2C mode still reads after its conversion wait and does not capture unsolicited acoustic echoes during cooldown.

### Timing and control integration

The Nano triggers one RCWL-1655 at a time with I2C command `0x01`, waits at least 100 ms, then reads the three-byte micrometre result and converts it to millimetres. The module generates its own **40 kHz acoustic burst**; 40 kHz is not the trigger repetition rate or the I2C bus clock. The existing I2C interface does not provide an implemented early-echo notification: these are pushes on completed I2C reads, not interrupts at the instant the echo reaches the transducer.

After the read transaction and mux isolation complete, the Nano records a **10 ms cooldown for that sensor only**. The cooldown uses a fresh clock reading so time spent inside I2C cannot consume it. Another eligible sensor can trigger immediately; USB serial has no cooldown. Failed attempts also cool only the affected sensor, and polling advances without requiring a successful response.

With all sensors responding and serial keeping up, packets arrive roughly every 100 ms plus processing overhead and each sensor is revisited roughly every 400 ms. The configurable minimum full-round interval remains:

```cpp
constexpr uint32_t kPollingIntervalMs = 400;
```

Increasing this setting delays the next round, not the packet for a completed read. Lowering it cannot bypass conversion or cooldown waits. `kSensorCooldownMs` must be at least 10; `kMeasurementTimeMs` must be at least 100 for the current I2C protocol. See the [RCWL-1655 datasheet, I2C mode on page 5](https://makerhero.com/img/files/download/RCWL-1655-Datasheet.pdf). The older GPIO draft retains its own timing and reporting behavior.

Scheduling uses no `delay()`. Serial writes are limited to `availableForWrite()` space, so a full UART buffer does not block polling. `Wire` calls remain synchronous; supported Wire implementations use the configured operation timeout. A stuck shared I2C bus can still affect all sensors. Physical timing, acoustic interference, and recovery require bench testing; application logic added to `loop()` must return promptly.

### First-power-up checks

Default reverse builds require the [reverse bench checks](docs/reverse-trigger.md#verification).
The following serial-monitor procedure applies to the explicit standalone build.

1. Power the system with the sensor heads aimed in different directions.
2. Confirm that the TCA9548A responds at `0x70`.
3. Confirm that `0x57` appears only after selecting one mux channel.
4. Open Serial Monitor at `115200` baud with a newline setting. Confirm silence after reset, send `START`, and verify a header and packets roughly every 100 ms plus overhead when all sensors return readings; check that one working sensor still reports when the others return no result. Send `STOP`, allow buffered bytes to drain, and confirm silence. Send `START` again to resume.
5. Move a broad, flat target through each zone and verify its reported direction.
6. Tune the range and warning constants for the installation.

Do not fire all four sensors simultaneously. Reflections from one transducer can be received by another and create false detections.

## AHD camera selection (Raspberry Pi)

The supplied configuration displays live video from one of four cameras fullscreen through the Pi HDMI output at 1280x720. It starts on a configured camera and supports continuous selection through standard input and **both GPIO and USB serial** once their pins/port are configured; GPIO and serial are initially disabled. It uses no recording, video files, Ethernet, Wi-Fi, HTTP, RTSP or cloud service. Keep source and sink edits local and live-only: the configured GStreamer strings are executable pipeline instructions, and validation does not enforce that restriction.

Optional [blinker trigger mode](#blinker-trigger-mode) starts with no camera capture, selects a mapped left/right camera, and retains that view through blinker OFF gaps. BOTH stops camera capture and displays black. This mode uses two protected GPIO inputs and owns selection exclusively; it does not change the sensor or OLED firmware.

### Hardware

```text
AHD camera 1 --> AHD-to-USB UVC capture 1 --+
AHD camera 2 --> AHD-to-USB UVC capture 2 --+
AHD camera 3 --> AHD-to-USB UVC capture 3 --+--> powered USB hub --> Pi 5 (4 GB) --> HDMI display
AHD camera 4 --> AHD-to-USB UVC capture 4 --+

Controller --> four GPIO selection wires and/or physical USB serial --> Pi
```

The Pi cannot accept AHD coax directly. Each camera needs an **AHD-capable decoder/capture device** compatible with its resolution and frame rate. The program expects four independently accessible Linux V4L2 capture devices. A single four-channel unit is suitable if its Linux driver exposes four independent feeds, not just a combined quad-view image. No DVR/NVR or recording hardware is required.

The installation uses the GRACETOP USB-A 2.0 AHD capture adapter identified below. Its published specifications describe the intended interface; operation on the Raspberry Pi 5 (4 GB) remains unverified. Ordinary composite/CVBS USB adapters cannot be assumed to accept AHD.

Use a suitable Pi power supply, cooling and a powered USB hub. All four cameras remain connected, but only the selected capture is opened. This reduces USB bandwidth and decode load. Switching interrupts video while the next capture starts; seamless switching is not implemented.

#### GreenYi camera identity

The AHD cameras used for the project, including the left and right views, are
the **GreenYi cameras identified by Amazon ASIN B0C3R5Y7K1**:
[GreenYi reverse/front/side camera product link](https://www.amazon.com/GreenYi-Reverse-Trailer-Adjustable-Fisheye/dp/B0C3R5Y7K1).
This reference identifies the installation component; it is not a hardware
test result. The Amazon page could not be retrieved for independent listing
verification on 2026-10-14. Exact camera revision, supply requirements, harness
pinout, selected AHD mode, and native frame rate require confirmation from the
received hardware and its documentation.

The cameras provide AHD signals to the GRACETOP capture adapters. MJPEG is the
adapter's USB capture format. The adapter's advertised 1280×720 at 60 fps mode
does not establish that these cameras produce 60 distinct exposures per second.
Record the GreenYi ASIN and actual camera mode with each capture test report.

#### GRACETOP adapter identity and advertised specifications

Product references, checked 2026-10-14:

- [Amazon USB-A item, ASIN B0DZ2HT7TD](https://www.amazon.com/dp/B0DZ2HT7TD?th=1): model number **GTDE-ABV2USBC**; manufacturer part number **GTUS-AHD2USB**.
- [GRACETOP AHD Capture Card product page](https://www.gracetop.com/products/433t54w43): AHD-to-USB capture family and format specifications.

The specified installation variant is **USB-A 2.0**. The Amazon model identifier contains `USBC`, and GRACETOP's shared product description also names USB Type-C despite offering USB-A and USB-C variants. Retain the ASIN, variant, model number, and part number together; the model text alone does not establish connector type or PCB revision.

The following values are **vendor listing claims, not measurements of the installed adapter**:

| Property | Advertised specification |
| --- | --- |
| Input | AHD 720p/1080p video and audio; PAL/NTSC compatibility |
| Capture protocol | UVC/UAC; plug-and-play support including Linux |
| MJPEG output | 1280×720 at 60 fps; 1920×1080 at 30 fps |
| YUY2 output | Up to 1280×720 at 10 fps; 1920×1080 at 5 fps |
| Input connector | 1.25 mm, four-pin terminal; advertised signals are 5 V output, ground, video input, and audio input |
| Power consumption | Less than 3 W |

Source: [GRACETOP specifications](https://www.gracetop.com/products/433t54w43). Connector orientation, lead order, camera supply requirements, and the 5 V output's current capacity require confirmation on the actual hardware. The listing is not a verified harness pinout. See [camera wiring](docs/project-wiring.md#camera-and-monitor-connectors).

No Pi enumeration, sustained capture, unique-frame-rate, decode performance, HDMI output, or switching-latency result has been recorded for this adapter in the project. The advertised 60 fps USB mode does not establish 60 distinct camera exposures per second. General Linux support does not establish successful operation with the installed Pi OS/kernel, hub, cables, and cameras. The [verification procedure](#verify-mjpeg-720p60-on-the-pi) separates these evidence levels.

### Install on the Pi

Recommended target: **Raspberry Pi OS Lite (64-bit), Debian 13 Trixie**, on the **Raspberry Pi 5 with 4 GB RAM**, and a monitor supporting 720p60 on the first HDMI port. Complete the [Pi 5 setup guide](docs/rpi5-setup.md) for OS installation and whole-project provisioning. For camera-only setup, copy [`rpi-ahd-selector/`](rpi-ahd-selector/) to `~/rpi-ahd-selector` using an SD card or USB drive. Install these packages once, or pre-provision the OS image for a completely offline installation:

```sh
sudo apt update
sudo apt install python3 gstreamer1.0-tools gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav \
  v4l-utils python3-gpiozero python3-lgpio python3-serial
sudo usermod -aG video,render,gpio,dialout "$USER"
```

Reboot after changing groups. Operation requires no network connection. Package installation needs locally supplied packages or a pre-provisioned image when networking is unavailable. Run from a local console without a desktop compositor owning the display. If needed, set console boot through `sudo raspi-config`.

For a consistent 720p console mode, append this to the **existing single line** in `/boot/firmware/cmdline.txt`, then reboot:

```text
video=HDMI-A-1:1280x720@60D
```

The program uses [GStreamer's KMS sink](https://gstreamer.freedesktop.org/documentation/kms/index.html) with a default video format of 1280x720 at 60 frames/s. The console setting above requests a 60 Hz display mode; the pipeline frame rate alone does not prove the HDMI refresh rate. See [Raspberry Pi KMS configuration](https://www.raspberrypi.com/documentation/computers/configuration.html#set-the-kms-display-mode). Camera frames may repeat to meet the configured frame rate. Confirm actual HDMI resolution in the monitor information screen. If two displays are attached, add `connector-id=NUMBER` to the configured sink; `modetest -M vc4 -c` (package `libdrm-tests`) lists connector IDs. Output is HDMI, not analog AHD.

### Configure the capture devices

```sh
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/ /dev/v4l/by-path/
v4l2-ctl -d /dev/video0 --list-formats-ext
```

Replace each `device=` value in [`config.json`](rpi-ahd-selector/config.json) with the correct capture node. `/dev/video0,2,4,6` are placeholders. Prefer stable `/dev/v4l/by-id/...` names, or `/dev/v4l/by-path/...` if identical adapters lack unique serial numbers. Keep adapters on the same hub ports for path-based identification. Some devices also expose metadata nodes; those are not video streams.

Initial pipelines negotiate format automatically. For predictable bandwidth and quality, select an explicitly supported format based on `--list-formats-ext`. After verifying the GRACETOP adapter's advertised MJPEG 720p60 mode, a source entry can use:

```text
v4l2src device=/dev/v4l/by-path/YOUR_DEVICE do-timestamp=true ! image/jpeg,width=1280,height=720,framerate=60/1 ! jpegdec
```

For raw YUYV capture (called YUY2 by GStreamer), the listing advertises only 10 fps at 720p. Use this alternative only if the actual device enumerates and captures that mode:

```text
v4l2src device=/dev/v4l/by-path/YOUR_DEVICE do-timestamp=true ! video/x-raw,format=YUY2,width=1280,height=720,framerate=10/1
```

Request only adapter-supported formats. Capture uses [GStreamer's V4L2 source](https://gstreamer.freedesktop.org/documentation/video4linux2/v4l2src.html). Non-16:9 video is scaled with borders. Frames pass through memory to the display; they are not saved.

#### Verify MJPEG 720p60 on the Pi

For an automated report, use the [Pi-side adapter diagnostic](#pi-side-adapter-diagnostic).
The manual commands below remain useful for inspecting individual steps.

These are **bench procedures to run on the Raspberry Pi 5 (4 GB), not completed test results**. Stop the selector and any other capture program first. Connect and independently power a compatible AHD camera. Run each adapter separately using its actual video-capture node; repeat with the intended hub and cabling. Install the packages above before testing.

1. Enumerate devices and advertised driver modes:

   ```sh
   v4l2-ctl --list-devices
   ls -l /dev/v4l/by-id/ /dev/v4l/by-path/
   capture_device='/dev/video0'
   v4l2-ctl --device="$capture_device" --all
   v4l2-ctl --device="$capture_device" --list-formats-ext
   ```

   Replace `/dev/video0` with the identified capture node before proceeding, preferably its stable path. Look for FourCC **`MJPG`**, **1280×720**, and **60.000 fps** (approximately 0.016667 seconds per frame). This establishes only what the driver exposes. A 59.94 fps mode is distinct from exact 60 fps; use its reported interval rather than forcing `60/1`.

2. Request the mode, read back the accepted settings, and receive 600 buffers in one device session:

   ```sh
   timeout --signal=INT --kill-after=5s 30s \
     v4l2-ctl --device="$capture_device" \
       --set-fmt-video=width=1280,height=720,pixelformat=MJPG \
       --set-parm=60 --get-fmt-video --get-parm \
       --stream-mmap=4 --stream-count=600 --stream-to=/dev/null
   ```

   Confirm the returned format and rate, rather than assuming the request was accepted unchanged. Check the reported capture rate and any driver errors or dropped-buffer reports. At 60 buffers/s, 600 buffers represent about ten seconds of capture plus startup overhead. A timeout, fallback format, lower rate, or error is not a pass. `/dev/null` discards the video; nothing is recorded. Command references: upstream [V4L2 streaming options](https://github.com/gjasny/v4l-utils/blob/master/utils/v4l2-ctl/v4l2-ctl-streaming.cpp) and [frame-rate options](https://github.com/gjasny/v4l-utils/blob/master/utils/v4l2-ctl/v4l2-ctl-misc.cpp).

3. Exercise MJPEG negotiation and JPEG decoding without HDMI or frame-rate conversion:

   ```sh
   timeout --signal=INT --kill-after=5s 30s \
     gst-launch-1.0 -e -v \
       v4l2src device="$capture_device" num-buffers=600 do-timestamp=true \
       ! image/jpeg,width=1280,height=720,framerate=60/1 \
       ! jpegdec ! fakesink sync=false
   ```

   Require successful negotiation of the requested caps and normal end-of-stream after 600 buffers, without decoder errors or timeout. This tests receipt and decoding; the caps alone do not measure sustained throughput. No `videorate` is used, so this procedure does not insert frames to satisfy the requested output rate. GStreamer references: [v4l2src](https://gstreamer.freedesktop.org/documentation/video4linux2/v4l2src.html) and [jpegdec](https://gstreamer.freedesktop.org/documentation/jpeg/jpegdec.html).

After successful capture/decode checks, update the appropriate `sources` entries with the verified stable paths and mode, run `python3 selector.py --check-config`, then test actual HDMI playback and LEFT/RIGHT/BOTH transitions. The supplied JSON remains automatically negotiated until installation-specific values are verified. Driver enumeration, successful frame receipt, decoded output, distinct camera frames, HDMI refresh, and end-to-end latency are separate findings; none implies all the others. Record the test date, Pi OS/kernel, adapter identifiers/revision, camera mode, hub/port, accepted format/rate, observed buffer rate, and errors. No hardware result should be marked verified from listing text or host-only tests.

#### Pi-side adapter diagnostic

[`diagnose_adapter.py`](rpi-ahd-selector/diagnose_adapter.py) inventories one
explicit V4L2 device and performs separate compressed-capture and JPEG-decoding
tests. It runs locally on the **Raspberry Pi 5 with 4 GB RAM**, discards video
buffers, and saves readable `.txt` and structured `.json` reports. It does not
change selector configuration or start/stop the selector service. Stop other
capture programs and connect a continuously powered compatible AHD camera before
running it. Repeat for each adapter and the intended USB hub/port arrangement.

Install the additional GStreamer Python bindings, then identify the capture node:

```sh
sudo apt install python3-gi gir1.2-gstreamer-1.0
cd ~/rpi-ahd-selector
v4l2-ctl --list-devices
python3 diagnose_adapter.py --device /dev/video0
```

Replace `/dev/video0` with the verified capture node or stable
`/dev/v4l/by-id/...` or `/dev/v4l/by-path/...` path. The script does not select a
device automatically. Use the system `python3` with the installed GI bindings.
The earlier installation packages provide `v4l2-ctl`, `v4l2src`, and `jpegdec`.
Dependencies can be pre-provisioned for offline operation.

All test settings are in [`diagnostic.json`](rpi-ahd-selector/diagnostic.json),
separate from the playback configuration:

| Setting | Default | Meaning |
| --- | --- | --- |
| `device` | `null` | Explicit capture path; `--device` overrides this value. |
| `width`, `height`, `fps` | `1280`, `720`, `60` | Required MJPEG mode, using integer fps. Fractional 59.94 fps is not exact 60 fps. |
| `warmup_buffers` | `60` | Initial buffers excluded from rate measurement. |
| `measurement_buffers` | `600` | Buffers counted after warmup, approximately ten seconds at 60 fps. |
| `rate_tolerance_percent` | `5.0` | Allowed mean delivery-rate deviation in either direction; default 57–63 buffers/s. Negotiated caps must still be exact 60/1. |
| `max_buffer_gap_seconds` | `0.25` | Maximum interval between delivered buffers after warmup, including the boundary from the final warmup buffer. A longer gap fails even if subsequent bursts restore the mean rate. |
| `test_timeout_seconds` | `30.0` | Total limit per capture/decode worker, including startup and teardown. Must exceed nominal warmup plus measurement duration. |
| `probe_timeout_seconds` | `10.0` | Limit per V4L2 inventory command. |
| `cleanup_timeout_seconds` | `3.0` | Additional bounded wait for process termination after a timeout or interruption. Unconfirmed cleanup stops further device operations. |

For installation-specific tuning, copy the settings to `diagnostic.local.json`:

```sh
cp diagnostic.json diagnostic.local.json
python3 diagnose_adapter.py --config diagnostic.local.json --check-config
python3 diagnose_adapter.py --config diagnostic.local.json --device /dev/video0
python3 diagnose_adapter.py --device /dev/video0 --capabilities-only
```

`--check-config` performs no hardware access. `--capabilities-only` reads device
identity and modes but marks both hardware tests **SKIPPED**. Test runs save
timestamped reports under `diagnostic-reports/` beside the script; `--report-dir`
selects another directory. The default report directory and local configuration
are ignored by Git. Reports retain configuration, observed host model/kernel,
reported memory, V4L2 identity/modes, negotiated caps, counts, timing, warnings,
maximum measured gap, cleanup status/PID, errors, and command output. Existing
local configurations must include both `max_buffer_gap_seconds` and
`cleanup_timeout_seconds`; missing settings are rejected before device access.
The specified Pi 5 4 GB model is recorded separately
from observed host information; reported usable memory is not an independent
validation of the nominal RAM variant. Adapter model/revision, camera mode, and
physical hub/cable details still require a bench record.

The report separates three evidence levels:

- **Detected capabilities:** discrete `MJPG` modes returned by V4L2 enumeration.
  Unsupported output formats or continuous/stepwise ranges remain in the raw
  log and are not inferred as discrete support. A detected mode is never a pass.
- **Capture test:** exact negotiated MJPEG input/output caps, full nonempty buffer
  counts, normal end-of-stream, measured rate within tolerance, and maximum
  measured gap within its configured limit.
- **Decode test:** the same conditions with `jpegdec` inserted, checking raw
  output dimensions/rate and counting compressed input and decoded output
  separately. Wrong output dimensions or dropped frames fail. Empty input,
  CORRUPTED, GAP, and DECODE_ONLY flags are rejected before decoding, even if the
  decoder removes those flags. Invalid output buffers also fail. Capture success
  does not imply decode success.

Each test reports **PASS**, **FAIL**, **INCONCLUSIVE**, or **SKIPPED**. Timeouts,
GStreamer errors, incomplete/invalid buffers, wrong caps, out-of-range rates,
excessive gaps, and failed pipeline teardown fail. Queued errors/warnings are
drained after EOS before teardown; EOS alone is insufficient for a pass.
Missing tools/bindings, malformed evidence, warnings, or worker stderr
produce an inconclusive result requiring inspection. Capture and decode run
sequentially in isolated workers. After timeout or Ctrl+C, the parent kills the
worker and waits for at most `cleanup_timeout_seconds` to confirm exit. If exit
cannot be confirmed, the PID is reported and subsequent device operations are
skipped. Inspect the process and device before running another diagnostic. OS
process creation is not interruptible by the Python timeout, and an
uninterruptible kernel wait can prevent immediate reaping even after kill.
Process creation time is deducted from the remaining test budget; a completed
worker that exceeds the total budget cannot pass. Ctrl+C cancels the run without
claiming a completed report.

Exit status is `0` only when both hardware tests pass; `1` indicates at least one
non-pass result, including capabilities-only runs; `2` indicates a configuration
or report-writing error; `130` indicates interruption. A missing V4L2 utility
leaves inventory unconfirmed even if independent GStreamer tests pass.

With warmup enabled, rate is `measured buffers / (last measured arrival - last
warmup arrival)`. With zero warmup, the first arrival establishes the baseline,
so rate is `(measured buffers - 1) / (last arrival - first arrival)`. Both use a
monotonic clock. The maximum gap covers the same interval, including the first
post-warmup interval. Evidence validation checks finite, consistent counts,
durations, rates, gaps, caps types, and parent-observed elapsed time; malformed
evidence cannot pass. There is no frame-rate conversion, display synchronization,
recording, or network transport. A pass covers only the measured duration and
configured tolerance and gap limit; it does not prove long-term stability, absence of jitter,
distinct camera exposures, image correctness, HDMI output, or trigger timing.
The implementation uses GStreamer's [fakesink handoff signal](https://gstreamer.freedesktop.org/documentation/coreelements/fakesink.html)
and [bus error/EOS handling](https://gstreamer.freedesktop.org/documentation/tutorials/basic/concepts.html).
Decoded output uses the [jpegdec raw-video interface](https://gstreamer.freedesktop.org/documentation/jpeg/jpegdec.html).

Host checks use synthetic modes, measurements, and subprocess outcomes:

```sh
cd ~/rpi-ahd-selector
python3 -m unittest test_diagnose_adapter -v
```

These checks verify software classification, simulated decoder failures, report
generation, and actual host child-process timeout cleanup, not adapter
or Pi hardware behavior. No physical diagnostic result is supplied by the repository.

### Run and select

```sh
cd ~/rpi-ahd-selector
python3 selector.py
```

In manual mode, set `initial_camera` to 1–4 (default 1). Trigger mode ignores this startup selection and begins in IDLE. Ctrl+C stops the program. Use `--config PATH` for another configuration.

Serial/stdin commands are newline-terminated JSON objects containing exactly one action:

```json
{"inputs":[0,1,0,0]}
{"camera":4}
{"status":true}
```

The stdin/stdout command connection is optional. A failed read, readiness check,
or reply write disables that connection without stopping camera playback or
GPIO/serial monitoring. Capture subprocesses use null stdin/stdout and retain
standard-error diagnostics. A missing `python3-serial` package disables only the
optional serial worker; installing it requires a selector restart. Serial device
disconnections retry automatically. Short or missing reply-write counts are
treated as connection failures; later commands in that batch are discarded.
Serial reconnects discard incomplete input from the previous connection.
Shutdown is checked before each command, including after a blocking read, and
after reply preparation before the reply is handed to the transport. Commands
already applied and writes already started cannot be recalled. SIGINT/SIGTERM
still stop the selector.

In manual mode, the four inputs correspond to cameras 1–4. One active input selects that camera. All zero holds the previous selection. Multiple active inputs select the lowest numbered camera. Commands are complete snapshots, latch until changed and need no continuous retransmission. Rapid commands coalesce to the latest selection. Invalid commands leave selection unchanged and return an error. `inputs` accepts four JSON booleans or integer 0/1 values; `camera` requires an integer 1-4 and `status` requires `true`. Trigger mode rejects both selection commands in every state; status remains available over stdin and configured serial. Blank lines are ignored. Commands may contain at most 1024 bytes before the newline; an oversized line is discarded in full and receives an error when its newline arrives. An incomplete final line is not executed at input EOF.

#### GPIO selection

For manual mode, set `gpio_pins` to four distinct **BCM GPIO numbers** in camera order. GPIO is initially disabled because the wiring has not been specified. An example is `[17,27,22,23]` (physical header pins 11, 13, 15 and 16); confirm those pins are free before wiring.

With `gpio_active_low: true`, inputs use internal pull-ups and activate when connected to Pi ground through a switch, dry contact or compatible open-drain output. For active-high 3.3 V logic, set `gpio_active_low: false` to use pull-downs. Never connect 5 V, 12 V or RS-232 directly to GPIO. Confirm controller voltage and common-ground/isolation requirements first.

By default, inputs are sampled every 10 ms and must remain stable for 30 ms before acceptance; adjust `gpio_sample_seconds` and `gpio_debounce_seconds` to tune this. Each stable change applies the four-input selection rule. Releasing all inputs holds the last selection. Both GPIO and serial/stdin can operate together: the last accepted update wins. GPIO updates on a stable pin change and does not continually override serial commands. See [GPIO Zero input documentation](https://gpiozero.readthedocs.io/en/stable/api_input.html).

#### Blinker trigger mode

For simultaneous reverse ranging/OLED operation, follow the
[combined-trigger guide](docs/combined-triggers.md). Its software-only checker
detects overlapping GPIO and inspectable USB/video device assignments. BOTH
inhibits camera capture without changing the reverse session.

All selector installation settings are in [`rpi-ahd-selector/config.json`](rpi-ahd-selector/config.json). Trigger mode is disabled in the supplied file to avoid claiming unassigned GPIO pins. Enable it by setting `trigger_enabled` to `true`, keep `gpio_pins` empty, and set the two trigger pins and camera mappings. The four-source configuration remains intact; mappings identify which two entries represent the vehicle's left and right cameras.

The following settings are a partial configuration example; retain the existing `sources`, `sink`, and other settings in the complete file:

```json
{
  "trigger_enabled": true,
  "gpio_pins": [],
  "trigger_left_pin": 17,
  "trigger_right_pin": 27,
  "trigger_left_camera": 1,
  "trigger_right_camera": 2,
  "trigger_active_low": false,
  "trigger_sample_seconds": 0.01,
  "trigger_debounce_seconds": 0.03,
  "trigger_settle_seconds": 0.05,
  "trigger_off_hold_seconds": 1.0,
  "player_poll_seconds": 0.05,
  "process_stop_timeout_seconds": 2.0
}
```

Pins use BCM numbering, not physical header positions. GPIO17 and GPIO27 correspond to physical pins 11 and 13. These are editable examples, shared with the separate GPIO draft; do not run both listeners on the same pins. Camera mappings must be distinct integers 1–4. Replace capture device placeholders with verified stable device paths. For the GRACETOP adapter, verify MJPEG 720p60 before using the `image/jpeg,width=1280,height=720,framerate=60/1 ! jpegdec` source shown in [capture configuration](#configure-the-capture-devices). MJPEG is the local capture format; this mode adds no network streaming.

Vehicle blinker voltage must pass through a suitable protected input interface before reaching the Pi. The software reads normalized logical activity, not vehicle voltage. With `trigger_active_low: false`, both inputs use pull-downs and 3.3 V HIGH means active. With `true`, both use pull-ups and LOW means active, suitable for an inverting open-collector interface. See the [blinker wiring requirements](docs/project-wiring.md#optional-blinker-trigger-inputs).

| Accepted input pair | State | Camera/display behavior |
| --- | --- | --- |
| Left active, right inactive | `LEFT` | Run only `trigger_left_camera`. |
| Left inactive, right active | `RIGHT` | Run only `trigger_right_camera`. |
| Both active | `BOTH` | Stop any camera capture; display generated black frames. |
| Both inactive briefly | Previous state | Retain LEFT, RIGHT, or BOTH across the OFF gap. |
| Both inactive until timeout | `IDLE` | Stop camera capture; display generated black frames. |
| GPIO monitoring exception | `FAULT` | Stop camera capture; request black output; require restart. |

The input pair must remain unchanged for `trigger_debounce_seconds`. Single-side activation additionally requires `trigger_settle_seconds`; BOTH requires only debounce. At the supplied values, a single-side candidate needs 80 ms and BOTH needs 30 ms, plus sampling/scheduling delay. This settling interval suppresses single-side camera flashes when hazard edges arrive slightly apart. Skew longer than the configured window can still produce a temporary single-side selection. Inputs are not independently stretched, so a quick left-to-right change does not create an artificial BOTH state.

An accepted all-inactive interval starts its hold timer at the first sample of that interval. The previous state remains until `trigger_off_hold_seconds` expires; the initial OFF pair must complete debounce. Once armed, the deadline is checked on every sample, including while another pair is still being debounced or settled. Rejected glitches cannot reset or postpone that deadline. Only an accepted nonzero pair cancels it. If a returning HIGH has not qualified by expiry, the state becomes IDLE until that pair qualifies. A delayed sample after expiry follows the same rule. Continuous qualified HIGH remains active indefinitely. With a zero hold value, deactivation still requires initial OFF debounce.

Tune the hold above the measured longest normal blink OFF gap **plus the next pulse's debounce/settling time and a sampling/scheduling margin**; the one-second default is provisional. For example, a 0.99-second OFF gap with the default 80 ms single-side qualification can briefly reach IDLE with a one-second hold. After turn cancellation, the view remains until the hold expires. BOTH is retained across hazard OFF gaps, but a subsequently stable single-side pair can select that side after debounce and settling. Polling can only classify observed levels; pulses occurring entirely between samples are not observable.

Trigger mode starts in IDLE regardless of `initial_camera`. `camera` and `inputs` commands return `ok: false` while enabled, including in IDLE and BOTH; `status` remains available. `State.trigger()` is the centralized transition point for future BOTH entry behavior; no additional function is invoked for BOTH currently. A stop request cannot be lost when a later trigger arrives before the playback worker polls, including BOTH followed by the same camera selection. Capture teardown completes before another source is opened, and the target is checked again after teardown.

The player reserves a launch under the state lock, performs process creation outside that lock, and validates the target and stop counter again before publishing playback status. GPIO transitions and status reads therefore remain available during a slow process launch. BOTH accepted before reservation prevents camera creation. A launch already reserved cannot be cancelled inside the operating system: if BOTH, another selection, a stop-counter change, or shutdown invalidates it, the resulting process is terminated as soon as creation returns, before a playback polling wait. It may briefly open a device before termination; this is not a hardware interlock or a real-time cutoff guarantee. Rejected launches are not reported as established playback. Trigger/fault state is published before diagnostic logging, without holding the state lock during log output.

The black pipeline uses `videotestsrc pattern=black` and the configured output settings/sink. It opens no camera device. Display clearing requires a functioning GStreamer/display path; if that pipeline fails, it retries and reports `last_error`, and the display may retain an old frame. A detected GPIO read failure is latched in `trigger_error`; it does not automatically reconnect. A disconnected wire that simply reads inactive is handled as an OFF interval, not a detectable GPIO exception.

For installation-specific tuning, an optional ignored copy can be used:

```sh
cp config.json config.local.json
python3 selector.py --config config.local.json --check-config
python3 selector.py --config config.local.json
```

Edit the copy before validation and startup. On Windows, `Copy-Item config.json config.local.json` performs the copy. The tracked `config.json` and this reference retain the auditable defaults; the running file is loaded once at startup. No electrical compatibility or timing guarantee follows from configuration validation.

#### USB serial selection

Set `serial_port` to the Pi serial device, preferably `/dev/serial/by-id/...`. Set `serial_baud` to the controller rate, default 115200, 8N1. Serial is initially disabled (`null`) until the port is known. This is a physical serial connection. Do not connect two USB host ports with a passive USB cable; use suitable serial adapters or a controller presenting a USB serial device to the Pi.

The controller sends the JSON commands above and receives a JSON line reply. From a controller computer with Python and pyserial, use its own port name:

```sh
python3 control.py --serial COM3 --inputs 0 1 0 0
python3 control.py --serial COM3 --camera 4
python3 control.py --serial COM3 --status
```

Disconnected serial devices retry every two seconds by default (`retry_delay_seconds`) without stopping video. Some controllers reset when their port opens; use a persistent serial session and wait for readiness on those devices.

Successful replies contain `ok: true`, `selected_camera`, `pipeline_camera`, `last_error`, `display_mode`, `trigger_state`, `trigger_error`, and `stop_generation`. Invalid-command replies contain `ok: false` and `error`. `selected_camera` is `null` when trigger mode prohibits capture; `pipeline_camera` can still name the previous camera while teardown is pending. `display_mode` reports `camera`, `blank`, or `stopped` for the playback worker's process state. `trigger_state` is `null` in manual mode. `stop_generation` counts trigger transitions requiring capture inhibition. `ok` confirms command acceptance, not delivery of a live frame. Neither `pipeline_camera` nor `display_mode` proves physical video or successful screen clearing.

#### Local program control

A parent program can send JSON lines through the selector's standard input. A one-command example is:

```sh
python3 control.py --inputs 0 1 0 0 | python3 selector.py
```

The selector keeps running after input EOF. For ongoing commands, keep the input pipe open. Interactive commands can also be typed in the launching console, although fullscreen video may hide the console text. Replies go to standard output; diagnostic text goes to standard error.

### Recovery and testing

By default, a five-second frame watchdog stops a stalled pipeline, and failures retry after two seconds. Adjust `watchdog_timeout_ms` and `retry_delay_seconds` for those timings. The watchdog detects missing buffers, not repeated/frozen image content. Driver startup and teardown can take longer. Controls remain active during recovery. A switch stops the old capture and starts the new one. During a fault/switch the screen may be blank or retain an old frame; there is no signal-loss overlay. A still image is not proof of a live feed.

Use `python3 selector.py --demo` for four test patterns without cameras. `--demo --headless` discards video for pipeline tests without HDMI. Run software tests with `python3 -m unittest discover -v` from the `rpi-ahd-selector/` directory.

Before deployment, verify all four real feeds, both GPIO and serial, simultaneous inputs, rapid switching, capture disconnection/reconnection, startup selection, actual 720p output, latency, CPU load and temperature. Raspberry Pi, AHD hardware, GStreamer rendering, GPIO, serial hardware and HDMI have not been tested in the development environment.

For trigger mode, first use a protected bench input to verify left/right mapping, polarity, startup with no capture, brief glitches, held HIGH, repeated blink OFF gaps, final OFF timeout, BOTH while either camera runs, hazard edge skew, and rapid direction changes. Confirm manual commands cannot override BOTH, camera retries stop on inhibition, and the display clears. Measure activation and stop latency on the installed hardware: debounce/settling, sampling, `player_poll_seconds`, process teardown, and capture/display startup all contribute. `process_stop_timeout_seconds` bounds each graceful and forced termination wait; final cleanup can retry, so it is not a guaranteed end-to-end stop bound. Then measure vehicle signal levels, PWM/diagnostic pulses, and blink timing before choosing final input protection and tuning values.

## Manual review and adjustment guide

### File map and reading order

| File | What to review or change |
| --- | --- |
| [`README.md`](README.md) | Setup, settings reference, behavior, and checks. This is the shared guide for the sensor sketch, camera selector, and draft GPIO connection. |
| [`optic_coyote_ultrasonic.ino`](optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino) | Arduino program. Start at `Config`, then read `setup()`, `loop()`, `serviceSensorPolling()`, and `serviceSerialOutput()`. |
| [`config.json`](rpi-ahd-selector/config.json) | Camera sources, display output, GPIO, serial, and timing settings. Edit this first for camera installation changes. |
| [`reverse.json`](rpi-oled-bridge/reverse.json) | Reverse GPIO, 100 ms HIGH qualification, USB limits, leases, and sample freshness. |
| [`reverse_control.py`](rpi-oled-bridge/reverse_control.py) | ReverseGate qualification, SensorSession freshness, independent DisplayLink reconnects, guarded USB writes, and release handling. |
| [`diagnose_reverse.py`](rpi-oled-bridge/diagnose_reverse.py) | Software checks and optional GPIO/USB bench cycle with Markdown/JSON reports. |
| [`reverse-diagnostic.json`](rpi-oled-bridge/reverse-diagnostic.json) | Diagnostic deadlines, LOW response limit, quiet window, maximum observation gap, and minimum reply counts. |
| [`check_trigger_setup.py`](tools/check_trigger_setup.py) | Software-only cross-check of reverse/blinker GPIO and device assignments in a complete checkout. |
| [`buzzer.py`](rpi-buzzer/buzzer.py), [`buzzer.json`](rpi-buzzer/buzzer.json) | Optional active/passive buzzer API, finite patterns, cancellation, strict settings, and CLI; DIYables passive active-low defaults at 3.3 V DC, disabled with pin unassigned. |
| [`test_diagnose_reverse.py`](rpi-oled-bridge/test_diagnose_reverse.py) | Simulated diagnostic lifecycle, evidence classification, timeout cleanup, and false-PASS regressions. |
| [`reverse-trigger.md`](docs/reverse-trigger.md) | Both Nano configuration headers, reverse protocol, idle rendering, setup, and verification. |
| [`selector.py`](rpi-ahd-selector/selector.py) | Camera program. Start with the module overview, `main()`, and `validate()`, then follow `player()` or the relevant input function. |
| [`control.py`](rpi-ahd-selector/control.py) | Sender helper. Read `build_parser()`, `make_message()`, `send_serial_command()`, then `main()`. |
| [`test_selector.py`](rpi-ahd-selector/test_selector.py) | Examples and automated checks for commands, configuration, switching, GPIO, and reconnects. Fake processes/ports replace hardware. |
| [`test_trigger.py`](rpi-ahd-selector/test_trigger.py) | Trigger timing, mappings, inhibition, black output, GPIO faults, and playback transition tests using synthetic time and devices. |
| [`test_control.py`](rpi-ahd-selector/test_control.py) | Sender options, output JSON, acknowledgement validation, and error handling using a fake serial port. |
| [`diagnostic.json`](rpi-ahd-selector/diagnostic.json) | Adapter diagnostic device, target mode, buffer counts, rate tolerance, and time limits. Independent of selector settings. |
| [`diagnose_adapter.py`](rpi-ahd-selector/diagnose_adapter.py) | Read `diagnose()`, `hardware_worker()`, `BufferMeasurements`, `evaluate()`, and `render_report()` for inventory, physical measurements, classification, and report formatting. |
| [`test_diagnose_adapter.py`](rpi-ahd-selector/test_diagnose_adapter.py) | Host-only diagnostic parsing, measurement, failure classification, worker lifecycle, and report tests. |

The sensor-only sketch and camera selector are independent. Arduino CSV distance reports are **not** camera-selection JSON commands. The separate [draft GPIO connection](#draft-arduino-to-pi-gpio-connection) supplies an alternative Arduino sketch and a Pi listener; its optional JSON output uses the camera program's existing input interface.

### Camera settings reference

Edit `config.json` with a text editor. JSON requires double quotes, lowercase `true`/`false`/`null`, and no comments or trailing commas. Keep numbers as numbers, not quoted strings. The following tables provide the comments that cannot go inside JSON.

The program reads the file once at startup. Save it, run `--check-config`, then restart the selector to apply changes. `--config PATH` selects a different file; otherwise the file beside `selector.py` is used, regardless of the current working directory. `initial_camera` and `sources` are required; omitted optional settings use `DEFAULTS` near the top of `selector.py`. Unknown setting names are rejected so spelling mistakes cannot silently fall back to defaults.

| Setting | Supplied value | Meaning and accepted values |
| --- | --- | --- |
| `initial_camera` | `1` | Integer camera number, 1–4; ignored at startup in trigger mode. |
| `sources` | Four V4L2 pipeline strings | Exactly four nonempty strings, ordered camera 1, 2, 3, 4. Device placeholders are `/dev/video0`, `/dev/video2`, `/dev/video4`, `/dev/video6`. |
| `sink` | `kmssink driver-name=vc4 force-modesetting=true sync=false` | Nonempty output pipeline fragment; normally the local HDMI display. |
| `output_width` | `1280` | Output width in pixels, integer 1–8192. |
| `output_height` | `720` | Output height in pixels, integer 1–8192. |
| `output_fps` | `60` | Pipeline frames per second, integer 1–240. Does not set the capture device's own frame rate. |
| `watchdog_timeout_ms` | `5000` | Integer milliseconds allowed without downstream video buffers, 1–600000. Expiry terminates the pipeline. |
| `retry_delay_seconds` | `2` | Seconds before a failed video pipeline or disconnected serial port retries, 0.05–300. A camera change bypasses the old camera's retry delay. |
| `player_poll_seconds` | `0.05` | Playback worker polling interval in seconds, 0.001–1. Applies in both modes. |
| `process_stop_timeout_seconds` | `2.0` | Timeout for each graceful and forced process termination wait, 0.05–10 seconds. Failed teardown stops the selector without launching another capture. Applies in both modes. |
| `gpio_pins` | `[]` | Disabled, or exactly four distinct BCM pin numbers 0–27 in camera order. Check board pin availability separately. |
| `gpio_active_low` | `true` | `true`: pull-up, ground activates. `false`: pull-down, high activates. |
| `gpio_sample_seconds` | `0.01` | Seconds between GPIO samples, 0.001–1. |
| `gpio_debounce_seconds` | `0.03` | Seconds an unchanged input must remain stable, 0–5. Even zero requires another sample to accept the candidate. |
| `serial_port` | `null` | Disabled, or a nonempty local serial device path such as `/dev/serial/by-id/...`. |
| `serial_baud` | `115200` | Integer bits per second, 1–4000000; must match the sender and be supported by the device. |
| `serial_read_timeout_seconds` | `0.1` | Receiver read timeout in seconds, 0.001–10. Partial commands are retained until their newline arrives. |
| `serial_write_timeout_seconds` | `0.5` | Receiver reply write timeout in seconds, 0.001–10. |

Trigger settings are validated even when the mode is disabled, so dormant installation errors are reported before enabling it:

| Setting | Supplied value | Meaning and accepted values |
| --- | --- | --- |
| `trigger_enabled` | `false` | Enable exclusive two-input blinker control. Requires `gpio_pins: []`. |
| `trigger_left_pin` / `trigger_right_pin` | `17` / `27` | Two distinct integer BCM pin numbers, each 0–27; verify physical availability. |
| `trigger_left_camera` / `trigger_right_camera` | `1` / `2` | Distinct integer source numbers, each 1–4. |
| `trigger_active_low` | `false` | `false`: pull-down/HIGH active. `true`: pull-up/LOW active. Applies to both conditioned inputs. |
| `trigger_sample_seconds` | `0.01` | Trigger polling interval, 0.001–1 seconds. Separate from manual GPIO sampling. |
| `trigger_debounce_seconds` | `0.03` | Required unchanged pair duration, 0–5 seconds. Zero permits acceptance on the first sample. |
| `trigger_settle_seconds` | `0.05` | Additional stable duration before LEFT/RIGHT acceptance, 0–5 seconds. Does not delay BOTH. |
| `trigger_off_hold_seconds` | `1.0` | Both-inactive hold duration, 0–30 seconds. Initial OFF debounce arms the timer; pending/rejected input changes cannot postpone expiry. |

These limits catch editing mistakes; they are not promises that a camera, display, serial device, or Pi supports every accepted value. Timing fields accept finite numbers within their ranges. Integer fields reject decimals and booleans. Smaller watchdog/retry values can cause repeated restarts on slow hardware; longer serial timeouts can delay shutdown.

#### Changing a camera source

The first `sources` entry is camera 1, even if its Linux device is named `/dev/video6`. GPIO order and JSON camera numbers follow this list order. Use stable device paths and supported capture formats as described in [Configure the capture devices](#configure-the-capture-devices).

Each source fragment must supply decoded/raw video to the rest of the pipeline. For example, an MJPEG source needs `jpegdec` after its JPEG capture format. `command()` appends this sequence automatically:

```text
selected source -> two-buffer queue -> convert -> scale with borders
                -> adjust frame rate -> output format -> watchdog -> sink
```

Do not append a display sink to a source entry: `sink` is separate. Change capture resolution/rate inside the source fragment; change display video resolution/rate using `output_width`, `output_height`, and `output_fps`. Check the Pi display mode too when changing the requested output size. `--demo` substitutes test-pattern sources; `--headless` substitutes a sink that discards frames. Configured control inputs remain enabled in both modes.

Source/sink quoting is checked, but GStreamer element availability, format negotiation, camera identity, and HDMI operation require a real run. The pipeline runs without a shell, but its GStreamer elements still perform their configured actions. Use local capture and display elements to retain this project's local-only, live-only behavior.

### Arduino settings reference

Edit only the `Config` section for ordinary installation tuning, then compile and upload again. The running board does not read `config.json`. Array positions link the physical mux channel, zone label, reported distance column, and nearest-zone name.

| Setting | Default | Meaning and editing constraints |
| --- | --- | --- |
| `kPollingIntervalMs` | `400` | Nano USB sketch: minimum milliseconds between round starts, positive and below 2147483648. Four sequential I2C conversions need about 400 ms plus overhead. |
| `kMuxAddress` | `0x70` | 7-bit mux address; match the physical address straps. |
| `kSensorAddress` | `0x57` | RCWL-1655's fixed 7-bit address; changing a number does not readdress the sensors. |
| `kI2cClockHz` | `100000` | Positive I2C bus rate in Hz; choose a rate supported by the board, sensors, and wiring. |
| `kSensorCount` | `4` | Fixed program layout, checked at compile time. Supporting another count requires code changes. |
| `kMuxChannels` | `{0, 1, 2, 3}` | Exactly four distinct physical mux channels, each 0–7. |
| `kZoneLabels` | `front_left`, `front_right`, `rear_left`, `rear_right` | Exactly four labels. Keep them nonempty and free of commas/newlines and at most 23 characters; CSV escaping is not implemented. The header gains `_mm` automatically. |
| `kMeasurementTimeMs` | `100` | Wait between trigger and read in milliseconds. Nano firmware enforces at least 100 ms for the RCWL-1655 I2C protocol. |
| `kSensorCooldownMs` | `10` | Minimum delay before retriggering the same sensor, 10-255 ms. Does not delay USB or other sensors. The separate GPIO draft retains its own guard setting. |
| `kMinimumDistanceMm` / `kMaximumDistanceMm` | `200` / `5000` | Inclusive accepted range in millimetres, 16-bit unsigned values. Minimum must not exceed maximum. Outside readings become invalid. |
| `kWarningDistanceMm` / `kCriticalDistanceMm` | `600` / `300` | Inclusive thresholds in millimetres, 16-bit unsigned values. Critical must not exceed warning. For both states to be reachable, use `minimum <= critical < warning <= maximum`; equal thresholds skip `WARNING`. |
| `kAlarmPin` | `8` | Board digital pin; `255` disables it. Must differ from an enabled heartbeat pin. |
| `kAlarmActiveHigh` | `true` | `true` activates the alarm with HIGH; `false` with LOW. |
| `kHeartbeatPin` | `LED_BUILTIN` | Board status LED pin; `255` disables heartbeat output. |
| `kHeartbeatToggleMs` | `500` | Milliseconds between LED toggles, greater than 0 and below 2147483648. Two toggles make one full cycle. |
| `kSerialBaud` | `115200` | Positive serial bits per second; match the Serial Monitor/receiver and board capabilities. |

Compile-time assertions catch array lengths, duplicate/out-of-range channels, inverted thresholds/ranges, invalid timing/rates, and output pin collisions. They do not validate physical wiring, supported pins/rates, or label text. Keep edits within the declared C++ integer types.

`Design` contains protocol and algorithm constants, not ordinary tuning values: the one-shot command, three-byte response, micrometre conversion, three-sample history, and disabled-pin marker. In particular, changing `kHistorySize` alone does not implement a different filter. The filter uses the first sample directly, averages the first two, and then uses the median of the latest three successful readings.

### Function map: Arduino

Comments above each function describe its inputs, outputs, and hardware/state changes. Sensor indexes inside the sketch are zero-based, 0–3.

| Function | Use/action |
| --- | --- |
| `setup()` | Configure outputs, serial, I2C and its timeout; disable mux channels; reverse acquisition starts idle. |
| `loop()` | Enforce lease expiry, service commands, polling, alarm, output and heartbeat. Application work must return promptly. |
| `serviceSerialCommands()` | Parse bounded reverse R/K/X commands or standalone START/STOP lines; discard invalid lines. |
| `handleReverseCommand()` | Validate session/request identifiers and renew only an unexpired matching lease. |
| `startReverseAcquisition()` / `stopReverseAcquisition()` | Reset session samples and control actual ranging; stopping silences the alarm and retains the physical cooldown guard. |
| `acquisitionPermitted()` / `retainRestartGuard()` | Check the lease between bus operations and preserve conversion/cooldown deadlines across cancellation. |
| `prepareReversePacket()` | Freeze request/session identifiers, elapsed time, distances and individual ages. |
| `prepareSerialPacket()` | Freeze a standalone header/data snapshot; consume only readings represented in that snapshot. |
| `deadlineReached(now, deadline)` | Compare millisecond deadlines with counter wraparound handling. |
| `selectMuxChannel(channel)` | Connect one sensor's mux channel; return whether the I2C write succeeded. |
| `disableAllMuxChannels()` | Request disconnection of all channels. The write result is not checked. |
| `startRanging(sensorIndex)` | Select the sensor's configured channel and send the measurement command; return success/failure. |
| `readDistanceMm(distanceMm)` | Decode the selected sensor's three-byte result; return success and update the output argument only for an in-range reading. |
| `medianOfHistory(sensor)` | Calculate the filtered distance without changing state. |
| `recordSuccessfulReading(sensorIndex, distanceMm)` | Update history/filter, clear the error count, and mark the reading valid; reverse mode clears expired history on recovery. |
| `recordFailedReading(sensorIndex)` | Mark the reading invalid and increase its diagnostic error count, retaining earlier filter samples. |
| `findNearestSensor()` | Return the nearest valid sensor index, or `-1`; reverse mode excludes stale samples. Equal distances prefer the earlier configured zone. |
| `setAlarm(active)` | Apply configured alarm polarity, or do nothing when disabled. |
| `cachedDistance(index)` | Return the latest successful raw millimetres, or -1 if unavailable. |
| `serviceSerialOutput()` | Queue available bytes without waiting; produce periodic reverse snapshots or pending standalone values. |
| `distancesChangedSinceSend()` | Compare all four cached distances with the last fully queued data snapshot. |
| `updateAlarm()` | Update the alarm after each sensor attempt, independent of TX progress. |
| `finishCurrentSensor()` | Disable mux, start that sensor's cooldown, update the alarm, and advance to another sensor. |
| `serviceSensorPolling(now)` | Trigger eligible sensors and wait/read without delay(); skip sensors still cooling down. |
| `serviceHeartbeat(now)` | Toggle the enabled status output when its deadline arrives. This indicates loop activity, not sensor health. |

### Function map: camera selector and sender

`selector.py` keeps selection, trigger state, pipeline identity, and errors in `State`. Its lock protects those shared values. The main thread reads standard input; workers handle playback, GPIO, and serial. Only the playback worker starts/stops video. In manual mode, the latest accepted selection wins. Trigger mode owns selection exclusively and retains stop transitions even when intermediate selections coalesce.

| Function/class in `selector.py` | Use/action |
| --- | --- |
| `camera_number(value)` | Validate and return a camera number; raise `ValueError` for invalid input. |
| `resolve_inputs(values, current)` | Return the lowest active camera or hold `current` when all four inputs are zero. |
| `validate(config)` | Validate keys/types/ranges/quoting and return effective settings with defaults. No hardware is opened. |
| `command(config, camera, demo, headless)` | Build a camera pipeline, or generated black output when camera is `None`. No process launch. |
| `BlinkerTrigger.update(left, right, now)` | Debounce a normalized pair, settle single-side changes, and retain the last state through short OFF gaps using monotonic time. |
| `State.select()` / `State.inputs()` | Apply a direct selection or four-input snapshot under the lock. |
| `State.trigger()` | Apply trigger transitions/mappings, retain stop requests, and latch GPIO faults. Future BOTH entry behavior belongs here. |
| `State.snapshot()` / `State.playback()` | Read status or update playback identity/error under the lock. Status does not prove a live frame. |
| `stop_process(process, timeout)` | Terminate capture or black output, then force termination if needed; both waits are bounded and failure prevents replacement capture. |
| `player(...)` | Switch/retry camera or black output; recheck after teardown and process creation; cancel stale launches and clean up on shutdown. |
| `apply_message(state, line)` | Parse exactly one JSON action; return an acknowledgement or error object. |
| `Lines.feed(data)` | Assemble partial byte chunks into complete lines. Discard an entire command exceeding 1024 bytes. |
| `responses(state, lines, data)` | Convert complete input lines to newline-terminated JSON reply bytes. |
| `serial_control(...)` | Request cooperative exclusive serial access, read commands, reject short reply writes, and reconnect after port failures. |
| `poll_gpio(...)` | Sample/debounce all four inputs and apply only stable changes. |
| `poll_triggers(...)` | Sample the normalized left/right pair, publish trigger state, and latch a blank FAULT on read exceptions. |
| `main(argv=None)` | Load/check settings, start workers, read stdin, and stop/close resources on exit. |

Near the top of `selector.py`, `DEFAULTS` supplies omitted optional settings and `NUMERIC_LIMITS` documents their accepted ranges. Named constants below them cover fixed protocol limits and stdin polling. Trigger timing, playback polling, and process termination tuning are all available in JSON. Change configuration first; changing fixed internals requires reviewing shutdown behavior and tests.

| Function in `control.py` | Use/action |
| --- | --- |
| `positive_integer()` / `positive_seconds()` | Reject invalid command-line baud/timeout values before opening a port. |
| `build_parser()` | Define command options and help text; require one action. |
| `make_message(args)` | Return the JSON line for camera, inputs, or status without doing I/O. |
| `send_serial_command(...)` | Request cooperative exclusive access, write one complete command, read/validate one reply, close the port, and return the reply object. |
| `main()` | Print the command or send it; report failures with a nonzero exit status. |

Sender options are `--camera 1..4`, `--inputs` followed by four 0/1 values, or `--status` (choose one). Optional `--serial PORT` sends to a device; omission prints JSON only. `--baud` defaults to 115200 and `--timeout` defaults to 3 seconds for each read/write. These are sender settings; they do not change the receiver's configuration. For example:

```sh
python3 control.py --serial COM3 --baud 115200 --timeout 5 --camera 2
```

### Check an edit before deployment

From `rpi-ahd-selector/`, run these checks (`python` can replace `python3` on Windows):

```sh
python3 selector.py --check-config
python3 selector.py --config config.json --check-config
python3 control.py --help
python3 -m unittest discover -v
```

`--check-config` prints the effective configuration, four camera pipeline argument lists, and `inactive_pipeline` for black output, then exits. It works without GStreamer, GPIO libraries, serial libraries, or attached devices. It catches setting and quote errors, but does not start GStreamer to check plugin syntax or formats. Demo/headless switches affect the reported pipelines; the original configured source/sink quoting is still checked.

The automated tests use fake capture processes, clocks, GPIO buttons, and serial ports. They verify software behavior and supplied examples, not electrical wiring or real video. If deliberately changing camera mapping/default output, review the tests that assert those defaults too. For Arduino edits, use the IDE's **Verify** action with the actual target board selected, then upload and repeat the first-power-up checks. No Arduino board build or hardware validation is claimed by the Python test suite.

For live Pi checks, start with `--demo --headless`, then `--demo` with HDMI, then the real cameras and configured controls. These modes still need GStreamer and any libraries/devices required by enabled controls. Watch actual frames and inputs: an `ok: true` command reply, running process, or heartbeat LED alone does not establish system health.

### Verify all components from the project root

The Python checks use the standard library and do not require attached devices or the Pi runtime packages:

```sh
python3 -m unittest discover -s rpi-ahd-selector -p "test_*.py" -v
python3 -m unittest discover -s draft-gpio-link -p "test_*.py" -v
python3 -m unittest discover -s rpi-oled-bridge -p "test_*.py" -v
python3 -m unittest discover -s rpi-buzzer -p "test_*.py" -v
python3 -m unittest discover -s tests/integration -p "test_*.py" -v
python3 rpi-buzzer/buzzer.py --check-config
python3 rpi-ahd-selector/selector.py --check-config
python3 rpi-ahd-selector/selector.py --demo --headless --check-config
python3 rpi-ahd-selector/control.py --camera 2
python3 draft-gpio-link/warning_receiver.py --simulate 0 1 2 3 4 0 -1
python3 draft-gpio-link/warning_receiver.py --selector-json --simulate 0 1 2 3 4 0
```

Run all five explicit discovery commands: the tests live in separate component directories. The selector and sender suite covers command validation/framing, configuration defaults and limits, pipeline construction, switching/retry cleanup, GPIO arbitration, serial reconnects, and sender acknowledgements. The receiver suite covers the draft link separately. The OLED bridge suite covers distance parsing/order, stale input, framing, USB cleanup, reverse qualification, request freshness, and LOW cancellation. The buzzer suite covers active/passive configuration, playback, cancellation, fault reporting, and cleanup. The integration suite covers concurrent trigger states, GPIO/device assignment conflicts, unrelated device failures, serial ownership failures, and bounded camera teardown. Python tests do not compile the Arduino sketches. The [reverse guide](docs/reverse-trigger.md#verification) supplies both reverse firmware host checks.

Build each sketch separately in Arduino IDE with the target board selected. With Arduino CLI and the matching board core already installed, a classic Nano build from the project root is:

```sh
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 optic_coyote_ultrasonic
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 optic_coyote_display
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 draft-gpio-link/arduino_camera_warning
```

Install the OLED libraries listed in the [display guide](docs/oled-display.md) before compiling its sketch. Use your board's FQBN when it differs. These commands compile without uploading. Firmware compilation and software tests do not establish physical sensor accuracy, electrical compatibility, GPIO/serial operation, camera capture, HDMI/OLED output, or end-to-end response time. Those require the hardware checks above. The display guide also includes the C++ host check for its actual sketch.

The Nano stream contract also has a host simulation that includes the actual sketch and substitutes the clock, serial port, and I2C devices. With a C++ compiler installed, run from the project root (Windows MinGW example):

```powershell
g++ -std=c++11 -Wall -Wextra -Werror -static -I tests/nano tests/nano/test_serial.cpp -o "$env:TEMP/optic-coyote-nano-test.exe"
if ($LASTEXITCODE -eq 0) { & "$env:TEMP/optic-coyote-nano-test.exe" }
```

It checks silent boot, complete command framing, start/stop/restart, per-reading cached packets, each sensor responding alone, trigger/read/partial/out-of-range failures, recovery, minimum conversion waits, per-sensor cooldown, clock rollover, stalled/partial serial writes, changed-value follow-up, sends during cooldown, and STOP/START mid-packet. This simulation does not exercise the Nano hardware, its bootloader, USB buffering, or acoustic interference.
