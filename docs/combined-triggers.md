# Reverse and blinker modes operating together

The recommended operating system is Raspberry Pi OS Lite (64-bit), Debian 13
Trixie. Complete the [Pi 5 (4 GB) setup guide](rpi5-setup.md) for installation,
dependencies, permissions, and console HDMI configuration.
The [installation package](installation-package.md) provides separate camera
and reverse services. Successful setup enables both for boot; failed
configuration leaves both disabled. Stop these services before foreground tests
or live diagnostics.

The Raspberry Pi 5 with 4 GB RAM runs two independent processes. The reverse
bridge owns sensor acquisition and the OLED Nano. The blinker selector owns
camera capture and HDMI output. Neither trigger state changes the other
process's state or timing. No combined controller or display-priority rule is
required for these distinct outputs.

Failures remain local to the affected function. A missing camera or failed
capture pipeline does not stop reverse acquisition; another camera can still
be selected. A missing sensor USB endpoint causes the reverse bridge to release
acquisition/display ownership and retry without disabling blinker playback.
An absent or failed OLED link releases/retries only that link; qualified reverse
sensor acquisition continues. OLED reconnection uses fresh display ownership
and current sample ages without restarting the sensor session. LOW still stops
sensor ranging and releases any connected reverse display. The selector's optional JSON
serial-control endpoint retries independently of its blinker and playback
workers. The optional buzzer has no automatic trigger connections. Its separate
CLI cannot stop camera or reverse processes; future in-process integrations
must catch buzzer playback and cleanup failures at the optional call boundary
and report the fault without setting another feature's shutdown event.

The selector's stdin/stdout command connection is optional. Input/readiness
errors, incomplete reply writes, or flush failures disable only that connection; GPIO monitoring,
serial control, and video playback continue. Capture subprocesses receive null
stdin/stdout so they do not inherit that connection; GStreamer diagnostics use
standard error. A missing `python3-serial` package disables only the optional
serial worker and logs an error. Install the package and restart the selector
to restore that worker. An unplugged serial endpoint instead retries normally.

| Reverse input/state | Blinker state | Sensor/OLED behavior | Camera/HDMI behavior |
| --- | --- | --- | --- |
| LOW or unqualified HIGH | LEFT or RIGHT | Idle; no distance ownership | Selected side camera |
| Qualified HIGH | LEFT or RIGHT | Ranging and fresh distances | Selected side camera |
| Qualified HIGH | BOTH | Ranging and fresh distances continue | Both camera streams inhibited; black output |
| LOW after activation | LEFT/RIGHT during an OFF gap | Release sensor/OLED session | Existing side view retains its configured hold |
| Qualified HIGH | IDLE or blinker GPIO fault | Reverse continues while its own GPIO/USB links remain healthy | Camera capture inhibited |
| Reverse GPIO/sensor USB fault | Any blinker state | Acquisition stops directly or by lease fallback; OLED released | Blinker state remains independent |
| OLED USB/ACK fault | Any blinker state | Qualified sensor acquisition continues; OLED link retries independently | Blinker state remains independent |

## GPIO and port assignments

The supplied blinker pins are BCM17 and BCM27. Reverse deliberately has no
default pin. Assign a distinct unused GPIO in `reverse.local.json`; BCM22 is
an example only when the optional four-line camera draft and other peripherals
are not using it. BCM numbers and physical header positions differ. The
[wiring guide](project-wiring.md) describes the protected 3.3 V input interfaces.

The blinker selector rejects simultaneous use of its four-line `gpio_pins`
input mode. Do not run the separate GPIO draft receiver on pins used by either
trigger process. GPIO construction/claim errors abort startup and close any
already acquired resources before starting control workers. Host tests inject
these failures; actual Pi pin allocation behavior remains unverified.

Keep the sensor Nano, OLED Nano, optional selector JSON serial-control endpoint,
and video capture nodes distinct. Reverse packets are not camera JSON commands.
Leave selector `serial_port` as `null` unless a separate controller link is
actually required. Status requests remain available over stdin; manual camera
selection commands are rejected while blinker mode owns selection.

All project serial opens in the bridge, selector listener, and command sender
request `exclusive=True`. On POSIX this uses pySerial's cooperative exclusive
port lock. A competing cooperating process fails its open rather than sharing
reads/writes. The selector retries after its configured retry delay; the reverse
bridge requalifies after sensor reconnection. A display-only failure retries
that link without resetting sensor acquisition. This is not a
guarantee against unrelated serial monitors that ignore cooperative locking,
device-opening reset effects, stale device names, or incorrect first ownership.
Close running owners before uploads and diagnostics. A short command or reply
write fails the exchange and closes the port; queued acknowledgements cannot
turn an incomplete command into a successful exchange.

## Software-only setup check

Run the checker from a complete repository checkout before starting either
process. It uses the existing component configuration validators and does not
import hardware drivers, open GPIO/USB/video devices, or launch GStreamer.

```sh
python3 tools/check_trigger_setup.py \
  --selector-config rpi-ahd-selector/config.local.json \
  --reverse-config rpi-oled-bridge/reverse.local.json \
  --sensor-port /dev/serial/by-path/YOUR_SENSOR_NANO \
  --display-port /dev/serial/by-path/YOUR_DISPLAY_NANO
```

Enable `trigger_enabled` in the selector configuration and assign
`reverse_gpio_pin` before this check. The checker rejects overlapping trigger
pins, duplicate sensor/display/control paths, filesystem aliases visible on the
current host, and duplicate explicit V4L2 capture paths. Identity checks include
resolved paths, filesystem device/inode pairs, and character-device major/minor
identity (`st_rdev`); two different node names can represent the same device.
All inspected serial/capture paths must resolve to character devices. Missing
paths, dangling links, permission failures, other `stat` errors, and paths that
resolve to regular files, directories, or block devices produce an incomplete
verdict. The JSON `device_issues` field distinguishes these cases.

Pipeline inspection uses a deliberately narrow allowlist. A source must be a
linear `v4l2src` fragment with one explicit `device=` and optional
`do-timestamp=true|false`, optionally followed by JPEG/raw-video caps and a
property-free `decodebin` or `jpegdec`. Device paths containing whitespace or
pipeline punctuation require manual inspection. Accepted caps fields are `width`,
`height`, `framerate`, and `format`; duplicate properties are not accepted.
Branches, additional elements or properties, and other unparsed structure
require manual inspection even when a V4L2 path is visible. Explicit device
assignments in such fragments are still checked for known conflicts. Sink
inspection accepts `kmssink` with only `driver-name=vc4`,
`force-modesetting=true|false`, and `sync=true|false`, or `fakesink` with only
`sync=true|false` and `async=true|false`. Other sinks and sink properties require
manual inspection. This allowlist establishes only resource-check coverage;
it does not establish successful negotiation, capture, decoding, or display.

Add `--buzzer-config rpi-buzzer/buzzer.local.json` when checking the optional
Pi buzzer configuration. Its component validator is applied, and a non-null
`gpio_pin` must be distinct from all trigger inputs even when the buzzer is
disabled. A disabled configuration with no pin or hardware type is reported as
unconfigured; it does not invalidate the other assignment checks.

Exit status `0` means every configured serial/capture path was inspectable as
a distinct character device and the pipeline fragments matched the allowlist;
this is configuration evidence only. Exit `1` and JSON `result: INCOMPLETE`
mean unresolved device metadata or source/sink fragments still require review.
Exit `2` means invalid configuration, a detected conflict, or an unreadable
configuration file. Run the checker on the Pi when hardware becomes available:
absent `/dev/serial/by-path` links on another host cannot establish device
identity and cannot receive a complete verdict. Even existing character nodes
do not prove role suitability or that differently named nodes belong to
different physical USB devices. Implicit DRM resources, other running owners,
and physical USB topology are not checked. Device identities can change after
inspection. This checker does not reserve resources and is not a substitute
for runtime ownership.

The reverse bridge records the opened sensor descriptor's Linux character-device
identity (`fstat().st_rdev`). Before each OLED open, the target path must identify
a different character device, even if the original sensor path has disappeared
or changed. After opening, the OLED descriptor must match the inspected target
and differ from the owned sensor. Missing paths, unavailable identity metadata,
and identity changes defer only the OLED retry. Rejected candidates are closed
without acquisition, release, or display-value commands.
Shutdown observed after GPIO/sensor reads prevents a new OLED reconnect.
Lookup and descriptor checks also observe shutdown; a candidate opened during
cancellation is closed before it becomes an owned display link or receives
protocol commands. Cleanup of established links still attempts release.
Stable `/dev/serial/by-id` or `/dev/serial/by-path` assignments remain necessary.
These checks prevent protocol writes to detected aliases; they do not make
lookup/open atomic or prevent control-line/reset side effects during serial
opening. Device numbers can be reused and do not prove physical USB roles.

The aggregate checker is an audit, not a shared startup gate. A missing camera
or OLED must remain `INCOMPLETE` because its identity cannot be verified, while
unrelated configured services can still run. Launch services independently;
do not make every service conditional on the aggregate checker returning zero.
Resolve known overlapping assignments before starting their affected owners.
Runtime failures remain local as described above, including continued reverse
sensor acquisition while the OLED is unavailable.

The existing independent launch commands remain unchanged:

```sh
python3 rpi-ahd-selector/selector.py --config rpi-ahd-selector/config.local.json
python3 rpi-oled-bridge/bridge.py \
  --reverse-config rpi-oled-bridge/reverse.local.json \
  --sensor-port /dev/serial/by-path/YOUR_SENSOR_NANO \
  --display-port /dev/serial/by-path/YOUR_DISPLAY_NANO
```

Run these in separate terminals or independently configured services. The
[reverse guide](reverse-trigger.md) and [blinker configuration reference](../README.md#blinker-trigger-mode)
describe each process's settings. Restart the affected process after editing
its configuration and rerun the combined check after changing assignments.

## Race handling and shared-resource limits

BOTH and reverse LOW use separate cancellation generations. A BOTH transition
is retained even if LEFT returns before playback polls; reverse LOW invalidates
pending acquisition/data work even if HIGH returns during a USB write. Camera
process creation and termination do not hold the reverse bridge's locks. An
in-flight launch cannot be withdrawn, but an obsolete camera process is stopped
when creation returns, before publishing it as the selected pipeline.

Reverse shutdown is checked again after each pre-write GPIO sample. OLED
distance values and ACK health are checked after that sample, so an input-read
delay cannot send a previously formatted stale value. Display fault observers
run after link cleanup; observer exceptions do not stop sensor acquisition.
These checks preserve local fault isolation without providing a hard timing
bound for Linux scheduling, device opens, or USB transport.

The camera worker stops its old process before launching a replacement. Both
the graceful and forced termination waits use `process_stop_timeout_seconds`.
If teardown still fails, the selector requests shutdown, reports device release
as unverified, and does not launch another capture. Final cleanup may retry
termination using the same bounded waits. A process reported as stopped by
software is not proof of physical capture release or a visible blank screen.

USB device paths are independent resources, but cameras and Nanos can still
share hub bandwidth, power, and host scheduling. The code does not reserve USB
bandwidth or guarantee real-time deadlines. Only the selected camera is opened;
its capture load can still delay reverse USB service. Reverse freshness and
lease checks handle delayed/missing replies conservatively. A sustained-load
test is required before choosing final timing, power, hub, and camera settings.

## Software verification

```sh
python3 -m unittest discover -s tests/integration -p 'test_*.py' -v
python3 -m unittest discover -s rpi-ahd-selector -p 'test_*.py' -v
python3 -m unittest discover -s rpi-oled-bridge -p 'test_*.py' -v
python3 -m unittest discover -s rpi-buzzer -p 'test_*.py' -v
```

The integration suite exercises interleaved BOTH/reverse transitions, reverse
LOW during a blocked camera launch, preservation of blinker OFF-gap hold,
GPIO claim failures, cooperative serial contention, partial port acquisition,
short serial replies, failed camera teardown, configuration aliases, character
device identities, missing/inaccessible paths, source/sink allowlist limits,
and optional buzzer pin reservations. It
uses synthetic GPIO, serial ports, clocks, and video processes. The component
suites cover their own reconnect, stale-data, qualification, and cleanup paths.
Failure-isolation cases exercise camera launch/capture failure alongside
reverse ranging and LOW release, missing reverse USB endpoints alongside
camera switching, an absent optional selector controller while its playback
worker runs, and locally handled buzzer backend failures alongside both modes.
Additional cases detach the stdin/stdout control transport and retarget an OLED
path during an active sensor session. The alias case verifies continued sensor
renewals, reverse LOW release, camera switching, and healthy buzzer playback.
Missing optional serial dependencies and capture child-process stream isolation
are covered by selector tests. Further cases reject OLED descriptor changes
during opening and missing identity metadata, with sensor renewals and LOW
release preserved. Command tests discard partial input across serial reconnects,
stop the current batch after incomplete replies or flush failures, and suppress
unprocessed commands when shutdown is observed after a read or between replies.
Cancellation during reply preparation suppresses that unsent reply as well.
Further software tests cancel OLED reconnects during pathname lookup, opening,
and descriptor inspection, and retain direct candidate-close failures in the
diagnostic error report.
These tests establish software boundaries, not physical immunity to shared
power, USB, or GPIO hardware failures.

No physical equipment was available for the 2026-10-14 review. GPIO electrical
behavior, sensor operation, visible OLED/HDMI output, camera capture, USB hub
contention, and response timing remain untested. The
[reverse diagnostic](reverse-diagnostics.md) and
[adapter diagnostic](../README.md#pi-side-adapter-diagnostic) provide separate
procedures for later hardware validation; they must not compete with running
owners of the same ports or capture devices.

Generated reports under root `reports/`, test output under root `test-results/`,
and root `coverage.xml` are ignored by Git, along with component diagnostic
report directories and local tuning files. Default JSON configurations, source,
tests, and authored documentation remain version-controlled.
