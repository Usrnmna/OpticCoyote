# Project wiring and connection scheme

[Documentation index](index.md) | [Project overview](../README.md)

This is the assembly-level reference for Project Optic Coyote. It covers the
implemented ultrasonic-to-OLED USB path and the independent AHD camera path
with two rear-facing exterior mirror-area cameras. Reverse control adds one
protected Pi input to gate sensor acquisition and OLED distance ownership.

An [optional Pi buzzer](pi-buzzer.md) adds one GPIO logic output for later
explicitly defined calls. The specified DIYables `DIY-BUZZER-MODULE-PASSIVE-5`
module uses **3.3 V DC** on `VCC`, common ground on `GND`, and a configurable
GPIO logic signal on `I/O`. Passive PWM and active-low polarity are the defaults;
playback remains disabled with the BCM pin unassigned. The
[buzzer reference](pi-buzzer.md) records product links, printed labels, OFF bias,
and unverified electrical behavior. Active-buzzer rhythms remain supported.
This output is separate from the sensor Nano's D8 alarm.

Use [component pinouts](component-pinouts.md) to identify board signals and chip
pins. Use [the sensor reference](nano-ultrasonic-pinout.md) for sensor setup and
[the OLED guide](oled-display.md) for firmware uploads and Pi commands.

The tables below describe connections by **printed signal label**. They are not
a verified PCB layout. The exact Nano USB-C revision, sensor revisions, OLED
breakout, camera connectors, and capture adapters have not been inspected.
Connections depending on those parts are marked conditional rather than given
an invented connector position or supply rating.

## Assembly identifiers

These identifiers label parts in this document; they are not existing PCB
reference designators.

| ID | Part | Project role |
| --- | --- | --- |
| P1 | Raspberry Pi 5, 4 GB RAM | USB host; distance bridge and independent camera selector |
| N1 | ELEGOO Nano, ATmega328P + CH340 | Polls the four ultrasonic sensors |
| M1 | TCA9548A breakout | Isolates four sensors sharing I2C address `0x57` |
| S1-S4 | RCWL-1655 or protocol-compatible AJ-SR04M modules | Rear-bumper distances, numbered left to right on the OLED |
| N2 | Second ELEGOO Nano of the same type | Receives distance packets and drives the OLED |
| O1 | 0.91-inch SSD1306 128x32 I2C OLED module | Four distance columns in decimal feet |
| C1-C2 | GreenYi AHD cameras, [ASIN B0C3R5Y7K1](https://www.amazon.com/GreenYi-Reverse-Trailer-Adjustable-Fisheye/dp/B0C3R5Y7K1) | Left and right mirror-area rear-facing views; camera identity does not establish electrical specifications or tested operation |
| V1-V2 | GRACETOP AHD-to-USB-A 2.0 adapters, ASIN B0DZ2HT7TD | Intended independent V4L2 feeds; listing model GTDE-ABV2USBC, part GTUS-AHD2USB; hardware operation unverified |
| H1 | Powered USB hub for camera interfaces | Expands Pi host ports; power/bandwidth must fit the actual devices |
| D1 | HDMI monitor | Shows the selected camera; separate from O1 |

## Whole-project text diagram

```text
Rear bumper / sensor order used on the OLED:

     S1                 S2                 S3                 S4
  far left          left-middle        rear-middle        far right
     | I2C              | I2C              | I2C              | I2C
     v                  v                  v                  v
 M1 SC0/SD0          M1 SC1/SD1          M1 SC2/SD2          M1 SC3/SD3
     +------------------+------------------+------------------+
                                 |
                         M1 TCA9548A (0x70)
                         upstream SCL / SDA
                                 |
                         N1 A5/SCL / A4/SDA
                         N1 SENSOR NANO
                         ATmega328P + CH340
                                 |
                          N1 USB-C connector
                                 |
                       USB-A <-> USB-C data cable
                                 |
                    P1 Raspberry Pi 5 (4 GB) USB-A host port
                    rpi-oled-bridge/bridge.py
                    another USB-A host port
                                 |
                       USB-A <-> USB-C data cable
                                 |
                         N2 DISPLAY NANO
                         ATmega328P + CH340
                         N2 A5/SCL / A4/SDA
                                 |
                       O1 SSD1306 I2C OLED (0x3C)
                       +-----------------------+
                       |  1     2     3     4  |
                       | 1.0   2.0   3.0   4.0 |
                       |          ft           |
                       +-----------------------+

Independent camera path on the same Pi:

 C1 LEFT mirror  ---> V1 AHD capture --USB--+
 C2 RIGHT mirror ---> V2 AHD capture --USB--+--> H1 powered USB hub
                                                       |
                                                  USB upstream
                                                       |
                                                  P1 USB-A host
                                                  camera selector
                                                       |
                                                  P1 HDMI output
                                                       |
                                                  D1 HDMI monitor
```

Each Nano remains a USB device; P1 is the host for both. Power and ground wiring
are shown separately below. Reverse control additionally requires the protected
GPIO input; the ultrasonic/OLED links use USB rather than Pi I2C. The Pi's USB-C **power input** is not the outgoing host
connection to N2. Choose the two physical USB-A ports and record their Linux
device paths as explained in [USB port identification](oled-display.md#run-the-pi-bridge-in-standalone-mode).

The distance bridge does not select a camera. The camera selector's serial
control expects JSON, whereas N1 emits tagged sensor snapshots or standalone CSV. The configured selector
GPIO inputs and serial port are currently disabled.

## Sensor branch: N1, M1, and S1-S4

```text
N1 SENSOR NANO                      M1 TCA9548A BREAKOUT
 A4 / SDA <-----------------------> SDA / upstream data
 A5 / SCL ------------------------> SCL / upstream clock
 GND ----------------------------- GND

                                   A0 ---- GND
                                   A1 ---- GND       address = 0x70
                                   A2 ---- GND
                                   /RESET -- pull-up -- M1 logic supply

                                   SD0 <---------> S1 Echo / TX / SDA (*)
                                   SC0 ----------> S1 Trig / RX / SCL (*)
                                   SD1 <---------> S2 SDA
                                   SC1 ----------> S2 SCL
                                   SD2 <---------> S3 SDA
                                   SC2 ----------> S3 SCL
                                   SD3 <---------> S4 SDA
                                   SC3 ----------> S4 SCL
                                   SD4/SC4 ... SD7/SC7: no sensor connections
```

`(*)` The exact RCWL-1655 aliases used by the project are **Echo / TX / SDA**
and **Trig / RX / SCL**. Follow the table below when a module prints its UART or
trigger/echo names. An AJ-SR04M revision must have its own confirmed I2C pin map.

| Wire | From | To | Function |
| --- | --- | --- | --- |
| N1-DATA | N1 A4 / SDA | M1 upstream SDA | I2C data |
| N1-CLOCK | N1 A5 / SCL | M1 upstream SCL | I2C clock; N1 configures 100 kHz |
| S1-DATA | M1 SD0 | S1 Echo / TX / SDA | Sensor 1 data |
| S1-CLOCK | M1 SC0 | S1 Trig / RX / SCL | Sensor 1 clock |
| S2-DATA | M1 SD1 | S2 Echo / TX / SDA | Sensor 2 data |
| S2-CLOCK | M1 SC1 | S2 Trig / RX / SCL | Sensor 2 clock |
| S3-DATA | M1 SD2 | S3 Echo / TX / SDA | Sensor 3 data |
| S3-CLOCK | M1 SC2 | S3 Trig / RX / SCL | Sensor 3 clock |
| S4-DATA | M1 SD3 | S4 Echo / TX / SDA | Sensor 4 data |
| S4-CLOCK | M1 SC3 | S4 Trig / RX / SCL | Sensor 4 clock |
| SENSOR-GND | N1 GND | M1 GND and S1-S4 GND | Shared signal reference |
| SENSOR-SUPPLY | Selected regulated peripheral rail | M1 supply input and S1-S4 VCC | Conditional on every connected module's voltage rating |

The default mapping is:

| Sensor | Mux channel | CSV distance field | OLED column |
| --- | --- | --- | --- |
| S1 | 0 | `rear_far_left_mm` | 1, leftmost |
| S2 | 1 | `rear_left_middle_mm` | 2 |
| S3 | 2 | `rear_middle_mm` | 3 |
| S4 | 3 | `rear_far_right_mm` | 4, rightmost |

All four sensors face directly rearward from the rear bumper. S1 is far left,
S2 left-middle, S3 rear-middle, and S4 far right. Verify the required
viewing orientation with one target per sensor. If cable order differs, correct
the wiring or the sensor firmware's `kMuxChannels` mapping and retain physical
slot order 1-4. A Pi display permutation alone leaves CSV zone identities
unchanged; see [sensor identities](oled-display.md#preserve-physical-sensor-identities).
Do not infer camera positions from these sensor names.

N1 enables one mux channel at a time. Keep the four downstream SDA/SCL pairs
separate. M1 address straps and reset connection follow the
[TI TCA9548A specification](https://www.ti.com/lit/ds/symlink/tca9548a.pdf).
Use existing breakout straps/pull-ups where fitted. SDA and SCL require suitable
pull-ups on the upstream and each used downstream segment; inspect installed
resistors before adding parallel ones. Pull-ups must match that segment's
voltage design.

The source expects I2C address `0x57`, trigger byte `0x01`, a conversion wait,
and a three-byte big-endian result in micrometres. RCWL-1655 I2C mode is documented
in the existing sensor reference as R7 = 100 kOhm. Do not apply that resistor
setting to an AJ-SR04M by model name alone; its revision must support the same
protocol and its own documented mode selection.

## Display branch: N2 and O1

```text
N2 DISPLAY NANO                         O1 SSD1306 128x32 I2C MODULE
 A4 / SDA <------ [level shift if needed] ------> SDA
 A5 / SCL ------- [level shift if needed] ------> SCL / SCK
 GND ------------------------------------------ GND
 Module-compatible regulated supply ------------ VCC

 USB-C <---- data cable ----> P1 USB-A
 D0/RX and D1/TX already connect to N2's onboard CH340; no external UART wires.
```

| Wire | From | To | Condition |
| --- | --- | --- | --- |
| OLED-DATA | N2 A4 | O1 SDA | Direct only with compatible I2C levels |
| OLED-CLOCK | N2 A5 | O1 SCL / SCK | Same voltage condition |
| OLED-GND | N2 GND | O1 GND | Shared reference |
| OLED-SUPPLY | Appropriate regulated supply | O1 VCC | Confirm exact breakout rating |

The Nano has 5 V logic. An OLED breakout must explicitly support both 5 V
supply and I2C signals before using direct wiring with N2 5 V. For a 3.3 V-only
module, use a suitable 3.3 V supply and a bidirectional I2C level shifter, with
pull-ups on each side to that side's supply. The display controller name and
screen dimensions do not establish breakout voltage compatibility.

O1's default address is `0x3C`; `0x3D` requires the matching firmware setting.
The four-pin display setup has no external reset wire. These settings match the
[display sketch](../optic_coyote_display/optic_coyote_display.ino) and Adafruit's
[128x32 I2C example](https://github.com/adafruit/Adafruit_SSD1306/blob/master/examples/ssd1306_128x32_i2c/ssd1306_128x32_i2c.ino).

## Power and ground scheme

```text
Pi-compatible PSU ------> P1 power input
                           |
                           +-- USB cable power/data --> N1
                           +-- USB cable power/data --> N2

Selected peripheral supply ------> M1 and S1-S4 supply inputs
Peripheral supply return --------> N1 GND + M1 GND + S1-S4 GND

Selected OLED supply ------------> O1 VCC
OLED supply return --------------> N2 GND + O1 GND

Hub-compatible PSU ------> H1 powered hub --> capture adapters as rated
Camera-compatible supply -------> C1-C2 power inputs as individually specified
Monitor-compatible supply ------> D1 power input
```

N1/N2 USB cables already carry host ground. A separately powered peripheral
branch needs its return connected to the corresponding Nano's ground for a
shared signal reference. Do not parallel a separate positive supply onto a
USB-powered Nano's 5 V rail without an intentional power-sharing design.

The existing sensor reference describes a regulated 5 V peripheral option,
conditional on the mux breakout and all sensor modules accepting that supply.
Feeding peripherals from a Nano's 5 V pin additionally requires a verified USB
power path and current budget. VIN is not a regulated 5 V output. The exact
CH340-based Nano's 3V3 current capability must not be inferred from an official
Nano with a different USB bridge.

Retain the project guidance of local 0.1 uF sensor bypass capacitors and a
10-47 uF bulk capacitor near sensor power distribution. Confirm installed
capacitance, polarity where applicable, voltage ratings, and supply stability.
Cable lengths, vehicle power conditioning, and the total installed load are
not established by firmware or these text diagrams.

## Camera and monitor connectors

| From | To | Interface / assignment |
| --- | --- | --- |
| C1 video output | V1 AHD input | Match the camera's AHD format and connector |
| C2 video output | V2 AHD input | Same condition |
| V1-V2 USB | H1 downstream USB ports | Two independent V4L2 feeds |
| H1 upstream USB | P1 USB host | Hub data connection |
| P1 HDMI output used by the selector | D1 HDMI input | Appropriate cable for the Pi's connector |

The AHD sources are the GreenYi cameras identified by
[Amazon ASIN B0C3R5Y7K1](https://www.amazon.com/GreenYi-Reverse-Trailer-Adjustable-Fisheye/dp/B0C3R5Y7K1),
including the left and right camera views. The
[camera identity reference](camera-setup.md#greenyi-camera-identity) records the
listing-verification limits. Camera revision, harness pinout, supply, and native
frame rate remain subject to confirmation; the capture adapter's MJPEG 60 fps
mode is not evidence of the camera's native exposure rate.

The selected capture adapter is the GRACETOP USB-A variant,
[Amazon ASIN B0DZ2HT7TD](https://www.amazon.com/dp/B0DZ2HT7TD?th=1), with listing
model `GTDE-ABV2USBC` and manufacturer part number `GTUS-AHD2USB`. The
[GRACETOP product page](https://www.gracetop.com/products/433t54w43) advertises
a 1.25 mm four-pin input connector with 5 V output, ground, video input, and
audio input. These are advertised signal functions, not a verified pin order
for the received board or cable. Shared listing text also names USB-C; the
installation variant is USB-A 2.0. Inspect the actual connector and PCB labels.

Do not assume a BNC connector on the adapter. Any camera-side BNC connection or
automotive harness requires a separately verified transition to the module's
video input and return. Camera revisions, harness lead order, required supply
voltage, and the adapter's 5 V output capacity remain unverified. Keep camera
power separate unless the complete supply requirements are established.
The [adapter specification and Pi verification reference](camera-setup.md#gracetop-adapter-identity-and-advertised-specifications)
distinguishes listing claims from hardware evidence and provides MJPEG 720p60
checks for P1, the Raspberry Pi 5 with 4 GB RAM.

One multi-input capture unit can replace the two logical V1-V2 interfaces only
when it exposes two independent usable feeds to the existing software. A
combined quad-view image does not meet that interface. The supplied
[camera configuration](../rpi-ahd-selector/config.json) lists `/dev/video0`
and `/dev/video2` as placeholders; identify the actual
devices before assigning camera numbers. The [camera setup](camera-setup.md#ahd-camera-selection-raspberry-pi)
describes capture requirements and stable device paths.

## Reverse trigger input

Connect the reverse-light signal through a protected automotive-voltage sensing
interface to the manually assigned Pi BCM input. The pin is intentionally
unassigned in [reverse.json](../rpi-oled-bridge/reverse.json). Confirm that the
chosen pin does not overlap active blinker, draft, or peripheral pins.
Vehicle voltage must never reach Pi GPIO; the conditioned output must be
3.3 V-compatible with a defined inactive state.

```text
Reverse-light ON voltage -> protected sensing interface -> Pi reverse GPIO
Pi USB -> N1 sensor Nano -> M1 -> S1-S4 (ranging only during active reverse lease)
Pi USB -> N2 display Nano -> O1 (distance mode during reverse; idle renderer otherwise)
```

Keep the sensor and display supplies continuous. LOW stops new ranging through
USB and releases the powered OLED for other content. Both updated Nano sketches
are required; the older sensor START/STOP protocol only controls serial output.
See [reverse setup, timing, protocol, and verification](reverse-trigger.md).
GPIO protection, vehicle wiring, stop latency, and physical idle behavior remain
subject to bench verification.

## Optional blinker trigger inputs

The Pi camera selector supports an optional two-input trigger mode, configured
in [config.json](../rpi-ahd-selector/config.json). This path is independent of
the sensor and OLED Nanos. It requires two external protected voltage-sensing
channels; those interface components and the vehicle harness have not been
selected or electrically validated.

```text
Left blinker ON voltage  --> protected sensing channel --> Pi left GPIO
Right blinker ON voltage --> protected sensing channel --> Pi right GPIO

Camera power --> camera-rated regulated supply, independent of blink pulses
AHD video   --> existing AHD capture interfaces --> Pi USB --> HDMI display
```

| Signal | Configurable default BCM pin | Physical header pin | Logical role |
| --- | --- | --- | --- |
| Conditioned left trigger | GPIO17 | 11 | Select mapped left camera |
| Conditioned right trigger | GPIO27 | 13 | Select mapped right camera |

These pins overlap the retired four-wire GPIO draft. Trigger mode requires
`gpio_pins: []`; do not run the draft listener or another GPIO owner on the
trigger pins. Confirm the selected pins are available on the installed Pi.

**Vehicle voltage must never connect directly to Pi GPIO.** Inputs are 3.3 V
tolerant; see the [Raspberry Pi voltage specifications](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#voltage-specifications).
Use an interface with suitable voltage thresholds, current limiting, transient
and reverse-voltage protection, filtering, and a defined inactive output.
An optically isolated interface can provide the signal boundary if its complete
input circuit is rated for the vehicle environment. The retired Arduino NPN
GPIO draft is not a validated automotive-voltage input circuit.

Determine nominal system voltage, maximum operating voltage, switching polarity,
PWM/diagnostic pulse behavior, and input loading limits before selecting the
interface. Reference its vehicle side to the correct lamp return according to
the vehicle wiring. For isolation, preserve the interface's intended separation;
for a nonisolated interface, establish a suitable common signal reference.
Never pull the Pi-side output up to vehicle voltage or 5 V.

`trigger_active_low: false` uses Pi pull-downs with conditioned 3.3 V HIGH active.
An inverting open-collector interface uses `trigger_active_low: true` with
Pi-side pull-ups to 3.3 V. Both channels use the same configured polarity.
Blinker ON remains logical activity regardless of physical inversion.

Keep cameras powered from their specified supply while the system is operating;
the trigger selects capture rather than repeatedly switching camera power.
Only one mapped camera capture runs at a time. BOTH and expired all-LOW inputs
stop camera capture and request generated black output. The
[trigger setup and timing reference](camera-setup.md#blinker-trigger-mode) describes
OFF-gap retention, hazard skew, GPIO fault handling, and bench verification.
Hold tuning must allow the OFF gap plus qualification of the next ON pulse and
a sampling/scheduling margin. Once an OFF timer is armed, unqualified input
chatter cannot postpone its expiry. BOTH requests software capture termination;
an operating-system launch already in progress may briefly open a device before
it can be terminated. This GPIO path is not a hardware capture interlock.

## Retired GPIO camera-warning draft

The four-wire sensor-to-camera prototype is outside the supported installation.
It must not replace the reverse-controlled sensor firmware or share GPIO pins
with the blinker service. The [historical draft](../draft-gpio-link/README.md)
retains the prototype wiring and protocol for reference only.

## Verification boundary

Signal assignments are derived from the sensor/display sketches, Pi bridge,
camera configuration, GPIO draft, and linked manufacturer references. This
documentation does not verify a physical assembly or automotive input circuit.

Before connecting power, confirm the exact board labels, ground continuity,
supply ratings, pull-ups, and address straps. Then verify each sensor's cable
and screen column independently, followed by the two USB roles and camera
device assignments. Reverse snapshots carry individual sensor ages and request
identifiers; verify stale-data rejection and inactive ranging on hardware.
Standalone CSV has no individual sensor ages, so a failed sensor can retain an
old displayed distance while others continue reporting.
