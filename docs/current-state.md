# Current source and release status

[Documentation index](index.md) · [Project overview](../README.md)

The current release is **v0.5.2-beta** (`0.5.2~beta` in Debian metadata).
Its [release notes](release-notes-v0.5.2-beta.md) describe the updated applications,
firmware source, documentation, artifacts, and verification scope. The
[v0.5.1-beta notes](release-notes-v0.5.1-beta.md) apply only to the original builds.

## Current behavior

| Area | Current contract | Detailed reference |
| --- | --- | --- |
| Side cameras | Exactly two exterior mirror-area cameras face rearward. Default mapping is left=1, right=2; distinct swapped mappings remain supported. | [Camera setup](camera-setup.md#blinker-trigger-mode) |
| Hazards and reverse | Both-active blinker input inhibits camera capture. Qualified reverse sensing continues independently; reverse LOW releases sensing/OLED ownership. | [Combined operation](combined-triggers.md) |
| Rear sensor identities | Sensors 1–4 are far left, left-middle, rear-middle, and far right, all facing directly rearward. Firmware mux mapping preserves physical labels and packet positions. | [Sensor identities](oled-display.md#preserve-physical-sensor-identities) |
| OLED values | Fixed 9×16 glyph cells in four columns; rounded `0.0`–`9.9`, then `≥10`; `-.-` for missing, invalid, or stale measurements. | [Pixel layout](oled-display.md#fixed-pixel-layout) |
| OLED timing | Freshness is checked before drawing and transfer. Data expiring during drawing becomes `-.-`; ownership expiry selects idle. | [OLED review](oled-display.md#oled-source-review) |
| Optional buzzer | Explicit active/passive sound calls, disabled until configured, without automatic trigger bindings. | [Pi buzzer](pi-buzzer.md) |
| Historical GPIO prototype | Retained for reference; incompatible with current two-camera selection and excluded from supported operation. | [Historical guide](../draft-gpio-link/README.md) |

The OLED cap is applied after rounding to one decimal place: 3032 mm displays
`9.9`, and 3033 mm displays `≥10`. The cap changes presentation only. Raw sensor
measurements and alarm thresholds remain unchanged. The marker does not claim
that every capped raw reading is at least 3048 mm.

## Recorded software verification

The following results were recorded for the corresponding source revisions.
They are separate scopes, not one combined test count or a new hardware result.
Documentation and Git-rule counts describe their recorded review snapshots.

| Revision scope | Recorded evidence |
| --- | --- |
| v0.5.2-beta release | 304 Python tests, four firmware host harnesses, shell/systemd checks, and both default reverse-mode Nano compilations; artifact checks are recorded beside the release files |
| Two-camera implementation | 303 main Python tests, 11 historical compatibility tests, four C++ firmware harnesses, and sensor Nano compilation |
| Camera/sensor-identity review | 245 targeted Python tests and four C++ firmware harnesses; default/swapped mappings, sensor slots, and reverse/blinker coexistence |
| OLED implementation and review | 141 bridge/integration tests; both display C++ harnesses with address/undefined-behavior sanitizers; display Nano compilation |
| OLED edge cases | Every integer distance from 0 through 30000 mm, all supported output fields in four columns at rotations 0 and 2, stale/lease deadlines during drawing, cache transitions, and clock rollover |
| Documentation review | 260 local links and 34 moved-section anchors checked; 32 installation tests passed using temporary staging, without rebuilding distributions |
| Git-file maintenance | 38 generated paths excluded and 80 project paths retained; no tracked files matched ignore rules; text/binary attributes and whitespace checks passed |

The reviewed display firmware uses 19488 bytes of program storage and 700 bytes
of static RAM for `arduino:avr:nano:cpu=atmega328`. Its dynamically allocated
SSD1306 framebuffer is additional to the static RAM figure. No device was flashed.
Reproduction commands and limitations are in the [development guide](development.md),
[combined-operation guide](combined-triggers.md#software-verification), and
[OLED guide](oled-display.md#verify-before-installation).

## Distribution boundary

The v0.5.2-beta Debian package and offline installer include the current Pi
applications and maintained documentation. The accompanying source archive
contains the full project, including the Nano sketches, headers, host tests,
Git-file rules, and compiled default reverse-mode Nano firmware. Nano firmware
must be uploaded separately; Pi installation does not flash either board.

Original v0.5.1-beta and intermediate two-camera artifacts remain older snapshots.
Their hashes and test records do not describe v0.5.2-beta. Current artifact
filenames, checksum instructions, and verification details are in the
[release notes](release-notes-v0.5.2-beta.md#release-artifacts).

## Documentation organization

The main README contains the project overview, visible behavior, hardware roles,
and setup links. Sensor procedures, camera configuration, capture diagnostics,
and code/configuration references reside in dedicated guides. Internal links
point to those guides, and the [documentation index](index.md) provides the
complete navigation map. Technical procedures retain their software or hardware
validation boundaries.

## Physical validation

Pi boot behavior, GPIO voltage conditioning, camera orientation/frame delivery,
USB contention, ultrasonic accuracy/interference, physical OLED visibility, and
end-to-end timing remain subject to hardware acceptance. Host tests and compiler
results do not establish these properties.
