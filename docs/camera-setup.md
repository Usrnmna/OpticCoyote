# AHD camera selection (Raspberry Pi)

[Documentation index](index.md) · [Project overview](../README.md)

Current release: [v0.5.2-beta](release-notes-v0.5.2-beta.md) (Debian `0.5.2~beta`).

The supplied configuration displays live video from one of two cameras fullscreen through the Pi HDMI output at 1280x720. It starts on a configured camera and supports continuous selection through standard input and **both GPIO and USB serial** once their pins/port are configured; GPIO and serial are initially disabled. It uses no recording, video files, Ethernet, Wi-Fi, HTTP, RTSP or cloud service. Keep source and sink edits local and live-only: the configured GStreamer strings are executable pipeline instructions, and validation does not enforce that restriction.

The supported installation enables [blinker trigger mode](#blinker-trigger-mode), starts with no camera capture, selects a mapped left/right camera, and retains that view through blinker OFF gaps. BOTH stops camera capture and displays black. This mode uses two protected GPIO inputs and owns selection exclusively; it does not change the sensor or OLED firmware.

## Hardware

```text
Left mirror camera  --> AHD-to-USB UVC capture 1 --+
Right mirror camera --> AHD-to-USB UVC capture 2 --+--> powered USB hub --> Pi 5 (4 GB) --> HDMI display

Left/right blinkers --> protected 3.3 V inputs --> Pi
```

The Pi cannot accept AHD coax directly. Each camera needs an **AHD-capable decoder/capture device** compatible with its resolution and frame rate. The program expects two independently accessible Linux V4L2 capture devices. A multi-channel unit is suitable if its Linux driver exposes two independent feeds, not just a combined quad-view image. No DVR/NVR or recording hardware is required.

The installation uses the GRACETOP USB-A 2.0 AHD capture adapter identified below. Its published specifications describe the intended interface; operation on the Raspberry Pi 5 (4 GB) remains unverified. Ordinary composite/CVBS USB adapters cannot be assumed to accept AHD.

Use a suitable Pi power supply, cooling and a powered USB hub. Both cameras remain connected, but only the selected capture is opened. This reduces USB bandwidth and decode load. Switching interrupts video while the next capture starts; seamless switching is not implemented.

### GreenYi camera identity

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

### GRACETOP adapter identity and advertised specifications

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

Source: [GRACETOP specifications](https://www.gracetop.com/products/433t54w43). Connector orientation, lead order, camera supply requirements, and the 5 V output's current capacity require confirmation on the actual hardware. The listing is not a verified harness pinout. See [camera wiring](project-wiring.md#camera-and-monitor-connectors).

No Pi enumeration, sustained capture, unique-frame-rate, decode performance, HDMI output, or switching-latency result has been recorded for this adapter in the project. The advertised 60 fps USB mode does not establish 60 distinct camera exposures per second. General Linux support does not establish successful operation with the installed Pi OS/kernel, hub, cables, and cameras. The [verification procedure](camera-diagnostics.md#verify-mjpeg-720p60-on-the-pi) separates these evidence levels.

## Install on the Pi

Recommended target: **Raspberry Pi OS Lite (64-bit), Debian 13 Trixie**, on the **Raspberry Pi 5 with 4 GB RAM**, and a monitor supporting 720p60 on the first HDMI port. Complete the [Pi 5 setup guide](rpi5-setup.md) for OS installation and whole-project provisioning. For camera-only setup, copy [`rpi-ahd-selector/`](../rpi-ahd-selector) to `~/rpi-ahd-selector` using an SD card or USB drive. Install these packages once, or pre-provision the OS image for a completely offline installation:

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

## Configure the capture devices

Configuration and control commands below run from the `rpi-ahd-selector/`
directory unless another working directory is specified.

For the complete checkout used by the Pi setup guide:

```sh
cd ~/ProjectOpticCoyote/rpi-ahd-selector
```

For a camera-only copy, use `cd ~/rpi-ahd-selector` instead. These are source
checkout procedures. Package installations use `/etc/project-optic-coyote/camera.json`
and the `optic-coyote-camera` wrapper; see the
[installed commands](installation-package.md#configuration-and-cli-commands).

```sh
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/ /dev/v4l/by-path/
v4l2-ctl -d /dev/video0 --list-formats-ext
```

Replace each `device=` value in [`config.json`](../rpi-ahd-selector/config.json) with the correct capture node. `/dev/video0` and `/dev/video2` are placeholders. Prefer stable `/dev/v4l/by-id/...` names, or `/dev/v4l/by-path/...` if identical adapters lack unique serial numbers. Keep adapters on the same hub ports for path-based identification. Some devices also expose metadata nodes; those are not video streams.

Initial pipelines negotiate format automatically. For predictable bandwidth and quality, select an explicitly supported format based on `--list-formats-ext`. After verifying the GRACETOP adapter's advertised MJPEG 720p60 mode, a source entry can use:

```text
v4l2src device=/dev/v4l/by-path/YOUR_DEVICE do-timestamp=true ! image/jpeg,width=1280,height=720,framerate=60/1 ! jpegdec
```

For raw YUYV capture (called YUY2 by GStreamer), the listing advertises only 10 fps at 720p. Use this alternative only if the actual device enumerates and captures that mode:

```text
v4l2src device=/dev/v4l/by-path/YOUR_DEVICE do-timestamp=true ! video/x-raw,format=YUY2,width=1280,height=720,framerate=10/1
```

Request only adapter-supported formats. Capture uses [GStreamer's V4L2 source](https://gstreamer.freedesktop.org/documentation/video4linux2/v4l2src.html). Non-16:9 video is scaled with borders. Frames pass through memory to the display; they are not saved.

Capture validation and report generation are covered in
[Camera capture diagnostics](camera-diagnostics.md).

## Run and select

```sh
python3 selector.py
```

When the Pi setup procedure has created `config.local.json`, run
`python3 selector.py --config config.local.json` instead. Without `--config`,
the selector reads the supplied `config.json`, not the local configuration.

In manual mode, set `initial_camera` to 1–2 (default 1). Trigger mode ignores this startup selection and begins in IDLE. Ctrl+C stops the program. Use `--config PATH` for another configuration.

Serial/stdin commands are newline-terminated JSON objects containing exactly one action:

```json
{"inputs":[0,1]}
{"camera":2}
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

In manual mode, the two inputs correspond to cameras 1–2. One active input selects that camera. All zero holds the previous selection. Multiple active inputs select the lowest numbered camera. Commands are complete snapshots, latch until changed and need no continuous retransmission. Rapid commands coalesce to the latest selection. Invalid commands leave selection unchanged and return an error. `inputs` accepts two JSON booleans or integer 0/1 values; `camera` requires an integer 1-2 and `status` requires `true`. Trigger mode rejects both selection commands in every state; status remains available over stdin and configured serial. Blank lines are ignored. Commands may contain at most 1024 bytes before the newline; an oversized line is discarded in full and receives an error when its newline arrives. An incomplete final line is not executed at input EOF.

### GPIO selection

For manual mode, set `gpio_pins` to two distinct **BCM GPIO numbers** in camera order. Manual GPIO is disabled in the supplied template until pin assignments are configured. An example is `[17,27]` (physical header pins 11 and 13); confirm those pins are free before wiring.

With `gpio_active_low: true`, inputs use internal pull-ups and activate when connected to Pi ground through a switch, dry contact or compatible open-drain output. For active-high 3.3 V logic, set `gpio_active_low: false` to use pull-downs. Never connect 5 V, 12 V or RS-232 directly to GPIO. Confirm controller voltage and common-ground/isolation requirements first.

By default, inputs are sampled every 10 ms and must remain stable for 30 ms before acceptance; adjust `gpio_sample_seconds` and `gpio_debounce_seconds` to tune this. Each stable change applies the two-input selection rule. Releasing all inputs holds the last selection. Both GPIO and serial/stdin can operate together: the last accepted update wins. GPIO updates on a stable pin change and does not continually override serial commands. See [GPIO Zero input documentation](https://gpiozero.readthedocs.io/en/stable/api_input.html).

### Blinker trigger mode

For simultaneous reverse ranging/OLED operation, follow the
[combined-trigger guide](combined-triggers.md). Its software-only checker
detects overlapping GPIO and inspectable USB/video device assignments. BOTH
inhibits camera capture without changing the reverse session.

All selector installation settings are in [`rpi-ahd-selector/config.json`](../rpi-ahd-selector/config.json). Trigger mode is disabled in the supplied file to avoid claiming unassigned GPIO pins. Enable it by setting `trigger_enabled` to `true`, keep `gpio_pins` empty, and set the two trigger pins and camera mappings. Exactly two sources are required. With the default mapping, camera 1 is the exterior left mirror-area camera and camera 2 is the exterior right mirror-area camera. Both face rearward along the outside of the vehicle. The default mappings are left=1 and right=2; adjusted mappings must still identify those physical sides.

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

Pins use BCM numbering, not physical header positions. GPIO17 and GPIO27 correspond to physical pins 11 and 13. These are editable examples, shared with the retired GPIO draft; do not run both listeners on the same pins. Camera mappings must be distinct integers 1–2. Replace capture device placeholders with verified stable device paths. For the GRACETOP adapter, verify MJPEG 720p60 before using the `image/jpeg,width=1280,height=720,framerate=60/1 ! jpegdec` source shown in [capture configuration](#configure-the-capture-devices). MJPEG is the local capture format; this mode adds no network streaming.

Vehicle blinker voltage must pass through a suitable protected input interface before reaching the Pi. The software reads normalized logical activity, not vehicle voltage. With `trigger_active_low: false`, both inputs use pull-downs and 3.3 V HIGH means active. With `true`, both use pull-ups and LOW means active, suitable for an inverting open-collector interface. See the [blinker wiring requirements](project-wiring.md#optional-blinker-trigger-inputs).

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

### USB serial selection

Set `serial_port` to the Pi serial device, preferably `/dev/serial/by-id/...`. Set `serial_baud` to the controller rate, default 115200, 8N1. Serial is initially disabled (`null`) until the port is known. This is a physical serial connection. Do not connect two USB host ports with a passive USB cable; use suitable serial adapters or a controller presenting a USB serial device to the Pi.

The controller sends the JSON commands above and receives a JSON line reply. From a controller computer with Python and pyserial, use its own port name:

```sh
python3 control.py --serial COM3 --inputs 0 1
python3 control.py --serial COM3 --camera 2
python3 control.py --serial COM3 --status
```

Disconnected serial devices retry every two seconds by default (`retry_delay_seconds`) without stopping video. Some controllers reset when their port opens; use a persistent serial session and wait for readiness on those devices.

Successful replies contain `ok: true`, `selected_camera`, `pipeline_camera`, `last_error`, `display_mode`, `trigger_state`, `trigger_error`, and `stop_generation`. Invalid-command replies contain `ok: false` and `error`. `selected_camera` is `null` when trigger mode prohibits capture; `pipeline_camera` can still name the previous camera while teardown is pending. `display_mode` reports `camera`, `blank`, or `stopped` for the playback worker's process state. `trigger_state` is `null` in manual mode. `stop_generation` counts trigger transitions requiring capture inhibition. `ok` confirms command acceptance, not delivery of a live frame. Neither `pipeline_camera` nor `display_mode` proves physical video or successful screen clearing.

### Local program control

A parent program can send JSON lines through the selector's standard input. A one-command example is:

```sh
python3 control.py --inputs 0 1 | python3 selector.py
```

The selector keeps running after input EOF. For ongoing commands, keep the input pipe open. Interactive commands can also be typed in the launching console, although fullscreen video may hide the console text. Replies go to standard output; diagnostic text goes to standard error.

## Recovery and testing

By default, a five-second frame watchdog stops a stalled pipeline, and failures retry after two seconds. Adjust `watchdog_timeout_ms` and `retry_delay_seconds` for those timings. The watchdog detects missing buffers, not repeated/frozen image content. Driver startup and teardown can take longer. Controls remain active during recovery. A switch stops the old capture and starts the new one. During a fault/switch the screen may be blank or retain an old frame; there is no signal-loss overlay. A still image is not proof of a live feed.

Use `python3 selector.py --demo` for two test patterns without cameras. `--demo --headless` discards video for pipeline tests without HDMI. Run software tests with `python3 -m unittest discover -v` from the `rpi-ahd-selector/` directory.

Before deployment, verify both real feeds, both GPIO and serial, simultaneous inputs, rapid switching, capture disconnection/reconnection, startup selection, actual 720p output, latency, CPU load and temperature. Raspberry Pi, AHD hardware, GStreamer rendering, GPIO, serial hardware and HDMI have not been tested in the development environment.

For trigger mode, first use a protected bench input to verify left/right mapping, polarity, startup with no capture, brief glitches, held HIGH, repeated blink OFF gaps, final OFF timeout, BOTH while either camera runs, hazard edge skew, and rapid direction changes. Confirm manual commands cannot override BOTH, camera retries stop on inhibition, and the display clears. Measure activation and stop latency on the installed hardware: debounce/settling, sampling, `player_poll_seconds`, process teardown, and capture/display startup all contribute. `process_stop_timeout_seconds` bounds each graceful and forced termination wait; final cleanup can retry, so it is not a guaranteed end-to-end stop bound. Then measure vehicle signal levels, PWM/diagnostic pulses, and blink timing before choosing final input protection and tuning values.

The complete [camera settings reference](development.md#camera-settings-reference)
records accepted values and defaults.
