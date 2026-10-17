# Pi-side reverse-trigger diagnostics

[Documentation index](index.md) | [Project overview](../README.md)

[`diagnose_reverse.py`](../rpi-oled-bridge/diagnose_reverse.py) checks the reverse
control path for the **Raspberry Pi 5 with 4 GB RAM**. The report records this
project target; it does not detect the Pi model or installed RAM. Markdown and
JSON reports distinguish synthetic software checks, live GPIO/USB observations,
and physical behavior requiring separate bench measurements.

## Software-only checks

From the repository root:

```sh
python3 rpi-oled-bridge/diagnose_reverse.py
```

This default mode requires only Python's standard library. It does not import
GPIO or serial drivers, open ports, or operate connected hardware. It exercises
the production qualification, cancellation, release, and freshness code with
synthetic inputs:

- HIGH below the configured qualification interval, activation at the interval,
  LOW cancellation, and qualification invalidation on sensor reconnect.
- A GPIO read overtaken by LOW, and independent OLED release when the sensor
  write fails.
- Fresh, duplicate, wrong-session, and expired-request sensor packets; expired
  values replaced by `-1`; independent aging of one sensor while the other slots
  remain fresh; and fresh, duplicate, and expired display acknowledgements.

The parser cases use fixed synthetic timestamps and a one-second freshness
interval. The qualification case uses the loaded reverse configuration. These
checks remain enabled with Python optimization (`python3 -O`). Every hardware
and physical-behavior entry remains `NOT_TESTED` in software-only mode.

## Live GPIO and USB procedure

Use a stationary bench setup with the current reverse-mode firmware on both
Nanos. Follow the [reverse setup guide](reverse-trigger.md#installation-and-configuration)
for dependencies, USB permissions, and the protected GPIO connection. Stop the
running bridge and close serial monitors before testing. The diagnostic owns
both USB ports and starts actual ranging and distance output during the cycle.
It reads GPIO only; the input sequence must come from an external protected,
3.3 V-compatible source. Vehicle voltage must never connect directly to GPIO.

Prepare manually editable local configuration files:

```sh
cp rpi-oled-bridge/reverse.json rpi-oled-bridge/reverse.local.json
cp rpi-oled-bridge/reverse-diagnostic.json rpi-oled-bridge/reverse-diagnostic.local.json
python3 rpi-oled-bridge/bridge.py --list-ports
```

Assign an unused BCM pin to `reverse_gpio_pin` in `reverse.local.json`. Retain
the intended polarity and timing settings. Substitute the verified sensor and
display USB paths below; reversed roles or incompatible firmware cannot produce
a complete passing report.

```sh
python3 rpi-oled-bridge/diagnose_reverse.py --hardware \
  --reverse-config rpi-oled-bridge/reverse.local.json \
  --config rpi-oled-bridge/reverse-diagnostic.local.json \
  --sensor-port /dev/serial/by-path/YOUR_SENSOR_NANO \
  --display-port /dev/serial/by-path/YOUR_DISPLAY_NANO
```

The diagnostic retains firmware packet slot order 1–4, without a display
permutation. Those slots represent physical sensors only after the wiring and
`kMuxChannels` mapping have been verified. See
[sensor identity guidance](oled-display.md#preserve-physical-sensor-identities). All HIGH/LOW descriptions
below refer to normalized activity, as specified by `reverse_active_high`.

1. Start with the input LOW and keep it LOW through USB boot. Initial HIGH
   aborts the test before opening the USB ports.
   READY is printed only after the sensor and independently opened OLED have
   completed their boot intervals. Raising the input before READY aborts the
   cycle. Startup can therefore require approximately two `boot_ms` intervals.
2. Wait for the `READY` indication. Apply a HIGH pulse shorter than the configured
   qualification interval, then return to LOW. A controlled pulse source is
   preferable to a hand-operated switch; the pulse must overlap GPIO sampling
   to be observed. An unobserved pulse remains `NOT_TESTED`.
3. Apply sustained HIGH. Keep it HIGH until the script reports valid sensor
   snapshots, fresh display-controller acknowledgements, and fresh values from
   all four sensor slots in one snapshot, plus a validated four-value distance
   write, then indicates that LOW is required. Values are checked again for
   expiration before that indication. Place suitable targets within the sensors'
   supported range. Missing sensor values cannot pass the four-slot
   check merely because USB telemetry continues. Successful slots from separate
   snapshots cannot be accumulated into a four-slot PASS.
4. Return to LOW and keep it LOW through the settling and quiet-observation
   windows. The test ends automatically. Reasserting HIGH during this window
   aborts the cycle. Only one activation is permitted per run.

The report checks that acquisition writes followed qualified observed HIGH,
that no new R/K/D writes started after observed LOW, and that X writes to both
boards completed within the configured LOW response limit. A write already in
flight when LOW arrives is recorded separately from a new post-LOW write.
Each D write is checked against sensor values and their age at write start;
unavailable `-1` values remain permitted, but at least one write must contain all
four fresh distances. A run sending only blank values cannot pass. This checks
host data selection, not screen rendering. Replies received after LOW cannot
satisfy the active-session communication or sensor checks.

After the settling interval, all sensor USB bytes must stop for the entire quiet
window. Partial, oversized, malformed, and non-S traffic also prevent a
quiet-window PASS. Completion requires fresh GPIO and empty-buffer polls on
both ports at or after the end of the window. Elapsed wall-clock time alone
cannot establish completion. From READY onward, GPIO and USB polling gaps are
measured against `max_observation_gap_ms`; excessive gaps fail the continuity
check and prevent a quiet-window PASS. Missing steps and deadlines produce an
incomplete or failed result rather than a PASS.

With `reverse_high_qualify_ms: 0`, short-pulse rejection is deliberately disabled
and marked `SKIP`. Host GPIO timestamps include scheduling and callback delay;
they are not independent measurements of physical pulse width. Boundary tests
such as 99/100/101 ms require a controlled input source and external measurement.

## Editable limits

Production behavior comes from [`reverse.json`](../rpi-oled-bridge/reverse.json)
or the supplied `--reverse-config`. Test limits come from
[`reverse-diagnostic.json`](../rpi-oled-bridge/reverse-diagnostic.json) or
`--config`. Both are loaded at startup; configuration changes between the
supervisor and worker invalidate the worker report.

| Diagnostic setting | Default | Accepted range and purpose |
| --- | --- | --- |
| `hardware_timeout_seconds` | 60 | 5–600; total worker observation deadline, including USB boot |
| `cleanup_timeout_seconds` | 5 | 1–30; supervisor cleanup grace per termination stage |
| `low_release_limit_ms` | 300 | 1–10000; maximum observed LOW-to-completed-X-write delay for either board |
| `quiet_settle_ms` | 500 | 100–10000; delay after both release writes before testing telemetry silence |
| `quiet_observation_ms` | 1000 | 200–30000; full quiet window required before completion |
| `minimum_sensor_packets` | 3 | 1–1000; minimum valid tagged sensor snapshots |
| `minimum_display_acks` | 2 | 1–1000; minimum distinct fresh controller acknowledgements |
| `max_observation_gap_ms` | 50 | 1–1000; maximum gap between completed GPIO or serial-buffer polls after READY |

Unknown keys, non-integer limits, and out-of-range values are rejected. The
combined settling and quiet window must be shorter than the hardware deadline.
Allow additional time for USB boot, pulses, and acquisition. Increasing limits
changes acceptance criteria; it does not improve physical timing or reliability.
Existing local diagnostic files must add `max_observation_gap_ms` explicitly.
Choose a limit larger than the configured sampling interval and allow for USB
writes and Linux scheduling. A continuity failure is a measurement limitation,
not proof that the physical input or board malfunctioned. LOW callbacks cancel
pending audit samples; a delayed HIGH read cannot overwrite an intervening LOW.

## Reports, failures, and cleanup

Reports default to `rpi-oled-bridge/diagnostic-reports/`, independently of the
current directory. `--report-dir PATH` selects another directory. Timestamped,
uniquely suffixed `.md` and `.json` files contain the same evidence, effective
configuration, Python/platform information, USB paths, and SHA-256 hashes of
the diagnostic, bridge, and reverse-control source files. Local configuration
copies and default generated reports are ignored by Git.
The workspace-level `reports/` directory is also ignored for explicitly selected
review outputs. Other custom report destinations require an appropriate local
ignore rule; authored reports intended for version control belong elsewhere.

| Exit status | Meaning |
| --- | --- |
| `0` | All requested script checks passed, allowing the explicitly disabled short-pulse check; physical validation remains separate |
| `1` | A required check failed, was not completed, or hardware operation was interrupted |
| `2` | Invalid arguments/configuration, worker launch failure, or report-writing failure; a saved report is not guaranteed |

A software-only exit status of zero establishes no hardware evidence. In
hardware mode, unavailable drivers, GPIO setup errors, USB faults, or missing
replies produce a failed/incomplete report. Duplicate, stale, or wrong-session
replies cannot satisfy communication thresholds. The production bridge also
requires Linux character-device identities for the opened sensor and each OLED
candidate. A missing or conflicting OLED identity is reported as a display
fault while sensor acquisition continues. Simulated identity checks establish
protocol isolation only; they do not verify physical USB roles or serial-open
reset behavior. The production lifecycle may
retry the OLED independently while the sensor continues ranging. Open, poll,
read, write, reset, and close failures remain recorded in the diagnostic;
this includes direct closure of a rejected or cancelled OLED candidate before
it becomes an owned display link. Such cleanup errors prevent a complete PASS.
Internal display-session failures, including silent ACK expiry, are retained
explicitly even if a later idle reconnect supplies successful release writes.
Additional acquisition attempts cannot be combined into a passing cycle. The
audit keeps separate display ACK/request history and sensor freshness history.
Successful input-buffer resets also discard partial diagnostic frames; bytes
from different USB connections cannot be combined into an acknowledgement.
A display fault invalidates its diagnostic ACK ownership while preserving
sensor freshness history. The recorded fault still prevents a complete PASS.
An absent OLED cannot produce a complete hardware diagnostic even though the
normal reverse mode can continue sensor acquisition without it.

The hardware worker uses the production session lifecycle and attempts X on
each available port on exit, then closes acquired ports and GPIO resources. A parent watchdog
bounds a stuck worker: it requests termination, then kills and attempts to reap
the process if necessary. Parent SIGINT and SIGTERM use the same cleanup path.
Signals during process launch are deferred until the worker handle is available;
repeated signals cannot bypass cleanup. Each cleanup stage has a bounded wait,
including a final reap attempt after an interrupted output drain. Timeout/interruption output is discarded, and cleanup
remains explicitly unconfirmed. The boards' configured leases provide the
fallback when USB release is unavailable. Lease behavior still requires
physical verification; forced process termination cannot prove device release.
Cleanup time cannot complete an observation window that already expired.

## Evidence boundaries and remaining bench tests

- **Software PASS:** production Python decisions behaved correctly under
  synthetic inputs. This includes stale-data rejection, but not a disconnected
  physical sensor or stale OLED pixels.
- **Hardware-observation PASS:** the Pi observed the stated input and transport
  behavior during that run. Sensor packets establish reported readings; OLED
  controller ACKs establish protocol handling. Successful D/X writes establish
  host serial acceptance, not board execution or visible output. Quiet telemetry
  establishes observed USB silence, not acoustic cessation.
- **Physical behavior NOT_TESTED:** visible feet values and `-.-` stale markers,
  return to idle rendering, physical sensor-column order, distance accuracy,
  actual ranging cessation, electrical protection, physical pulse timing, USB
  reconnect/reset recovery, and disconnected-sensor behavior require separate
  bench measurements. Camera capture, decoding, distinct exposure rate, HDMI,
  and switching are also untested by this script; use the separate
  [adapter diagnostic and camera procedures](camera-diagnostics.md#pi-side-adapter-diagnostic)
  when equipment is available. The script does not collect operator attestations or
  promote these entries to PASS.

Use the [full reverse bench checklist](reverse-trigger.md#verification) for
these remaining cases. Confirm stale-data behavior by failing one sensor while
the others continue, observing that only its value becomes unavailable and
that recovery uses fresh data. Confirm visible idle content after LOW and each
USB/reset fault. None of these physical outcomes are inferred from host tests.

Diagnostic regression tests use simulated GPIO, USB endpoints, and time:

```sh
python3 -m unittest discover -s rpi-oled-bridge -p 'test_*.py' -v
```

They cover the production pump/session path, evidence classification, missing
observations, invalid sensor values, duplicate ACKs, in-flight LOW, post-LOW
writes, delayed release, late telemetry, partial writes, cleanup failures,
worker configuration drift, observation gaps, partial quiet-window traffic,
blank/stale distance writes, and interrupted worker launch/termination. One
test terminates and reaps a real host child process with no device access; this
establishes host process cleanup only. The tests do not exercise connected Pi,
Nano, ultrasonic, OLED, or camera hardware. Physical equipment was unavailable
for the 2026-10-14 review; no physical test result is recorded.
