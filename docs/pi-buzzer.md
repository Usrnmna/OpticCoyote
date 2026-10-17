# Optional Raspberry Pi buzzer

[Documentation index](index.md) | [Project overview](../README.md)

Current release: [v0.5.2-beta](release-notes-v0.5.2-beta.md) (Debian `0.5.2~beta`).

The Raspberry Pi 5, 4 GB RAM model can drive one optional buzzer through
`rpi-buzzer/buzzer.py`. Named finite patterns are available for later programs
to call. No reverse, blinker, distance, or BOTH-state binding is defined. The
Nano D8 alarm remains a separate firmware output.

## Specified module and evidence

The specified module is the **DIYables passive buzzer**, model
`DIY-BUZZER-MODULE-PASSIVE-5`, ASIN `B0DHGP95K4` (five-piece listing).
The [Amazon product listing](https://www.amazon.com/dp/B0DHGP95K4) identifies the
model and passive type. The [manufacturer product page](https://diyables.io/products/passive-buzzer-module)
links to that ASIN and advertises 3.3–5 V DC operation, external PWM tone control,
and Raspberry Pi compatibility. These are published specifications, not hardware
test results. The listing's 5 V title does not change the configured assembly
supply: **VCC uses 3.3 V DC**.

The [manufacturer module photograph](https://diyables.io/images/products/piezo-buzzer-module-passive-2.jpg)
shows `GND`, `I/O`, and `VCC` labels and a LOW-level-trigger PCB marking
(`低电平触发`). The default `active_high: false` is derived from this marking:
logical OFF requests physical HIGH; tone steps request PWM. Electrical polarity,
waveform quality, and acoustic output remain untested.

## Hardware and wiring boundary

The shipped `rpi-buzzer/buzzer.json` selects `hardware_type: "passive"` and
`active_high: false`. Playback remains disabled (`enabled: false`) and
`gpio_pin: null` until a free BCM pin is assigned and wiring is configured.
No physical GPIO header position is assigned to the signal.

| Module printed label | Connection |
| --- | --- |
| `VCC` | Raspberry Pi 3.3 V DC supply; physical header pin 1 or 17 |
| `GND` | Common Raspberry Pi ground |
| `I/O` | Configured BCM GPIO, used only as a 3.3 V logic control signal |

Connections refer to printed labels, not an assumed connector orientation.
The module contains a driver stage; a bare piezo load is not the specified
assembly. Supply-current margin and 3.3 V input operation require bench validation.
No 5 V supply or signal is specified for this connection.

| `hardware_type` | Output behavior | Sequence interpretation |
| --- | --- | --- |
| `active` | Steady logical ON during sound steps; OFF during pauses | Fixed-pitch rhythm; frequency and duty settings are ignored |
| `passive` | PWM during sound steps; OFF during pauses | Frequency and duty settings control the requested waveform |
| `null` | Playback cannot be enabled | Hardware selection remains incomplete |

The driver uses gpiozero `DigitalOutputDevice` for active hardware and
`PWMOutputDevice` for passive hardware, with an explicit `LGPIOFactory` and
initial logical value zero. Passive startup leaves PWM disabled. `active_high` selects the complete driver circuit's
polarity, including any inversion. See the
[gpiozero output API](https://gpiozero.readthedocs.io/en/stable/api_output.html).

For this active-low input, a circuit-level OFF bias is a pull-up to 3.3 V,
with its value selected against the module input circuit. This is needed during
boot and GPIO release; no resistor value or existing onboard bias is assumed.
Software cannot guarantee silence during power faults, kernel failure, forced
termination, or a stuck output stage. BCM and physical header numbers differ.

The chosen pin must be unused by reverse, blinker, the retired GPIO draft,
and other peripherals. Include `--buzzer-config` in the
[combined assignment check](combined-triggers.md#software-only-setup-check).
Assigned buzzer pins remain reserved even when disabled. The checker does not
claim pins or establish physical compatibility.

## Editable configuration

Copy `buzzer.json` to `buzzer.local.json` for installation tuning. The local
file is ignored by Git. Configuration is loaded once; recreate the library
owner or rerun the command after edits. Validation rejects unknown, missing,
and duplicate keys rather than applying hidden defaults.

| Setting | Shipped value | Meaning / permitted range |
| --- | --- | --- |
| `enabled` | `false` | Boolean; disabled operation imports no GPIO backend and claims no pin |
| `hardware_type` | `"passive"` | Specified DIYables module; `active` and unconfigured `null` remain supported |
| `gpio_pin` | `null` | BCM 2–27 or `null`; enabling requires a pin |
| `active_high` | `false` | LOW-level-trigger module; logical OFF drives HIGH |
| `max_sequence_ms` | `10000` | Total duration including pauses and repeats; 1–60000 ms |
| `sequences` | `single_beep`, `double_beep` | 1–64 names, starting with a lowercase letter; at most 64 lowercase letters, digits, or underscores |
| Sequence `repeat` | `1` | Integer 1–100; no infinite repetition |
| Sequence `steps` | Example sound/pause steps | 1–128 steps per pattern |
| Step `duration_ms` | `120` | Integer 1–60000; full pattern must fit `max_sequence_ms` |
| Step `sound` | `true` or `false` | Sound or silence |
| Sound `frequency_hz` | `2000` | Integer 20–10000; passive mode only |
| Sound `duty_cycle` | `0.5` | Finite number greater than zero and at most 0.5; passive mode only |

Sound steps require frequency and duty fields so the same pattern can be audited
for either hardware type. Silence steps contain only `duration_ms` and `sound`.
Examples have no assigned alert meaning. Bounds are software limits, not
verified module ratings or achievable Pi timing guarantees. An active buzzer
cannot produce arbitrary notes. The example 2000 Hz frequency is a tunable
request, not a measured or advertised resonant frequency.

## Inspection and explicit playback

These commands require only Python and do not touch GPIO:

```sh
python3 rpi-buzzer/buzzer.py --check-config
python3 rpi-buzzer/buzzer.py --config rpi-buzzer/buzzer.local.json --list
python3 -m unittest discover -s rpi-buzzer -p 'test_*.py' -v
```

The [Pi 5 (4 GB) setup guide](rpi5-setup.md) defines the recommended Raspberry
Pi OS Lite (64-bit), Debian 13 Trixie baseline and GPIO package provisioning.
After electrical review, pin assignment, configuration, and enabling on the Pi:

```sh
sudo apt install python3-gpiozero python3-lgpio
python3 rpi-buzzer/buzzer.py --config rpi-buzzer/buzzer.local.json --play double_beep
```

The playback command owns the output until the pattern finishes. Ctrl+C/SIGTERM
cancels playback and closes resources. Cancellation exits 130; configuration or
backend failures exit 2; completed playback exits 0. A zero exit code indicates
no reported backend error, not audible sound or a connected buzzer. An unplugged
load may produce no GPIO error. Hardware feedback is not implemented.

## Callable interface and concurrency

Add `rpi-buzzer` to the calling program's Python import path. Create one owner
and share it across that program's callers. Multiple processes must not compete
for the pin. No daemon, IPC endpoint, or automatic trigger subscription is installed.

```python
from buzzer import Buzzer, load_config

with Buzzer(load_config("rpi-buzzer/buzzer.local.json")) as speaker:
    speaker.play("double_beep")  # Nonblocking; replaces any existing pattern.
    speaker.wait()               # Optional; raises if the backend fails.
    speaker.stop()               # Cancels and requests silence.
```

| API | Contract |
| --- | --- |
| `load_config(path)` / `validate(config)` | Validate without hardware; return an independent configuration snapshot |
| `Buzzer(config)` | Create output owner; enabled startup requests silent output and starts one worker |
| `play(name)` | Silence and replace the old pattern; return a generation number |
| `stop()` | Invalidate playback and request silence before returning; report failures |
| `wait(timeout=None)` | Wait for global idle/cancellation; return false on timeout, raise on fault; replacements may extend the wait |
| `status()` | Return enabled/closed state, sequence, generation, and latched fault; software evidence only |
| `close()` | Cancel, release output/factory, join worker, and report faults; also invoked by context-manager exit |

Backend changes and cancellation share a lock. An old generation cannot reassert
output after `stop()` returns or silence its replacement. Step waits are
interruptible and monotonic. An in-progress backend call can delay cancellation;
Python scheduling and GPIO operations have no hard real-time bound. Duration
limits cover requested durations, not guaranteed wall-clock maximums under stalls.

Pauses, cancellation, replacement, completion, and cleanup disable PWM before
driving the inactive static level. A duty-only update can leave a waveform
generator running; the [gpiozero lgpio backend](https://gpiozero.readthedocs.io/en/stable/_modules/gpiozero/pins/lgpio.html)
explicitly stops it when frequency is set to `None`. An OFF write is still
attempted if stopping PWM fails, and the failure is reported. Resource release
returns the pin to input, so software OFF does not replace the external bias.
Glitch-free transitions are not established by host tests.

If both PWM cancellation and the inactive-level write fail, the error retains
both causes. Cleanup attempts silence, device release, and factory release even
when an earlier operation fails; normal cleanup failures are reported together.
A reported failure does not establish a silent physical output. The lgpio
[PWM implementation](https://github.com/joan2937/lg/blob/master/lgGpio.c) cancels
the active PWM record under its transmit lock; the subsequent static write is
therefore distinct from a queued duty update. This is source-derived behavior,
not a measured electrical cancellation deadline.

Faults latch until the owner is closed and recreated. Silence and cleanup are
attempted after failures. `play`, `stop`, `wait`, and `close` report faults.
Future optional-sound integrations must catch failures at that feature boundary
so unrelated processing continues. For example:

```python
speaker = None
try:
    speaker = Buzzer(load_config("rpi-buzzer/buzzer.local.json"))
except (OSError, ValueError, RuntimeError, ImportError) as error:
    logger.error("Optional buzzer unavailable: %s", error)

# Inside a future explicitly defined trigger handler:
if speaker is not None:
    try:
        speaker.play("single_beep")
    except (OSError, ValueError, RuntimeError) as error:
        logger.error("Optional buzzer playback failed: %s", error)

# Unrelated work continues independently. On application shutdown:
if speaker is not None:
    try:
        speaker.close()
    except (OSError, RuntimeError) as error:
        logger.error("Optional buzzer cleanup failed: %s", error)
```

The camera and reverse processes do not import or depend on this optional
module. The library installs no signal handlers; its CLI installs and restores
them. A caught exception is not successful audible-warning evidence.

## Verification boundary

Host tests cover backend selection, configuration limits, finite playback,
replacement, cancellation during backend calls, stale-generation prevention,
fault latching, and cleanup. Fake GPIO establishes software behavior only.
No electrical compatibility, physical fault detection, GPIO waveform, sound
level, frequency accuracy, or buzzer operation has been tested. Tests also model
deferred PWM duty updates and verify explicit PWM cancellation before static OFF
for either polarity. The specified passive, active-low defaults are source-derived;
the pin remains unassigned and playback disabled.
Regression coverage includes simultaneous PWM-stop and inactive-level-write
failures and failures at each cleanup stage, so the initiating error cannot be
hidden by a later release error.
