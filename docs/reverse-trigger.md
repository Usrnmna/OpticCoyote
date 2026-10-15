# Reverse-triggered ranging and OLED ownership

The Raspberry Pi 5 with 4 GB RAM reads one protected reverse-light input and
controls the existing sensor Nano and OLED Nano through their separate USB
ports. Both supplied Nano builds default to reverse control: sensors boot idle,
the distance alarm is off, and the powered OLED shows a blank idle view.

| Observed input | Sensor operation | OLED ownership |
| --- | --- | --- |
| LOW | No new ranging | Idle renderer; blank until other content is implemented |
| HIGH shorter than the qualification interval | No ranging | Idle renderer |
| HIGH continuously for at least 100 ms by default | Start a fresh acquisition session | Reverse-distance renderer |
| Continued HIGH with healthy links | Continue ranging without a duration limit | Fresh feet values, sensors 1–4 left to right |
| Qualified HIGH with OLED USB/ACK failure | Continue ranging and renewing the sensor lease | Release/retry only the OLED link; resume with fresh display ownership |
| LOW after activation | Cancel acquisition and pending data | Release reverse ownership |
| GPIO or sensor-link/lease failure | Stop directly or through the sensor lease | Release directly or through the display lease |

LOW has no debounce or blinker-style hold. An observed LOW cancels pending HIGH
qualification. Every new sensor activation, including sensor reconnect while
HIGH, must qualify again. OLED reconnection does not restart qualification or
sensor acquisition. Qualification starts from the completion of a HIGH input read;
a delayed read cannot count time spent waiting as observed HIGH. LOW takes
priority when observed at the qualification deadline. The camera selector and blinker functions retain their own
interfaces and GPIO ownership; this feature adds no camera selection behavior.

## Input connection

For concurrent blinker operation, use the
[combined-trigger setup check](combined-triggers.md) to inspect GPIO and device
assignments. BOTH inhibits cameras only; it does not release the reverse OLED
session. Reverse LOW releases the sensor/OLED session without cancelling a
blinker OFF-gap hold.

```text
Reverse-light ON voltage -> protected sensing interface -> selected Pi GPIO
Pi USB -> sensor Nano -> TCA9548A -> four ultrasonic sensors
Pi USB -> display Nano -> SSD1306 OLED
```

Vehicle voltage must not connect directly to a Pi GPIO. Use a protected
automotive-voltage sensing interface with a defined inactive state, appropriate
thresholds, transient/reverse-voltage protection, and a 3.3 V-compatible output.
The Pi GPIO electrical reference specifies [3.3 V inputs](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#voltage-specifications).
Interface ratings, vehicle switching polarity/PWM, reference grounding or
isolation, and actual electrical operation require bench validation.

The configuration deliberately leaves the BCM pin unassigned. Select an unused
pin and check its physical header position. Avoid conflicts with the blinker
defaults GPIO17/27, the optional camera draft GPIO17/27/22/23, or any other active
peripheral. `reverse_active_high: true` uses a pull-down and HIGH activation;
`false` supports an inverting interface with a pull-up and LOW activation.
An open input must resolve to the inactive state in the completed interface.

Sensors, both Nanos, and the OLED remain continuously powered. Inactive mode
stops ranging commands; it does not switch power. A pulse already transmitted
cannot be recalled. Its pending result is discarded and the conversion/cooldown
guard prevents an immediate conflicting retrigger.

## Installation and configuration

Upload **both updated Nano sketches** before enabling this mode. Older sensor
firmware ranges continuously and cannot be stopped by the new USB commands.
Earlier reverse display firmware using two-field K/A messages is incompatible
with the request-tagged acknowledgement protocol; update both firmware and bridge
together. Untagged or expired acknowledgements do not establish a healthy link.
The current [sensor header](../optic_coyote_ultrasonic/reverse_config.h) and
[display header](../optic_coyote_display/reverse_config.h) default
`OPTIC_COYOTE_STANDALONE` to `0`; retain that setting for reverse control.
Existing sensor, OLED wiring, and library requirements remain in the
[OLED guide](oled-display.md).

```sh
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 optic_coyote_ultrasonic
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 optic_coyote_display
```

Compile does not upload. Use each board's verified port when uploading. Close
serial monitors and bridge processes before uploading or starting the bridge.

On the Pi:

```sh
sudo apt install python3-serial python3-gpiozero python3-lgpio
cd ~/ProjectOpticCoyote
cp rpi-oled-bridge/reverse.json rpi-oled-bridge/reverse.local.json
```

Edit `reverse_gpio_pin` in the copy, then identify both USB devices using the
existing `bridge.py --list-ports` command. The account needs `gpio` and `dialout`
access. Stable serial paths are preferable to changing `/dev/ttyUSB*` numbers.

```sh
python3 rpi-oled-bridge/bridge.py \
  --reverse-config rpi-oled-bridge/reverse.local.json --check-config
python3 rpi-oled-bridge/bridge.py \
  --reverse-config rpi-oled-bridge/reverse.local.json \
  --sensor-port /dev/serial/by-path/YOUR_SENSOR_NANO \
  --display-port /dev/serial/by-path/YOUR_DISPLAY_NANO
```

`--check-config` needs no GPIO/USB dependencies and permits a null pin for
inspection. Actual operation requires an assigned pin. The JSON is loaded at
startup; restart the bridge after editing. `reverse.local.json` is ignored by
Git. `--sensor-order` remains supported; default order is `1 2 3 4`.

| JSON setting | Default | Purpose |
| --- | --- | --- |
| `reverse_gpio_pin` | `null` | Manually assigned BCM pin, 2–27; availability must be checked |
| `reverse_active_high` | `true` | Normalized activity polarity |
| `reverse_high_qualify_ms` | `100` | Required continuous observed activity, 0–5000 ms |
| `reverse_low_qualify_ms` | `0` | Immediate observed deactivation; only zero is supported |
| `reverse_sample_ms` | `5` | Main-loop sampling interval, 1–20 ms; GPIO edge callbacks also invalidate pending work |
| `sensor_keepalive_ms` | `250` | Renewal interval for both Nano leases |
| `sensor_lease_ms` | `1500` | Lease duration sent to both Nanos, 200–10000 ms |
| `ack_timeout_ms` | `1000` | Maximum absence of valid sensor telemetry or display acknowledgement; each link has independent tracking |
| `distance_stale_ms` | `1500` | Maximum per-sensor age accepted for display |
| `display_refresh_ms` | `100` | Minimum interval between distance packets |
| `usb_write_timeout_ms` | `100` | Bound per USB write; reads are nonblocking |
| `boot_ms` | `2000` | Nano reset/bootloader settling after each port opens; OLED settling uses a deadline without suspending sensor work |
| `reconnect_ms` | `2000` | Retry delay after the affected link fails; OLED retries do not restart the sensor link |
| `idle_display_mode` | `blank` | Current idle renderer; future content has a separate rendering hook |

The loader rejects duplicate/unknown keys and invalid types/ranges. It requires room for
two write timeouts plus sampling between keepalive, acknowledgement, and lease
deadlines. Reverse timing uses this JSON; legacy `--boot-seconds` and
`--stale-seconds` apply only to standalone forwarding.

Firmware settings are manually editable in the two `reverse_config.h` files.
The sensor reports every 100 ms and invalidates individual samples after 1500 ms
by default. Both boards accept leases of 200–10000 ms. Supported sensor Wire
operations use a 25000 us timeout. The display sketch's `Config` retains its
2000 ms data timeout, 100 ms screen refresh, and I2C recovery settings. Rebuild
and upload after firmware tuning; keep accepted lease bounds and freshness
settings consistent with the Pi configuration.

## Session protocol and stale-data protection

Both USB links use 115200 baud, 8N1. One Pi process owns both ports; additional
display functions must use the same ownership path rather than competing serial
writers. Commands use LF, with CRLF also accepted.
Runtime path checks reject sensor/display aliases, including distinct character
nodes with the same device ID; physical port roles still require verification.

| Packet | Direction and meaning |
| --- | --- |
| `R,token,lease_ms` | Pi to either Nano: acquire a fresh session; token is nonzero uint32 decimal |
| `K,token,request_id` | Pi to either Nano: renew the matching active session with a new, increasing nonzero uint32 request ID |
| `X` | Pi to either Nano: stop/release and invalidate cached data |
| `S,token,request_id,elapsed_ms,mm1,age1,mm2,age2,mm3,age3,mm4,age4` | Sensor to Pi: snapshot with the latest accepted request ID, session elapsed time and individual sample ages |
| `D,token,mm1,mm2,mm3,mm4` | Pi to display: values for the matching active session only |
| `A,token,request_id` | Display to Pi: acknowledgement of acquisition ID zero or the latest accepted renewal ID |

Repeated R for the active token does not reset data or renew its lease. K and D
cannot reactivate an expired or released session. The last retired token cannot
reacquire ownership. This protocol assumes ordered USB serial and a single
writer. It is a local control protocol, not authenticated messaging.
Acquisition starts with request ID zero independently on each board. Each link
increments its own renewal ID; duplicate/backward IDs cannot renew either lease. Repeated active R
acknowledges the display's latest accepted ID without renewing ownership.
Sensor sequence exhaustion causes a new qualified sensor session. Display
sequence exhaustion reconnects only that link. Neither sequence wraps within
an active session.

Each activation receives a fresh random 32-bit token. New acquisition clears
sensor filters/caches, bridge state and input framing, and display values.
The initial display acquisition may share the current sensor token; an OLED
reconnection during that acquisition receives a new display token and separate
ACK/request history. The continuing sensor session and its sample ages are
preserved. A new display ACK is required before any distance packet is sent;
only current sensor values still within `distance_stale_ms` are eligible.
Old-token data is discarded. Sensor failures mark that sensor unavailable;
unrelated working sensors cannot keep its old number fresh. Missing readings
are represented as `-1`, displayed as `--.-`, never as a fabricated zero.
In reverse mode, a recovery after `kStaleMs` without a successful reading also
clears the expired median-filter history before updating the alarm. A fresh
clear reading cannot reassert an alarm from pre-failure values. Standalone mode
retains its previous filtering behavior.

Each sensor snapshot freezes the latest accepted request ID with its data.
The bridge rejects unknown request IDs and reports whose corresponding request
was sent at least `ack_timeout_ms` ago. A newer request cannot make an older
queued snapshot fresh. Per-sensor measurement time is bounded conservatively
by the local request-send time minus the reported sample age. This includes
delivery delay and may age a value early by the request-to-snapshot interval.
The Pi and Nano clocks do not need to remain synchronized over a long session.
Duplicate/backwards elapsed timestamps and malformed frames do not refresh
liveness. Elapsed milliseconds are unwrapped across uint32 rollover. No old
snapshots are queued for later OLED playback.

Display acknowledgements must identify a recently issued request that has not
already been acknowledged. Duplicate, backward, unknown, or expired ACKs cannot
refresh liveness. A link that has already reached its acknowledgement deadline
is closed even if a queued reply arrives during input processing.

Only polling starts HIGH qualification. The LOW callback invalidates locked
input state, including brief LOW pulses missed by polling. A read overtaken by
cancellation is discarded; its older HIGH result cannot replace the LOW.
Serial writes occur outside the lock and read GPIO again before and after each
write, in addition to checking activation/generation. LOW
invalidates pending R/K/D work, including LOW followed quickly by HIGH during a
write. Already issued USB bytes cannot be withdrawn; X follows them in order.
Shutdown is rechecked after the pre-write GPIO read, so a stop observed during
that read cancels the unsent command. Distance packets are formatted only after
this cancellation check, with a new sample-age and display-ACK deadline check.
A delayed input read cannot send values selected before they became stale or
renew the apparent health of an expired display acknowledgement. Scheduling
and transport delay after the final check remain outside the freshness bound.

## Faults, idle rendering, and response limits

LOW normally sends X to both boards. Release is attempted on both links even if
one write fails. Ctrl+C/SIGTERM and GPIO read errors also attempt release. USB
errors or expired acknowledgements on the sensor link end acquisition, release
the OLED, and retry after the configured delay; an asserted input must qualify
again with a fresh sensor token after reopening. An absent OLED, display
open/read/write failure, or expired display ACK releases/closes only the OLED
link. Sensor acquisition continues while HIGH remains qualified. OLED retries
use `reconnect_ms` and `boot_ms` without a blocking boot sleep. Reconnection
while LOW cannot acquire reverse display ownership. Display cleanup failures
are logged; the display lease remains the fallback for an unreachable board.
An optional display-fault observer is notified after cleanup and retry
scheduling. An exception in that observer is logged without interrupting
sensor acquisition or preventing display release.
A GPIO setup/read failure ends the bridge rather than silently assuming reverse.

Firmware lease expiry runs before command acceptance and cannot be undone by a
late keepalive. A lost Pi process or sensor USB connection therefore stops
acquisition; a lost OLED USB connection releases display ownership while the
sensor lease continues to be renewed. Expiry does not depend on Python cleanup and is
limited by firmware scheduling and bounded I2C operations; a frozen board or
unsupported Wire implementation cannot provide a physical timing guarantee.

Leaving reverse selects `renderIdle(now)` in the display sketch. It currently
clears the screen once and keeps it powered. Future non-reverse content can be
implemented there without changing distance ownership. `renderReverseDistance`
alone renders the four feet values. Reverse ownership changes immediately in
firmware; visible screen changes occur on the next refresh, normally within
100 ms plus transfer time. A display ACK confirms protocol handling, not that a
physical OLED is connected or legible.

Qualification and LOW handling are based on observed GPIO state. Linux
scheduling, input conditioning, USB transport, and firmware execution add delay.
A 100 ms setting is not a hardware pulse-width discriminator or a real-time
stop interlock. No sensor or display is power-cycled. Bench measurements must
establish actual response time and electrical behavior.

## Verification

The [Pi-side reverse diagnostic](reverse-diagnostics.md) runs software-only
checks by default. Its explicit hardware mode observes a controlled GPIO cycle
through the production bridge and writes separate software, GPIO/USB, and
unverified physical-behavior sections. Diagnostic timing and reply thresholds
are editable in `rpi-oled-bridge/reverse-diagnostic.json`.

```sh
python3 -m unittest discover -s rpi-oled-bridge -p 'test_*.py' -v
g++ -std=c++11 -Wall -Wextra -Werror -I tests/nano tests/nano/test_reverse.cpp -o /tmp/optic-coyote-reverse-test
/tmp/optic-coyote-reverse-test
g++ -std=c++11 -Wall -Wextra -Werror -I tests/display tests/display/test_reverse_display.cpp -o /tmp/optic-coyote-reverse-display-test
/tmp/optic-coyote-reverse-display-test
```

The existing standalone host suites remain available; they explicitly select
standalone mode. Reverse tests cover HIGH qualification, LOW during USB work,
stale/duplicate/session-mismatched data, per-sensor ages, malformed packets,
lease expiry and rollover, partial transfers, acquisition cancellation,
request/echo deadlines, clock-rate mismatch, acknowledgement faults, OLED
release, and recovery. Regressions also exercise delayed GPIO reads, a LOW
callback overtaking a read, LOW with delayed callback delivery, duplicate/late
display ACKs, USB failure during renewal followed by HIGH or LOW on reconnect,
OLED open/read/write/ACK failures during continued ranging, LOW during OLED
reopen/boot/acquisition, independent display renewal tracking, stale values
and old ACKs after display reconnection, staleness/ACK expiry during the
pre-write GPIO check, shutdown during that check, and fault-observer isolation,
and stale alarm-filter recovery. These are software tests.

Bench verification must include 99/100/101 ms input pulses, startup while HIGH,
LOW during qualification/conversion/USB writes, repeated reverse engagements,
long HIGH, each USB unplug, each Nano reset, Pi termination, single sensor
failure, and OLED disconnection. Confirm that inactive mode emits no new ranging
commands and displays no distance values, that fresh feet values occupy the
correct physical columns, and that the idle renderer remains available.

For an explicitly ungated standalone installation, set
`OPTIC_COYOTE_STANDALONE` to `1` in both headers, rebuild/upload both sketches,
and run the bridge without `--reverse-config`. This restores continuous ranging
and the previous START/STOP CSV and untagged D display protocol. It does not
provide reverse gating and must not be mixed with a reverse-mode bridge.
