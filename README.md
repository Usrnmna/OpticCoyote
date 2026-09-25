# Project Optic Coyote

This repository contains two four-input components and a separate draft GPIO connection between them. The original sensor and camera programs remain independent; the draft provides an alternative Arduino sketch and a new Pi warning listener.

| Component | Purpose | Files |
| --- | --- | --- |
| Ultrasonic sensing | Poll four RCWL-1655 sensors through an I2C multiplexer and report distances over serial. | [`optic_coyote_ultrasonic/`](optic_coyote_ultrasonic/) |
| AHD camera selection | Show one of four AHD cameras on a Raspberry Pi HDMI display, selected through GPIO, USB serial, or standard input. | [`rpi-ahd-selector/`](rpi-ahd-selector/) |
| Draft GPIO connection | Send the nearest warning's camera number from Arduino; receive it in a separate Pi listener. | [`draft-gpio-link/`](draft-gpio-link/) |

Start with the [manual review and adjustment guide](#manual-review-and-adjustment-guide) for a file map, setting tables, function descriptions, and checks to run after editing. Hardware setup follows below for [Arduino sensing](#ultrasonic-sensing-arduino) and [Raspberry Pi cameras](#ahd-camera-selection-raspberry-pi).

## Draft Arduino-to-Pi GPIO connection

This draft establishes a local wired connection. It adds no network communication or recording. **The existing files in `rpi-ahd-selector/`, including its configuration, are unchanged.** The original ultrasonic sketch is also unchanged; upload the new standalone sketch instead when testing the connection.

The Pi listener must already be running to read GPIO. A wire changing level does not itself launch a Linux program. Start the listener once using the command below; it then reacts to incoming warnings until stopped. Automatic boot startup and launching a new process for each warning are outside this draft.

### Draft files and manual adjustment

| File | Review and edit here |
| --- | --- |
| [`arduino_camera_warning.ino`](draft-gpio-link/arduino_camera_warning/arduino_camera_warning.ino) | `Config` contains the existing sensor settings. `CameraLink` contains output pins and the sensor-to-camera map. `setupCameraLink()` initializes outputs; `publishCameraWarning()` updates them from `publishCompletedScan()`. This is a self-contained copy, so future sensor changes must be applied to both sketches if both are retained. |
| [`warning_receiver.py`](draft-gpio-link/warning_receiver.py) | Top-level defaults and `--help` expose GPIO and timing settings. `decode_camera()` reads the logical selection, `StableCamera` filters short transitions, `report_camera()` formats it, and `listen()` owns GPIO setup/cleanup. |
| [`test_warning_receiver.py`](draft-gpio-link/test_warning_receiver.py) | Software checks for all 16 wire combinations, transitions, cleanup, settings, and command acceptance by the unchanged camera selector. |

### Signal and camera mapping

Four signal wires encode one camera number by holding **exactly one** active. This is a held selection, not binary encoding, a pulse count, or a distance measurement. Both WARNING and CRITICAL select the nearest valid sensor's associated camera. Equal distances favor the earlier sensor in the configured order. A complete scan updates the selection, approximately every 420 ms plus processing overhead with default settings.

| Sensor zone | Camera number | Arduino output | Pi BCM input | Pi physical header pin |
| --- | --- | --- | --- | --- |
| front_left | 1 | D4 | GPIO17 | 11 |
| front_right | 2 | D5 | GPIO27 | 13 |
| rear_left | 3 | D6 | GPIO22 | 15 |
| rear_right | 4 | D7 | GPIO23 | 16 |

Camera numbers refer to entries 1-4 in the existing camera configuration's `sources` list. Edit `CameraLink::kCameraForSensor` to match where the physical cameras actually face. Multiple zones may share a camera. The output pins always remain ordered camera 1, 2, 3, 4. Pins D4-D7 assume a classic Uno/Nano; check availability on your actual Arduino board.

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

1. Open [`draft-gpio-link/arduino_camera_warning/arduino_camera_warning.ino`](draft-gpio-link/arduino_camera_warning/arduino_camera_warning.ino) in Arduino IDE. Choose your board and port; upload this sketch **instead of** the original. It requires only the board's standard `Wire` library. Sensor wiring and CSV output remain as documented below.
2. Copy this project to the Pi, for example `~/ProjectOpticCoyote`. Provide `python3-gpiozero` and `python3-lgpio` using the existing Pi installation instructions, or provision packages offline. The receiver uses [GPIO Zero's input device API](https://gpiozero.readthedocs.io/en/stable/api_input.html#digitalinputdevice) and [lgpio pin factory](https://gpiozero.readthedocs.io/en/stable/api_pins.html#lgpio).
3. Start the new listener from a Pi terminal:

```sh
cd ~/ProjectOpticCoyote
python3 draft-gpio-link/warning_receiver.py
```

The listener samples every 10 ms and accepts a state after 30 ms of stability. It reports an already-held warning at startup, prints changes only, and releases GPIO on Ctrl+C or SIGTERM. The listener does not start or switch the camera program in its default mode.

To change wiring or timing without editing Python:

```sh
python3 draft-gpio-link/warning_receiver.py --pins 17 27 22 23 --debounce-seconds 0.05
```

### Optional connection to the unchanged camera program

After the standalone wiring test, pipe the listener's optional JSON output into the existing selector's standard input:

```sh
cd ~/ProjectOpticCoyote
python3 draft-gpio-link/warning_receiver.py --selector-json | python3 rpi-ahd-selector/selector.py
```

The receiver sends commands such as `{"camera": 2}` only for valid warnings. Clear or conflicting inputs send no camera command; the existing selector keeps displaying its last selected camera. This uses the existing camera interface without changing its code or configuration. The supplied camera configuration already has `gpio_pins: []` and `serial_port: null`. Keep those settings for this test, and stop any other running selector instance first: only the draft listener should own these GPIO inputs. Capture device configuration and video dependencies still need to match your installation.

Use Ctrl+C in the foreground terminal to stop both programs. If the listener exits alone, the existing selector deliberately continues displaying its last camera after input closes; stop it separately if needed. This draft does not supervise the camera process or automatically restart either program.

### Draft checks and validation boundary

Run software tests and a simulated report from the project root (use `python` instead of `python3` on Windows if needed):

```sh
python3 -m unittest discover -s draft-gpio-link -p "test_*.py" -v
python3 draft-gpio-link/warning_receiver.py --simulate 0 1 2 3 4 0
python3 draft-gpio-link/warning_receiver.py --selector-json --simulate 0 1 2 3 4 0
```

Simulation checks output formatting only; it does not read GPIO or exercise timing. On hardware, test clear startup, an object in each zone, overlapping warnings, warning removal, Arduino reset, and receiver restart during a held warning. Compare Arduino CSV `nearest_zone` with the Pi camera number. In camera mode, verify each number displays the intended physical camera. Expect sensor scan/filter delay plus GPIO debounce; software timing does not establish actual end-to-end response time.

Validation for this draft: all 11 new receiver tests and all 35 existing camera tests passed. The draft Arduino sketch compiled for `arduino:avr:uno` with Arduino AVR core 1.8.8, using 6116 bytes flash and 528 bytes RAM. The original Arduino sketch and all existing camera source/configuration files were verified unchanged by SHA-256 checksums. The draft has not been uploaded or tested with Arduino, Pi GPIO, sensor, or AHD hardware. Select your actual target board and repeat the build and electrical checks before use.

## Ultrasonic sensing (Arduino)

This Arduino sketch polls four fixed-address RCWL-1655 ultrasonic sensors through a TCA9548A I2C multiplexer. It reads one sensor at a time, applies a three-reading median filter, finds the nearest object, drives an alarm output, and publishes one CSV record per complete scan.

### Required hardware

- One Arduino-compatible controller
- Four RCWL-1655 modules configured for I2C mode
- One TCA9548A I2C multiplexer at its default `0x70` address
- A regulated supply appropriate for the Arduino logic voltage
- I2C pull-up resistors if they are not already present on the TCA9548A breakout
- One `0.1 uF` bypass capacitor at each sensor, plus a bulk `10-47 uF` capacitor near the power distribution point

### Sensor configuration

Install `100 kOhm` at the RCWL-1655 `R7` position to select I2C mode. The four sensor signals are wired to separate mux channels:

| RCWL-1655 pin/function | TCA9548A connection |
| --- | --- |
| VCC | Common regulated supply |
| GND | Common ground |
| Trig / RX / SCL | `SC0`, `SC1`, `SC2`, or `SC3` |
| Echo / TX / SDA | `SD0`, `SD1`, `SD2`, or `SD3` |

The TCA9548A upstream `SCL` and `SDA` connect to the Arduino's hardware I2C pins. All grounds must be connected together. Keep all I2C pull-ups tied to the selected logic supply; do not mix 3.3 V and 5 V pull-ups.

### Build and upload

Open [`optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino`](optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino) in the Arduino IDE, choose the correct board and serial port, then upload it. The sketch only needs the standard `Wire` library.

The defaults suit a classic Arduino Uno/Nano:

- Serial rate: `115200`
- Alarm output: digital pin `8`, active high
- Status heartbeat: built-in LED
- TCA9548A channels: `0`, `1`, `2`, `3`
- Warning threshold: `600 mm`
- Critical threshold: `300 mm`
- Accepted sensor range: `200-5000 mm`

All of these values are grouped in the `Config` namespace near the top of the sketch.

### Serial output

The program prints a header followed by CSV records:

```text
time_ms,front_left_mm,front_right_mm,rear_left_mm,rear_right_mm,nearest_zone,nearest_mm,state
1680,742,515,1204,980,front_right,515,WARNING
2100,738,509,1198,977,front_right,509,WARNING
```

An invalid, missing, or out-of-range sensor is reported as `-1` and excluded from nearest-object selection. Possible system states are `CLEAR`, `WARNING`, `CRITICAL`, and `NO_VALID_SENSORS`. `CLEAR` describes the valid readings only: other sensors may be invalid. A reading below the configured minimum range is invalid, not automatically `CRITICAL`.

The alarm output is on for both `WARNING` and `CRITICAL`, and off for `CLEAR` and `NO_VALID_SENSORS`. It updates once per completed scan. Error handling retains the sensor's earlier filter samples, so its first valid reading after recovery can still be influenced by pre-error distances. This is prototype reporting behavior; no motor-stop action or separate fault alarm is implemented.

### Timing and control integration

The sketch uses a non-blocking state machine instead of `delay()`. A measurement is triggered with command `0x01`, read after 100 ms, and converted from the returned 24-bit micrometre value to millimetres. The mux channel is then disabled before the next sensor is selected.

One complete four-sensor scan takes about 420 ms with the conservative default timing, plus I2C and serial processing overhead. Application logic can run alongside the scanner by adding non-blocking work to `loop()`. The scheduling uses no `delay()`, but the underlying `Wire` transactions and serial writes are synchronous and can block. Any future motion controller needs its own tested response to critical readings, invalid sensors, and delayed scans.

### First-power-up checks

1. Power the system with the sensor heads aimed in different directions.
2. Confirm that the TCA9548A responds at `0x70`.
3. Confirm that `0x57` appears only after selecting one mux channel.
4. Watch the Serial Monitor at `115200` baud.
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

Serial/stdin commands are newline-terminated JSON:

```json
{"inputs":[0,1,0,0]}
{"camera":4}
{"status":true}
```

The four inputs correspond to cameras 1–4. One active input selects that camera. All zero holds the previous selection. Multiple active inputs select the lowest numbered camera. Commands are complete snapshots, latch until changed and need no continuous retransmission. Rapid commands coalesce to the latest selection. Invalid commands leave selection unchanged and return an error.

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
| [`README.md`](README.md) | Setup, settings reference, behavior, and checks. This is the shared guide for both programs. |
| [`optic_coyote_ultrasonic.ino`](optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino) | Arduino program. Start at `Config`, then read `setup()`, `loop()`, `serviceSensorPolling()`, and `publishCompletedScan()`. |
| [`config.json`](rpi-ahd-selector/config.json) | Camera sources, display output, GPIO, serial, and timing settings. Edit this first for installation changes. |
| [`selector.py`](rpi-ahd-selector/selector.py) | Camera program. Start with the module overview, `main()`, and `validate()`, then follow `player()` or the relevant input function. |
| [`control.py`](rpi-ahd-selector/control.py) | Sender helper. Read `build_parser()`, `make_message()`, `send_serial_command()`, then `main()`. |
| [`test_selector.py`](rpi-ahd-selector/test_selector.py) | Examples and automated checks for commands, configuration, switching, GPIO, and reconnects. Fake processes/ports replace hardware. |
| [`test_control.py`](rpi-ahd-selector/test_control.py) | Sender options, output JSON, acknowledgement validation, and error handling using a fake serial port. |

The original two components are independent. Arduino CSV distance reports are **not** camera-selection JSON commands. The separate [draft GPIO connection](#draft-arduino-to-pi-gpio-connection) supplies an alternative Arduino sketch and a Pi listener; its optional JSON output uses the camera program's existing input interface.

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
| `kMuxAddress` | `0x70` | 7-bit mux address; match the physical address straps. |
| `kSensorAddress` | `0x57` | RCWL-1655's fixed 7-bit address; changing a number does not readdress the sensors. |
| `kI2cClockHz` | `100000` | Positive I2C bus rate in Hz; choose a rate supported by the board, sensors, and wiring. |
| `kSensorCount` | `4` | Fixed program layout, checked at compile time. Supporting another count requires code changes. |
| `kMuxChannels` | `{0, 1, 2, 3}` | Exactly four distinct physical mux channels, each 0–7. |
| `kZoneLabels` | `front_left`, `front_right`, `rear_left`, `rear_right` | Exactly four labels. Keep them nonempty and free of commas/newlines; CSV escaping is not implemented. The header gains `_mm` automatically. |
| `kMeasurementTimeMs` | `100` | Wait between trigger and read in milliseconds, positive 16-bit integer. Verify conversion timing before reducing it. |
| `kInterSensorGuardMs` | `5` | Pause between sensors in milliseconds, 8-bit integer 0–255. |
| `kMinimumDistanceMm` / `kMaximumDistanceMm` | `200` / `5000` | Inclusive accepted range in millimetres, 16-bit unsigned values. Minimum must not exceed maximum. Outside readings become invalid. |
| `kWarningDistanceMm` / `kCriticalDistanceMm` | `600` / `300` | Inclusive thresholds in millimetres, 16-bit unsigned values. Critical must not exceed warning. For both states to be reachable, use `minimum <= critical < warning <= maximum`; equal thresholds skip `WARNING`. |
| `kAlarmPin` | `8` | Board digital pin; `255` disables it. Must differ from an enabled heartbeat pin. |
| `kAlarmActiveHigh` | `true` | `true` activates the alarm with HIGH; `false` with LOW. |
| `kHeartbeatPin` | `LED_BUILTIN` | Board status LED pin; `255` disables heartbeat output. |
| `kHeartbeatToggleMs` | `500` | Milliseconds between LED toggles, greater than 0 and below 2147483648. Two toggles make one full cycle. |
| `kSerialBaud` | `115200` | Positive serial bits per second; match the Serial Monitor/receiver and board capabilities. |

Compile-time assertions catch array lengths, duplicate/out-of-range channels, inverted thresholds/ranges, zero timing/rates, and output pin collisions. They do not validate physical wiring, supported pins/rates, or label text. Keep edits within the declared C++ integer types.

`Design` contains protocol and algorithm constants, not ordinary tuning values: the one-shot command, three-byte response, micrometre conversion, three-sample history, and disabled-pin marker. In particular, changing `kHistorySize` alone does not implement a different filter. The filter uses the first sample directly, averages the first two, and then uses the median of the latest three successful readings.

### Function map: Arduino

Comments above each function describe its inputs, outputs, and hardware/state changes. Sensor indexes inside the sketch are zero-based, 0–3.

| Function | Use/action |
| --- | --- |
| `setup()` | Configure outputs, serial and I2C; disable mux channels; print the CSV header once. |
| `loop()` | Read the current clock and service polling/heartbeat repeatedly. Add short non-blocking application work here. |
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
| `printDistanceOrInvalid(sensor)` | Print the filtered millimetres or `-1` to serial. |
| `publishCompletedScan()` | Determine nearest/state, update alarm, and print a complete CSV row. This is the place to inspect or extend scan-level decisions. |
| `finishCurrentSensor(now)` | Disable mux channels, publish after the last sensor, advance to the next, and schedule the guard interval. |
| `serviceSensorPolling(now)` | Advance through trigger, wait/read, and guard phases without using `delay()`. |
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

Validation completed during this readability review: 35 Python tests passed, and the supplied configuration passed `--check-config`. The Arduino sketch compiled for an Uno using the installed Arduino AVR core 1.8.8 (5836 bytes flash, 519 bytes RAM). No board was uploaded/flashed, and no physical sensor, camera, Pi display, GPIO, or serial connection was exercised.
