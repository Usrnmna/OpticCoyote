# Project Optic Coyote

This repository contains two independent four-input components. They have separate hardware and setup requirements; no connection between their outputs or controls is implemented here.

| Component | Purpose | Files |
| --- | --- | --- |
| Ultrasonic sensing | Poll four RCWL-1655 sensors through an I2C multiplexer and report distances over serial. | [`optic_coyote_ultrasonic/`](optic_coyote_ultrasonic/) |
| AHD camera selection | Show one of four AHD cameras on a Raspberry Pi HDMI display, selected through GPIO, USB serial, or standard input. | [`rpi-ahd-selector/`](rpi-ahd-selector/) |

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

An invalid or missing sensor is reported as `-1`. Possible system states are `CLEAR`, `WARNING`, `CRITICAL`, and `NO_VALID_SENSORS`.

### Timing and control integration

The sketch uses a non-blocking state machine instead of `delay()`. A measurement is triggered with command `0x01`, read after 100 ms, and converted from the returned 24-bit micrometre value to millimetres. The mux channel is then disabled before the next sensor is selected.

One complete four-sensor scan takes about 420 ms with the conservative default timing. Application logic can run alongside the scanner by adding non-blocking work to `loop()`. For motor control, treat `CRITICAL` as an immediate stop condition and `WARNING` as a slow-down or avoidance condition after testing the thresholds on the actual platform.

### First-power-up checks

1. Power the system with the sensor heads aimed in different directions.
2. Confirm that the TCA9548A responds at `0x70`.
3. Confirm that `0x57` appears only after selecting one mux channel.
4. Watch the Serial Monitor at `115200` baud.
5. Move a broad, flat target through each zone and verify its reported direction.
6. Tune the range and warning constants for the installation.

Do not fire all four sensors simultaneously. Reflections from one transducer can be received by another and create false detections.

## AHD camera selection (Raspberry Pi)

Live view only: displays one of four cameras fullscreen through the Pi HDMI output at 1280x720. Starts on a configured camera and accepts changes continuously through **both GPIO and USB serial**. No recording, video files, Ethernet, Wi-Fi, HTTP, RTSP or cloud service is used.

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

The program uses [GStreamer's KMS sink](https://gstreamer.freedesktop.org/documentation/kms/index.html) for fullscreen 1280x720 at 60 Hz. See [Raspberry Pi KMS configuration](https://www.raspberrypi.com/documentation/computers/configuration.html#set-the-kms-display-mode). Camera frames may repeat for 60 Hz output. Confirm actual HDMI resolution in the monitor information screen. If two displays are attached, add `connector-id=NUMBER` to the configured sink; `modetest -M vc4 -c` (package `libdrm-tests`) lists connector IDs. Output is HDMI, not analog AHD.

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

Inputs are sampled every 10 ms and must remain stable for 30 ms before acceptance. Each stable change applies the four-input selection rule. Releasing all inputs holds the last selection. Both GPIO and serial/stdin can operate together: the last accepted update wins. GPIO updates on a stable pin change and does not continually override serial commands. See [GPIO Zero input documentation](https://gpiozero.readthedocs.io/en/stable/api_input.html).

#### USB serial selection

Set `serial_port` to the Pi serial device, preferably `/dev/serial/by-id/...`. Set `serial_baud` to the controller rate, default 115200, 8N1. Serial is initially disabled (`null`) until the port is known. This is a physical serial connection. Do not connect two USB host ports with a passive USB cable; use suitable serial adapters or a controller presenting a USB serial device to the Pi.

The controller sends the JSON commands above and receives a JSON line reply. From a controller computer with Python and pyserial, use its own port name:

```sh
python3 control.py --serial COM3 --inputs 0 1 0 0
python3 control.py --serial COM3 --camera 4
python3 control.py --serial COM3 --status
```

Disconnected serial devices retry every two seconds without stopping video. Some controllers reset when their port opens; use a persistent serial session and wait for readiness on those devices.

Replies contain `ok`, `selected_camera`, `pipeline_camera` and `last_error`. `ok` confirms command acceptance, not delivery of a live frame. `pipeline_camera` identifies a running process, not verified camera health.

#### Local program control

A parent program can send JSON lines through the selector's standard input. A one-command example is:

```sh
python3 control.py --inputs 0 1 0 0 | python3 selector.py
```

The selector keeps running after input EOF. For ongoing commands, keep the input pipe open. Interactive commands can also be typed in the launching console, although fullscreen video may hide the console text. Replies go to standard output; diagnostic text goes to standard error.

### Recovery and testing

A five-second frame watchdog stops a stalled capture; failures retry after two seconds. Driver startup and teardown can take longer. Controls remain active during recovery. A switch stops the old capture and starts the new one. During a fault/switch the screen may be blank or retain an old frame; there is no signal-loss overlay. A still image is not proof of a live feed.

Use `python3 selector.py --demo` for four test patterns without cameras. `--demo --headless` discards video for pipeline tests without HDMI. Run software tests with `python3 -m unittest discover -v` from the `rpi-ahd-selector/` directory.

Before deployment, verify all four real feeds, both GPIO and serial, simultaneous inputs, rapid switching, capture disconnection/reconnection, startup selection, actual 720p output, latency, CPU load and temperature. Raspberry Pi, AHD hardware, GStreamer rendering, GPIO, serial hardware and HDMI have not been tested in the development environment.
