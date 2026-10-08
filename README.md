# Project Optic Coyote

## Base ultrasonic connectivity architecture

```text
Raspberry Pi (SBC / USB host, USB-A)
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

The Raspberry Pi communicates with the Nano through USB serial. The Nano owns the I2C connection to the four ultrasonic modules. This diagram establishes component roles and communication links; it does not specify the sensor power distribution or constitute a verified electrical schematic.

### Existing implementation and details still to resolve

- **I2C fan-out:** the user confirmed retaining the existing TCA9548A wiring for the Nano firmware: mux address `0x70`, with one RCWL-1655 at `0x57` on each of channels 0-3. Devices with the same fixed address remain isolated on separate channels.
- **Pi OLED integration:** the [USB OLED bridge](rpi-oled-bridge/bridge.py) starts the sensor stream, receives its CSV at 115200 baud, and forwards the four distances to a second ELEGOO Nano running the [SSD1306 display sketch](optic_coyote_display/optic_coyote_display.ino). The camera selector's USB input still expects JSON camera commands; this display bridge does not select cameras.
- **Earlier GPIO draft:** `draft-gpio-link/` documents a separate Arduino-to-Pi GPIO prototype. It is retained for reference and is outside this base USB connectivity path.

The Nano firmware sends a cached four-zone USB packet after every successful sensor reading while streaming. It retains the I2C conversion wait and enforces at least 10 ms after each read before retriggering that same sensor. The OLED USB path is implemented; physical hardware validation remains required.

## Rear-bumper OLED display

The [OLED setup guide](docs/oled-display.md) covers the second Nano's wiring,
firmware upload, Pi dependencies, USB port selection, and verification commands.
Both Nanos connect to separate Pi USB-A ports using USB-A-to-USB-C data cables.
The new display Nano drives a 0.91-inch **SSD1306 128x32 I2C OLED** on A4/SDA and
A5/SCL. Its four fixed columns show sensors **1, 2, 3, 4 from left to right**, in
feet with one decimal place, for example `1.0 2.0 3.0 4.0`.

The default order follows sensor CSV positions 1-4 (mux channels 0-3). The existing
front/rear CSV labels are retained for compatibility; this installation places
all four sensors on the rear bumper. `--sensor-order` adjusts the physical cable
mapping. Missing values or a stopped stream show `--.-`. The original CSV has no
per-sensor ages, so a failed individual sensor can retain its cached value while
other sensors continue reporting. See the guide's failure behavior before use.

## Existing components

This repository contains ultrasonic sensing, a Pi-to-Nano OLED display path,
camera selection, and a separate draft GPIO camera connection. The display bridge
consumes the sensor program's CSV. The camera program remains independent; the
draft provides an alternative Arduino sketch and Pi camera-warning listener.

| Component | Purpose | Files |
| --- | --- | --- |
| Ultrasonic sensing | Poll four RCWL-1655 or compatible AJ-SR04M I2C sensors through an I2C multiplexer and report distances over serial. | [`optic_coyote_ultrasonic/`](optic_coyote_ultrasonic/) |
| OLED display | Receive four distances on a second Nano and display decimal feet in sensor order. | [`optic_coyote_display/`](optic_coyote_display/) |
| Pi USB distance bridge | Read sensor CSV and forward the latest ordered snapshot to the display Nano. | [`rpi-oled-bridge/`](rpi-oled-bridge/) |
| AHD camera selection | Show one of four AHD cameras on a Raspberry Pi HDMI display, selected through GPIO, USB serial, or standard input. | [`rpi-ahd-selector/`](rpi-ahd-selector/) |
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

The receiver sends commands such as `{"camera": 2}` only for valid warnings. Clear or conflicting inputs send no camera command; the existing selector keeps displaying its last selected camera. The pipe uses the selector's standard-input interface. The supplied camera configuration already has `gpio_pins: []` and `serial_port: null`. Keep those settings for this test, and stop any other running selector instance first: only the draft listener should own these GPIO inputs. Capture device configuration and video dependencies still need to match your installation.

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

**AJ-SR04M interchangeability:** an AJ-SR04M variant supporting the same I2C protocol can replace an RCWL-1655 on any mux channel, including in a mixed set, without a firmware change. The required operations are 7-bit address `0x57`, write `0x01` to trigger a measurement, wait for conversion (the sketch defaults to `100 ms`), then read three bytes containing a big-endian distance in micrometres and divide by `1000` for millimetres. The same polling, per-sensor cooldown, filtering, START/STOP commands, and cached CSV reporting apply.

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

Open [`optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino`](optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino) in the Arduino IDE, choose **Arduino Nano**, **ATmega328P**, and the board's serial port, then upload it. If your Nano has the older bootloader, select **ATmega328P (Old Bootloader)**. The sketch only needs the standard `Wire` library. Nano I2C pins are **A4 = SDA** and **A5 = SCL**, connected to the mux upstream pins.

The defaults suit a classic Arduino Uno/Nano:

- Serial rate: `115200`
- Requested minimum full-round interval: `400 ms`, edited with `Config::kPollingIntervalMs`; USB packets are sent per successful reading
- Alarm output: digital pin `8`, active high
- Status heartbeat: built-in LED
- TCA9548A channels: `0`, `1`, `2`, `3`
- Warning threshold: `600 mm`
- Critical threshold: `300 mm`
- Accepted sensor range: `200-5000 mm`

All of these values are grouped in the `Config` namespace near the top of the sketch.

### Serial output

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

Scheduling uses no `delay()`. Serial writes are limited to `availableForWrite()` space, so a full UART buffer does not block polling; `Wire` calls remain synchronous and can block. A stuck shared I2C bus can still affect all sensors. Physical timing, acoustic interference, and recovery require bench testing; application logic added to `loop()` must return promptly.

### First-power-up checks

1. Power the system with the sensor heads aimed in different directions.
2. Confirm that the TCA9548A responds at `0x70`.
3. Confirm that `0x57` appears only after selecting one mux channel.
4. Open Serial Monitor at `115200` baud with a newline setting. Confirm silence after reset, send `START`, and verify a header and packets roughly every 100 ms plus overhead when all sensors return readings; check that one working sensor still reports when the others return no result. Send `STOP`, allow buffered bytes to drain, and confirm silence. Send `START` again to resume.
5. Move a broad, flat target through each zone and verify its reported direction.
6. Tune the range and warning constants for the installation.

Do not fire all four sensors simultaneously. Reflections from one transducer can be received by another and create false detections.

## AHD camera selection (Raspberry Pi)

The supplied configuration displays live video from one of four cameras fullscreen through the Pi HDMI output at 1280x720. It starts on a configured camera and supports continuous selection through standard input and **both GPIO and USB serial** once their pins/port are configured; GPIO and serial are initially disabled. It uses no recording, video files, Ethernet, Wi-Fi, HTTP, RTSP or cloud service. Keep source and sink edits local and live-only: the configured GStreamer strings are executable pipeline instructions, and validation does not enforce that restriction.

### Hardware

```text
AHD camera 1 --> AHD-to-USB UVC capture 1 --+
AHD camera 2 --> AHD-to-USB UVC capture 2 --+
AHD camera 3 --> AHD-to-USB UVC capture 3 --+--> powered USB hub --> Pi 4/5 --> HDMI display
AHD camera 4 --> AHD-to-USB UVC capture 4 --+

Controller --> four GPIO selection wires and/or physical USB serial --> Pi
```

The Pi cannot accept AHD coax directly. Each camera needs an **AHD-capable decoder/capture device** compatible with its resolution and frame rate. The program expects four independently accessible Linux V4L2 capture devices. A single four-channel unit is suitable if its Linux driver exposes four independent feeds, not just a combined quad-view image. No DVR/NVR or recording hardware is required.

This is an interface specification, not a validated shopping list. No specific AHD USB adapter has been verified on a Pi in this project. Obtain vendor confirmation of AHD input, Linux ARM64 UVC/V4L2 support, independent camera access and 720p capture before buying. Ordinary composite/CVBS USB adapters cannot be assumed to accept AHD. An alternative is four AHD-to-HDMI decoders followed by Linux-compatible UVC HDMI capture adapters, with additional hardware and connections.

Use a suitable Pi power supply, cooling and a powered USB hub. All four cameras remain connected, but only the selected capture is opened. This reduces USB bandwidth and decode load. Switching interrupts video while the next capture starts; seamless switching is not implemented.

### Install on the Pi

Target: Raspberry Pi OS Lite 64-bit on Pi 4 or Pi 5 and a monitor supporting 720p60 on the first HDMI port. Copy [`rpi-ahd-selector/`](rpi-ahd-selector/) to `~/rpi-ahd-selector` using an SD card or USB drive. Install these packages once, or pre-provision the OS image for a completely offline installation:

```sh
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

Initial pipelines negotiate format automatically. For predictable bandwidth and quality, select an explicitly supported format based on `--list-formats-ext`. For an adapter supporting MJPEG 720p30:

```text
v4l2src device=/dev/v4l/by-path/YOUR_DEVICE do-timestamp=true ! image/jpeg,width=1280,height=720,framerate=30/1 ! jpegdec
```

For raw YUYV capture (called YUY2 by GStreamer):

```text
v4l2src device=/dev/v4l/by-path/YOUR_DEVICE do-timestamp=true ! video/x-raw,format=YUY2,width=1280,height=720,framerate=30/1
```

Request only adapter-supported formats. Capture uses [GStreamer's V4L2 source](https://gstreamer.freedesktop.org/documentation/video4linux2/v4l2src.html). Non-16:9 video is scaled with borders. Frames pass through memory to the display; they are not saved.

### Run and select

```sh
cd ~/rpi-ahd-selector
python3 selector.py
```

Set `initial_camera` to 1–4 (default 1). Ctrl+C stops the program. Use `--config PATH` for another configuration.

Serial/stdin commands are newline-terminated JSON objects containing exactly one action:

```json
{"inputs":[0,1,0,0]}
{"camera":4}
{"status":true}
```

The four inputs correspond to cameras 1–4. One active input selects that camera. All zero holds the previous selection. Multiple active inputs select the lowest numbered camera. Commands are complete snapshots, latch until changed and need no continuous retransmission. Rapid commands coalesce to the latest selection. Invalid commands leave selection unchanged and return an error. `inputs` accepts four JSON booleans or integer 0/1 values; `camera` requires an integer 1-4 and `status` requires `true`. Blank lines are ignored. Commands may contain at most 1024 bytes before the newline; an oversized line is discarded in full and receives an error when its newline arrives. An incomplete final line is not executed at input EOF.

#### GPIO selection

Set `gpio_pins` to four distinct **BCM GPIO numbers** in camera order. GPIO is initially disabled because the wiring has not been specified. An example is `[17,27,22,23]` (physical header pins 11, 13, 15 and 16); confirm those pins are free before wiring.

With `gpio_active_low: true`, inputs use internal pull-ups and activate when connected to Pi ground through a switch, dry contact or compatible open-drain output. For active-high 3.3 V logic, set `gpio_active_low: false` to use pull-downs. Never connect 5 V, 12 V or RS-232 directly to GPIO. Confirm controller voltage and common-ground/isolation requirements first.

By default, inputs are sampled every 10 ms and must remain stable for 30 ms before acceptance; adjust `gpio_sample_seconds` and `gpio_debounce_seconds` to tune this. Each stable change applies the four-input selection rule. Releasing all inputs holds the last selection. Both GPIO and serial/stdin can operate together: the last accepted update wins. GPIO updates on a stable pin change and does not continually override serial commands. See [GPIO Zero input documentation](https://gpiozero.readthedocs.io/en/stable/api_input.html).

#### USB serial selection

Set `serial_port` to the Pi serial device, preferably `/dev/serial/by-id/...`. Set `serial_baud` to the controller rate, default 115200, 8N1. Serial is initially disabled (`null`) until the port is known. This is a physical serial connection. Do not connect two USB host ports with a passive USB cable; use suitable serial adapters or a controller presenting a USB serial device to the Pi.

The controller sends the JSON commands above and receives a JSON line reply. From a controller computer with Python and pyserial, use its own port name:

```sh
python3 control.py --serial COM3 --inputs 0 1 0 0
python3 control.py --serial COM3 --camera 4
python3 control.py --serial COM3 --status
```

Disconnected serial devices retry every two seconds by default (`retry_delay_seconds`) without stopping video. Some controllers reset when their port opens; use a persistent serial session and wait for readiness on those devices.

Successful replies contain `ok: true`, `selected_camera`, `pipeline_camera` and `last_error`. Invalid-command replies contain `ok: false` and `error`. `ok` confirms command acceptance, not delivery of a live frame. `pipeline_camera` identifies a started process, not verified camera health.

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

## Manual review and adjustment guide

### File map and reading order

| File | What to review or change |
| --- | --- |
| [`README.md`](README.md) | Setup, settings reference, behavior, and checks. This is the shared guide for the sensor sketch, camera selector, and draft GPIO connection. |
| [`optic_coyote_ultrasonic.ino`](optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino) | Arduino program. Start at `Config`, then read `setup()`, `loop()`, `serviceSensorPolling()`, and `serviceSerialOutput()`. |
| [`config.json`](rpi-ahd-selector/config.json) | Camera sources, display output, GPIO, serial, and timing settings. Edit this first for installation changes. |
| [`selector.py`](rpi-ahd-selector/selector.py) | Camera program. Start with the module overview, `main()`, and `validate()`, then follow `player()` or the relevant input function. |
| [`control.py`](rpi-ahd-selector/control.py) | Sender helper. Read `build_parser()`, `make_message()`, `send_serial_command()`, then `main()`. |
| [`test_selector.py`](rpi-ahd-selector/test_selector.py) | Examples and automated checks for commands, configuration, switching, GPIO, and reconnects. Fake processes/ports replace hardware. |
| [`test_control.py`](rpi-ahd-selector/test_control.py) | Sender options, output JSON, acknowledgement validation, and error handling using a fake serial port. |

The sensor-only sketch and camera selector are independent. Arduino CSV distance reports are **not** camera-selection JSON commands. The separate [draft GPIO connection](#draft-arduino-to-pi-gpio-connection) supplies an alternative Arduino sketch and a Pi listener; its optional JSON output uses the camera program's existing input interface.

### Camera settings reference

Edit `config.json` with a text editor. JSON requires double quotes, lowercase `true`/`false`/`null`, and no comments or trailing commas. Keep numbers as numbers, not quoted strings. The following tables provide the comments that cannot go inside JSON.

The program reads the file once at startup. Save it, run `--check-config`, then restart the selector to apply changes. `--config PATH` selects a different file; otherwise the file beside `selector.py` is used, regardless of the current working directory. `initial_camera` and `sources` are required; omitted optional settings use `DEFAULTS` near the top of `selector.py`. Unknown setting names are rejected so spelling mistakes cannot silently fall back to defaults.

| Setting | Supplied value | Meaning and accepted values |
| --- | --- | --- |
| `initial_camera` | `1` | Integer camera number, 1–4. |
| `sources` | Four V4L2 pipeline strings | Exactly four nonempty strings, ordered camera 1, 2, 3, 4. Device placeholders are `/dev/video0`, `/dev/video2`, `/dev/video4`, `/dev/video6`. |
| `sink` | `kmssink driver-name=vc4 force-modesetting=true sync=false` | Nonempty output pipeline fragment; normally the local HDMI display. |
| `output_width` | `1280` | Output width in pixels, integer 1–8192. |
| `output_height` | `720` | Output height in pixels, integer 1–8192. |
| `output_fps` | `60` | Pipeline frames per second, integer 1–240. Does not set the capture device's own frame rate. |
| `watchdog_timeout_ms` | `5000` | Integer milliseconds allowed without downstream video buffers, 1–600000. Expiry terminates the pipeline. |
| `retry_delay_seconds` | `2` | Seconds before a failed video pipeline or disconnected serial port retries, 0.05–300. A camera change bypasses the old camera's retry delay. |
| `gpio_pins` | `[]` | Disabled, or exactly four distinct BCM pin numbers 0–27 in camera order. Check board pin availability separately. |
| `gpio_active_low` | `true` | `true`: pull-up, ground activates. `false`: pull-down, high activates. |
| `gpio_sample_seconds` | `0.01` | Seconds between GPIO samples, 0.001–1. |
| `gpio_debounce_seconds` | `0.03` | Seconds an unchanged input must remain stable, 0–5. Even zero requires another sample to accept the candidate. |
| `serial_port` | `null` | Disabled, or a nonempty local serial device path such as `/dev/serial/by-id/...`. |
| `serial_baud` | `115200` | Integer bits per second, 1–4000000; must match the sender and be supported by the device. |
| `serial_read_timeout_seconds` | `0.1` | Receiver read timeout in seconds, 0.001–10. Partial commands are retained until their newline arrives. |
| `serial_write_timeout_seconds` | `0.5` | Receiver reply write timeout in seconds, 0.001–10. |

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
| `setup()` | Configure outputs, serial and I2C; disable mux channels; remain serial-silent until `START`. |
| `loop()` | Service serial commands, then polling and heartbeat repeatedly. Add short non-blocking application work here. |
| `serviceSerialCommands()` | Parse bounded uppercase `START`/`STOP` lines without dynamic memory; discard invalid lines. |
| `prepareSerialPacket()` | Freeze a complete header/data snapshot; consume only readings represented in that snapshot. |
| `deadlineReached(now, deadline)` | Compare millisecond deadlines with counter wraparound handling. |
| `selectMuxChannel(channel)` | Connect one sensor's mux channel; return whether the I2C write succeeded. |
| `disableAllMuxChannels()` | Request disconnection of all channels. The write result is not checked. |
| `startRanging(sensorIndex)` | Select the sensor's configured channel and send the measurement command; return success/failure. |
| `readDistanceMm(distanceMm)` | Decode the selected sensor's three-byte result; return success and update the output argument only for an in-range reading. |
| `medianOfHistory(sensor)` | Calculate the filtered distance without changing state. |
| `recordSuccessfulReading(sensorIndex, distanceMm)` | Update history/filter, clear the error count, and mark the reading valid. |
| `recordFailedReading(sensorIndex)` | Mark the reading invalid and increase its diagnostic error count, retaining earlier filter samples. |
| `findNearestSensor()` | Return the nearest valid sensor index, or `-1`; equal distances prefer the earlier configured zone. |
| `setAlarm(active)` | Apply configured alarm polarity, or do nothing when disabled. |
| `cachedDistance(index)` | Return the latest successful raw millimetres, or -1 if unavailable. |
| `serviceSerialOutput()` | Queue available bytes without waiting; finish the current snapshot, then send pending or changed values. |
| `distancesChangedSinceSend()` | Compare all four cached distances with the last fully queued data snapshot. |
| `updateAlarm()` | Update the alarm after each sensor attempt, independent of TX progress. |
| `finishCurrentSensor()` | Disable mux, start that sensor's cooldown, update the alarm, and advance to another sensor. |
| `serviceSensorPolling(now)` | Trigger eligible sensors and wait/read without delay(); skip sensors still cooling down. |
| `serviceHeartbeat(now)` | Toggle the enabled status output when its deadline arrives. This indicates loop activity, not sensor health. |

### Function map: camera selector and sender

`selector.py` keeps the selected camera, running pipeline identity, and last playback error in `State`. Its lock protects those shared values. The main thread reads standard input; workers handle playback, GPIO, and serial. Accepted inputs update `State`; only the playback worker starts/stops video. The latest accepted selection wins, and rapid updates can skip intermediate cameras.

| Function/class in `selector.py` | Use/action |
| --- | --- |
| `camera_number(value)` | Validate and return a camera number; raise `ValueError` for invalid input. |
| `resolve_inputs(values, current)` | Return the lowest active camera or hold `current` when all four inputs are zero. |
| `validate(config)` | Validate keys/types/ranges/quoting and return effective settings with defaults. No hardware is opened. |
| `command(config, camera, demo, headless)` | Build the GStreamer argument list for one camera. It does not launch the process. |
| `State.select()` / `State.inputs()` | Apply a direct selection or four-input snapshot under the lock. |
| `State.snapshot()` / `State.playback()` | Read status or update playback identity/error under the lock. Status does not prove a live frame. |
| `stop_process(process)` | Terminate the capture; force termination if it ignores the stop timeout. |
| `player(...)` | Switch/retry the selected camera and clean up its child process on shutdown. |
| `apply_message(state, line)` | Parse exactly one JSON action; return an acknowledgement or error object. |
| `Lines.feed(data)` | Assemble partial byte chunks into complete lines. Discard an entire command exceeding 1024 bytes. |
| `responses(state, lines, data)` | Convert complete input lines to newline-terminated JSON reply bytes. |
| `serial_control(...)` | Read physical serial commands, write replies, and reconnect after port failures. |
| `poll_gpio(...)` | Sample/debounce all four inputs and apply only stable changes. |
| `main(argv=None)` | Load/check settings, start workers, read stdin, and stop/close resources on exit. |

Near the top of `selector.py`, `DEFAULTS` supplies omitted optional settings and `NUMERIC_LIMITS` documents their accepted ranges. Named constants below them cover fixed protocol limits and internal polling/stop intervals. Change configuration first; changing these internals requires reviewing shutdown behavior and tests.

| Function in `control.py` | Use/action |
| --- | --- |
| `positive_integer()` / `positive_seconds()` | Reject invalid command-line baud/timeout values before opening a port. |
| `build_parser()` | Define command options and help text; require one action. |
| `make_message(args)` | Return the JSON line for camera, inputs, or status without doing I/O. |
| `send_serial_command(...)` | Open the sender's port, write one command, read/validate one reply, close the port, and return the reply object. |
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

`--check-config` prints the effective configuration and the four resulting pipeline argument lists, then exits. It works without GStreamer, GPIO libraries, serial libraries, or attached devices. It catches setting and quote errors, but does not start GStreamer to check plugin syntax or formats. Demo/headless switches affect the reported pipelines; the original configured source/sink quoting is still checked.

The automated tests use fake capture processes, clocks, GPIO buttons, and serial ports. They verify software behavior and supplied examples, not electrical wiring or real video. If deliberately changing camera mapping/default output, review the tests that assert those defaults too. For Arduino edits, use the IDE's **Verify** action with the actual target board selected, then upload and repeat the first-power-up checks. No Arduino board build or hardware validation is claimed by the Python test suite.

For live Pi checks, start with `--demo --headless`, then `--demo` with HDMI, then the real cameras and configured controls. These modes still need GStreamer and any libraries/devices required by enabled controls. Watch actual frames and inputs: an `ok: true` command reply, running process, or heartbeat LED alone does not establish system health.

### Verify all components from the project root

The Python checks use the standard library and do not require attached devices or the Pi runtime packages:

```sh
python3 -m unittest discover -s rpi-ahd-selector -p "test_*.py" -v
python3 -m unittest discover -s draft-gpio-link -p "test_*.py" -v
python3 -m unittest discover -s rpi-oled-bridge -p "test_*.py" -v
python3 rpi-ahd-selector/selector.py --check-config
python3 rpi-ahd-selector/selector.py --demo --headless --check-config
python3 rpi-ahd-selector/control.py --camera 2
python3 draft-gpio-link/warning_receiver.py --simulate 0 1 2 3 4 0 -1
python3 draft-gpio-link/warning_receiver.py --selector-json --simulate 0 1 2 3 4 0
```

Run all three explicit discovery commands: the tests live in separate component directories. The selector and sender suite covers command validation/framing, configuration defaults and limits, pipeline construction, switching/retry cleanup, GPIO arbitration, serial reconnects, and sender acknowledgements. The receiver suite covers the draft link separately. The OLED bridge suite covers distance parsing/order, stale input, framing, and USB cleanup. Python tests do not compile the Arduino sketches.

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
