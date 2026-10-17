# Manual review and adjustment guide

[Documentation index](index.md) · [Project overview](../README.md)

## Existing components

This repository contains ultrasonic sensing, a Pi-to-Nano OLED display path,
two-camera blinker selection, and a retired GPIO prototype retained as historical
reference. The display bridge consumes tagged sensor snapshots in reverse mode
or CSV in standalone mode. Rear sensor measurements never select side cameras.

| Component | Purpose | Files |
| --- | --- | --- |
| Ultrasonic sensing | Poll four RCWL-1655 or compatible AJ-SR04M I2C sensors through an I2C multiplexer and report distances over serial. | [`optic_coyote_ultrasonic/`](../optic_coyote_ultrasonic) |
| OLED display | Receive four distances on a second Nano and display decimal feet in sensor order. | [`optic_coyote_display/`](../optic_coyote_display) |
| Pi USB distance bridge | Gate ranging/OLED distance ownership from reverse GPIO, or explicitly run standalone CSV forwarding. | [`rpi-oled-bridge/`](../rpi-oled-bridge) |
| AHD camera selection | Show one of two AHD cameras on a Raspberry Pi HDMI display, selected manually through GPIO/serial/stdin or by an optional two-input blinker mode. | [`rpi-ahd-selector/`](../rpi-ahd-selector) |
| Optional Pi buzzer | Explicitly play configurable active-buzzer rhythms or passive PWM tones; no automatic trigger bindings. | [`rpi-buzzer/`](../rpi-buzzer), [configuration](../rpi-buzzer/buzzer.json), [API and wiring limits](pi-buzzer.md) |
| Retired GPIO prototype | Historical four-camera sensor-warning experiment; excluded from the supported installation. | [`draft-gpio-link/`](../draft-gpio-link) |

## File map and reading order

| File | What to review or change |
| --- | --- |
| [`README.md`](../README.md) | Project overview and links to installation and operating guides. |
| [`optic_coyote_ultrasonic.ino`](../optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino) | Arduino program. Start at `Config`, then read `setup()`, `loop()`, `serviceSensorPolling()`, and `serviceSerialOutput()`. |
| [`config.json`](../rpi-ahd-selector/config.json) | Camera sources, display output, GPIO, serial, and timing settings. Edit this first for camera installation changes. |
| [`reverse.json`](../rpi-oled-bridge/reverse.json) | Reverse GPIO, 100 ms HIGH qualification, USB limits, leases, and sample freshness. |
| [`reverse_control.py`](../rpi-oled-bridge/reverse_control.py) | ReverseGate qualification, SensorSession freshness, independent DisplayLink reconnects, guarded USB writes, and release handling. |
| [`diagnose_reverse.py`](../rpi-oled-bridge/diagnose_reverse.py) | Software checks and optional GPIO/USB bench cycle with Markdown/JSON reports. |
| [`reverse-diagnostic.json`](../rpi-oled-bridge/reverse-diagnostic.json) | Diagnostic deadlines, LOW response limit, quiet window, maximum observation gap, and minimum reply counts. |
| [`check_trigger_setup.py`](../tools/check_trigger_setup.py) | Software-only cross-check of reverse/blinker GPIO and device assignments in a complete checkout. |
| [`buzzer.py`](../rpi-buzzer/buzzer.py), [`buzzer.json`](../rpi-buzzer/buzzer.json) | Optional active/passive buzzer API, finite patterns, cancellation, strict settings, and CLI; DIYables passive active-low defaults at 3.3 V DC, disabled with pin unassigned. |
| [`test_diagnose_reverse.py`](../rpi-oled-bridge/test_diagnose_reverse.py) | Simulated diagnostic lifecycle, evidence classification, timeout cleanup, and false-PASS regressions. |
| [`reverse-trigger.md`](reverse-trigger.md) | Both Nano configuration headers, reverse protocol, idle rendering, setup, and verification. |
| [`selector.py`](../rpi-ahd-selector/selector.py) | Camera program. Start with the module overview, `main()`, and `validate()`, then follow `player()` or the relevant input function. |
| [`control.py`](../rpi-ahd-selector/control.py) | Sender helper. Read `build_parser()`, `make_message()`, `send_serial_command()`, then `main()`. |
| [`test_selector.py`](../rpi-ahd-selector/test_selector.py) | Examples and automated checks for commands, configuration, switching, GPIO, and reconnects. Fake processes/ports replace hardware. |
| [`test_trigger.py`](../rpi-ahd-selector/test_trigger.py) | Trigger timing, mappings, inhibition, black output, GPIO faults, and playback transition tests using synthetic time and devices. |
| [`test_control.py`](../rpi-ahd-selector/test_control.py) | Sender options, output JSON, acknowledgement validation, and error handling using a fake serial port. |
| [`diagnostic.json`](../rpi-ahd-selector/diagnostic.json) | Adapter diagnostic device, target mode, buffer counts, rate tolerance, and time limits. Independent of selector settings. |
| [`diagnose_adapter.py`](../rpi-ahd-selector/diagnose_adapter.py) | Read `diagnose()`, `hardware_worker()`, `BufferMeasurements`, `evaluate()`, and `render_report()` for inventory, physical measurements, classification, and report formatting. |
| [`test_diagnose_adapter.py`](../rpi-ahd-selector/test_diagnose_adapter.py) | Host-only diagnostic parsing, measurement, failure classification, worker lifecycle, and report tests. |

The sensor sketch and camera selector are independent. Distance reports do not select cameras. The [retired GPIO prototype](../draft-gpio-link/README.md) uses a historical four-camera protocol incompatible with the current two-camera selector; its firmware and listener are excluded from the supported installation.

## Camera settings reference

Edit `config.json` with a text editor. JSON requires double quotes, lowercase `true`/`false`/`null`, and no comments or trailing commas. Keep numbers as numbers, not quoted strings. The following tables provide the comments that cannot go inside JSON.

The program reads the file once at startup. Save it, run `--check-config`, then restart the selector to apply changes. `--config PATH` selects a different file; otherwise the file beside `selector.py` is used, regardless of the current working directory. `initial_camera` and `sources` are required; omitted optional settings use `DEFAULTS` near the top of `selector.py`. Unknown setting names are rejected so spelling mistakes cannot silently fall back to defaults.

| Setting | Supplied value | Meaning and accepted values |
| --- | --- | --- |
| `initial_camera` | `1` | Integer camera number, 1–2; ignored at startup in trigger mode. |
| `sources` | Two V4L2 pipeline strings | Exactly two nonempty strings, left then right by default. Device placeholders are `/dev/video0` and `/dev/video2`. |
| `sink` | `kmssink driver-name=vc4 force-modesetting=true sync=false` | Nonempty output pipeline fragment; normally the local HDMI display. |
| `output_width` | `1280` | Output width in pixels, integer 1–8192. |
| `output_height` | `720` | Output height in pixels, integer 1–8192. |
| `output_fps` | `60` | Pipeline frames per second, integer 1–240. Does not set the capture device's own frame rate. |
| `watchdog_timeout_ms` | `5000` | Integer milliseconds allowed without downstream video buffers, 1–600000. Expiry terminates the pipeline. |
| `retry_delay_seconds` | `2` | Seconds before a failed video pipeline or disconnected serial port retries, 0.05–300. A camera change bypasses the old camera's retry delay. |
| `player_poll_seconds` | `0.05` | Playback worker polling interval in seconds, 0.001–1. Applies in both modes. |
| `process_stop_timeout_seconds` | `2.0` | Timeout for each graceful and forced process termination wait, 0.05–10 seconds. Failed teardown stops the selector without launching another capture. Applies in both modes. |
| `gpio_pins` | `[]` | Disabled, or exactly two distinct BCM pin numbers 0–27 in camera order. Check board pin availability separately. |
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
| `trigger_left_camera` / `trigger_right_camera` | `1` / `2` | Distinct integer source numbers, each 1–2. |
| `trigger_active_low` | `false` | `false`: pull-down/HIGH active. `true`: pull-up/LOW active. Applies to both conditioned inputs. |
| `trigger_sample_seconds` | `0.01` | Trigger polling interval, 0.001–1 seconds. Separate from manual GPIO sampling. |
| `trigger_debounce_seconds` | `0.03` | Required unchanged pair duration, 0–5 seconds. Zero permits acceptance on the first sample. |
| `trigger_settle_seconds` | `0.05` | Additional stable duration before LEFT/RIGHT acceptance, 0–5 seconds. Does not delay BOTH. |
| `trigger_off_hold_seconds` | `1.0` | Both-inactive hold duration, 0–30 seconds. Initial OFF debounce arms the timer; pending/rejected input changes cannot postpone expiry. |

These limits catch editing mistakes; they are not promises that a camera, display, serial device, or Pi supports every accepted value. Timing fields accept finite numbers within their ranges. Integer fields reject decimals and booleans. Smaller watchdog/retry values can cause repeated restarts on slow hardware; longer serial timeouts can delay shutdown.

### Changing a camera source

The first `sources` entry is camera 1, even if its Linux device is named `/dev/video6`. GPIO order and JSON camera numbers follow this list order. Use stable device paths and supported capture formats as described in [Configure the capture devices](camera-setup.md#configure-the-capture-devices).

Each source fragment must supply decoded/raw video to the rest of the pipeline. For example, an MJPEG source needs `jpegdec` after its JPEG capture format. `command()` appends this sequence automatically:

```text
selected source -> two-buffer queue -> convert -> scale with borders
                -> adjust frame rate -> output format -> watchdog -> sink
```

Do not append a display sink to a source entry: `sink` is separate. Change capture resolution/rate inside the source fragment; change display video resolution/rate using `output_width`, `output_height`, and `output_fps`. Check the Pi display mode too when changing the requested output size. `--demo` substitutes test-pattern sources; `--headless` substitutes a sink that discards frames. Configured control inputs remain enabled in both modes.

Source/sink quoting is checked, but GStreamer element availability, format negotiation, camera identity, and HDMI operation require a real run. The pipeline runs without a shell, but its GStreamer elements still perform their configured actions. Use local capture and display elements to retain this project's local-only, live-only behavior.

## Arduino settings reference

Edit only the `Config` section for ordinary installation tuning, then compile and upload again. The running board does not read `config.json`. Array positions link the physical mux channel, zone label, reported distance column, and nearest-zone name.

| Setting | Default | Meaning and editing constraints |
| --- | --- | --- |
| `kPollingIntervalMs` | `400` | Nano USB sketch: minimum milliseconds between round starts, positive and below 2147483648. Four sequential I2C conversions need about 400 ms plus overhead. |
| `kMuxAddress` | `0x70` | 7-bit mux address; match the physical address straps. |
| `kSensorAddress` | `0x57` | RCWL-1655's fixed 7-bit address; changing a number does not readdress the sensors. |
| `kI2cClockHz` | `100000` | Positive I2C bus rate in Hz; choose a rate supported by the board, sensors, and wiring. |
| `kSensorCount` | `4` | Fixed program layout, checked at compile time. Supporting another count requires code changes. |
| `kMuxChannels` | `{0, 1, 2, 3}` | Exactly four distinct physical mux channels, each 0–7. |
| `kZoneLabels` | `rear_far_left`, `rear_left_middle`, `rear_middle`, `rear_far_right` | Exactly four labels. Keep them nonempty and free of commas/newlines and at most 23 characters; CSV escaping is not implemented. The header gains `_mm` automatically. |
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

## Function map: Arduino

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

## OLED renderer and settings

The display Nano owns formatting and drawing; the Pi transports integer
millimetres. The [OLED guide](oled-display.md#fixed-pixel-layout) defines
pixel geometry and the rounded `≥10` boundary. All non-reverse timing and
ownership settings remain in their existing modules.

| Source | Purpose |
| --- | --- |
| [`optic_coyote_display.ino`](../optic_coyote_display/optic_coyote_display.ino) | `Config` contains serial baud, OLED address/rotation, refresh interval, and data timeout. |
| [`display_protocol.h`](../optic_coyote_display/display_protocol.h) | Bounded standalone packet parsing and `formatFeet()` conversion to three render symbols. |
| [`distance_glyphs.h`](../optic_coyote_display/distance_glyphs.h) | Flash-resident 9×16 glyphs, narrow decimal point, per-column centering, and raster drawing. |
| [`reverse_protocol.h`](../optic_coyote_display/reverse_protocol.h) | Reverse session acquisition, renewals, ACKs, packet validation, and expiry. |
| [`reverse_config.h`](../optic_coyote_display/reverse_config.h) | Reverse mode default, accepted lease range, frame limit, and receive budget. |

| Function | Behavior |
| --- | --- |
| `distancePacketFresh(now)` | Check the selected protocol's packet age using wrap-safe arithmetic. |
| `renderReverseDistance(now, values)` | Format four physical sensor slots, skip identical cached views, and draw labels, glyphs, and units. |
| `renderIdle(now)` | Clear the reverse view once after ownership ends. |
| `refreshOled()` | Check device availability, enforce refresh timing, replace data that expires during drawing, and select idle when ownership expires. |
| `receiveDistances()` | Consume bounded USB input using current time for each byte. |
| `sendReverseAcknowledgement()` | Send the latest accepted session/request acknowledgement without blocking. |

The display shows `0.0` through `9.9`, then `≥10`, with `-.-` for unavailable
measurements. The five-byte field buffers contain three glyph tokens followed
by two zero bytes. A private `>` token selects the `≥` bitmap and never changes
the USB protocol. Changes to the font require the pixel-boundary and reverse
regressions in the [OLED verification procedure](oled-display.md#verify-before-installation).

## Function map: camera selector and sender

`selector.py` keeps selection, trigger state, pipeline identity, and errors in `State`. Its lock protects those shared values. The main thread reads standard input; workers handle playback, GPIO, and serial. Only the playback worker starts/stops video. In manual mode, the latest accepted selection wins. Trigger mode owns selection exclusively and retains stop transitions even when intermediate selections coalesce.

| Function/class in `selector.py` | Use/action |
| --- | --- |
| `camera_number(value)` | Validate and return a camera number; raise `ValueError` for invalid input. |
| `resolve_inputs(values, current)` | Return the lowest active camera or hold `current` when both inputs are zero. |
| `validate(config)` | Validate keys/types/ranges/quoting and return effective settings with defaults. No hardware is opened. |
| `command(config, camera, demo, headless)` | Build a camera pipeline, or generated black output when camera is `None`. No process launch. |
| `BlinkerTrigger.update(left, right, now)` | Debounce a normalized pair, settle single-side changes, and retain the last state through short OFF gaps using monotonic time. |
| `State.select()` / `State.inputs()` | Apply a direct selection or two-input snapshot under the lock. |
| `State.trigger()` | Apply trigger transitions/mappings, retain stop requests, and latch GPIO faults. Future BOTH entry behavior belongs here. |
| `State.snapshot()` / `State.playback()` | Read status or update playback identity/error under the lock. Status does not prove a live frame. |
| `stop_process(process, timeout)` | Terminate capture or black output, then force termination if needed; both waits are bounded and failure prevents replacement capture. |
| `player(...)` | Switch/retry camera or black output; recheck after teardown and process creation; cancel stale launches and clean up on shutdown. |
| `apply_message(state, line)` | Parse exactly one JSON action; return an acknowledgement or error object. |
| `Lines.feed(data)` | Assemble partial byte chunks into complete lines. Discard an entire command exceeding 1024 bytes. |
| `responses(state, lines, data)` | Convert complete input lines to newline-terminated JSON reply bytes. |
| `serial_control(...)` | Request cooperative exclusive serial access, read commands, reject short reply writes, and reconnect after port failures. |
| `poll_gpio(...)` | Sample/debounce both inputs and apply only stable changes. |
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

Sender options are `--camera 1..2`, `--inputs` followed by two 0/1 values, or `--status` (choose one). Optional `--serial PORT` sends to a device; omission prints JSON only. `--baud` defaults to 115200 and `--timeout` defaults to 3 seconds for each read/write. These are sender settings; they do not change the receiver's configuration. For example:

```sh
python3 control.py --serial COM3 --baud 115200 --timeout 5 --camera 2
```

## Check an edit before deployment

From `rpi-ahd-selector/`, run these checks (`python` can replace `python3` on Windows):

```sh
python3 selector.py --check-config
python3 selector.py --config config.json --check-config
python3 control.py --help
python3 -m unittest discover -v
```

`--check-config` prints the effective configuration, two camera pipeline argument lists, and `inactive_pipeline` for black output, then exits. It works without GStreamer, GPIO libraries, serial libraries, or attached devices. It catches setting and quote errors, but does not start GStreamer to check plugin syntax or formats. Demo/headless switches affect the reported pipelines; the original configured source/sink quoting is still checked.

The automated tests use fake capture processes, clocks, GPIO buttons, and serial ports. They verify software behavior and supplied examples, not electrical wiring or real video. If deliberately changing camera mapping/default output, review the tests that assert those defaults too. For Arduino edits, use the IDE's **Verify** action with the actual target board selected, then upload and repeat the first-power-up checks. No Arduino board build or hardware validation is claimed by the Python test suite.

For live Pi checks, start with `--demo --headless`, then `--demo` with HDMI, then the real cameras and configured controls. These modes still need GStreamer and any libraries/devices required by enabled controls. Watch actual frames and inputs: an `ok: true` command reply, running process, or heartbeat LED alone does not establish system health.

## Verify all components from the project root

The Python checks use the standard library and do not require attached devices or the Pi runtime packages:

```sh
python3 -m unittest discover -s rpi-ahd-selector -p "test_*.py" -v
python3 -m unittest discover -s rpi-oled-bridge -p "test_*.py" -v
python3 -m unittest discover -s rpi-buzzer -p "test_*.py" -v
python3 -m unittest discover -s tests/integration -p "test_*.py" -v
python3 rpi-buzzer/buzzer.py --check-config
python3 rpi-ahd-selector/selector.py --check-config
python3 rpi-ahd-selector/selector.py --demo --headless --check-config
python3 rpi-ahd-selector/control.py --camera 2
```

Run all listed discovery commands: the tests live in separate component directories. The selector and sender suite covers command validation/framing, configuration defaults and limits, pipeline construction, switching/retry cleanup, GPIO arbitration, serial reconnects, and sender acknowledgements. The OLED bridge suite covers distance parsing/order, stale input, framing, USB cleanup, reverse qualification, request freshness, and LOW cancellation. The buzzer suite covers active/passive configuration, playback, cancellation, fault reporting, and cleanup. The integration suite covers concurrent trigger states, GPIO/device assignment conflicts, unrelated device failures, serial ownership failures, and bounded camera teardown. Python tests do not compile the Arduino sketches. The [reverse guide](reverse-trigger.md#verification) supplies both reverse firmware host checks.

The installation checks run separately from the application suites. From the
project root on Linux or WSL, run:

```sh
python3 -m unittest discover -s packaging -p "test_*.py" -v
```

These checks exercise configuration preservation, service enablement, offline
inventory validation, and temporary payload staging. They do not build a Debian
package or offline installer. Linux provides the POSIX permissions, file locking,
symlinks, and `systemctl` behavior used by the full suite; platform-specific
checks are skipped where unavailable. Historical prototype checks remain in the
[retired guide](../draft-gpio-link/README.md#draft-checks-and-validation-boundary).

Build each sketch separately in Arduino IDE with the target board selected. With Arduino CLI and the matching board core already installed, a classic Nano build from the project root is:

```sh
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 optic_coyote_ultrasonic
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 optic_coyote_display
```

Install the OLED libraries listed in the [display guide](oled-display.md) before compiling its sketch. Use the board-specific FQBN when it differs. These commands compile without uploading. Firmware compilation and software tests do not establish physical sensor accuracy, electrical compatibility, GPIO/serial operation, camera capture, HDMI/OLED output, or end-to-end response time. Those require the hardware checks in the [sensor](ultrasonic-sensing.md#first-power-up-checks), [camera](camera-diagnostics.md), and [OLED](oled-display.md#verify-before-installation) guides. The display guide also includes the C++ host check for its actual sketch.

The Nano stream contract also has a host simulation that includes the actual sketch and substitutes the clock, serial port, and I2C devices. With a C++ compiler installed, run from the project root (Windows MinGW example):

```powershell
g++ -std=c++11 -Wall -Wextra -Werror -static -I tests/nano tests/nano/test_serial.cpp -o "$env:TEMP/optic-coyote-nano-test.exe"
if ($LASTEXITCODE -eq 0) { & "$env:TEMP/optic-coyote-nano-test.exe" }
```

It checks silent boot, complete command framing, start/stop/restart, per-reading cached packets, each sensor responding alone, trigger/read/partial/out-of-range failures, recovery, minimum conversion waits, per-sensor cooldown, clock rollover, stalled/partial serial writes, changed-value follow-up, sends during cooldown, and STOP/START mid-packet. This simulation does not exercise the Nano hardware, its bootloader, USB buffering, or acoustic interference.

## Git file handling

The root `.gitignore` excludes local settings, diagnostic reports, build trees,
firmware exports, host-test executables, and compiler coverage data. Normal
package output belongs in `dist/`; recognized package, manifest, checksum,
offline-bundle, and APT-work names are also excluded when generated in the
repository root or `packaging/`. Source, shipped JSON defaults, tests, and
maintained documentation images remain trackable.

`.gitattributes` specifies LF line endings for detected text, including Linux
maintainer scripts, and binary treatment for image assets and distribution
archives. It does not convert character encodings. The existing
`docs/nano-ultrasonic-pinout.md` uses Windows-1252; preserve that encoding when
editing it. New documentation uses UTF-8. Attribute changes do not rewrite
existing working files automatically.

Inspect an ignore decision with `git check-ignore -v --no-index -- PATH` and
attributes with `git check-attr text eol diff -- PATH`. The command
`git ls-files -ci --exclude-standard` identifies already tracked files matching
ignore rules; adding an ignore pattern does not untrack existing files.
Repository rules do not require changes to global Git settings, remotes,
credentials, or hooks.
