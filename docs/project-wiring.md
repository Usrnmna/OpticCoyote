# Project wiring and connection scheme

This is the assembly-level reference for Project Optic Coyote. It covers the
implemented ultrasonic-to-OLED USB path, the independent AHD camera path, and
the separately maintained GPIO camera-warning draft.

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
| P1 | Raspberry Pi 4 or 5 | USB host; distance bridge and independent camera selector |
| N1 | ELEGOO Nano, ATmega328P + CH340 | Polls the four ultrasonic sensors |
| M1 | TCA9548A breakout | Isolates four sensors sharing I2C address `0x57` |
| S1-S4 | RCWL-1655 or protocol-compatible AJ-SR04M modules | Rear-bumper distances, numbered left to right on the OLED |
| N2 | Second ELEGOO Nano of the same type | Receives distance packets and drives the OLED |
| O1 | 0.91-inch SSD1306 128x32 I2C OLED module | Four distance columns in decimal feet |
| C1-C4 | AHD cameras | Four independently selectable video inputs |
| V1-V4 | AHD-capable USB capture interfaces | Supply four Linux V4L2 camera streams |
| H1 | Powered USB hub for camera interfaces | Expands Pi host ports; power/bandwidth must fit the actual devices |
| D1 | HDMI monitor | Shows the selected camera; separate from O1 |

## Whole-project text diagram

```text
Rear bumper / sensor order used on the OLED:

     S1                 S2                 S3                 S4
  leftmost          second slot        third slot         rightmost
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
                    P1 Raspberry Pi USB-A host port
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

 C1 AHD OUT ---> V1 AHD capture --USB--+
 C2 AHD OUT ---> V2 AHD capture --USB--+
 C3 AHD OUT ---> V3 AHD capture --USB--+--> H1 powered USB hub
 C4 AHD OUT ---> V4 AHD capture --USB--+            |
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
are shown separately below. No Pi GPIO or Pi I2C wires are required for the
ultrasonic/OLED path. The Pi's USB-C **power input** is not the outgoing host
connection to N2. Choose the two physical USB-A ports and record their Linux
device paths as explained in [USB port identification](oled-display.md#run-the-pi-bridge).

The distance bridge does not select a camera. The camera selector's serial
control expects JSON, whereas N1 emits distance CSV. The configured selector
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
| S1 | 0 | `front_left_mm` | 1, leftmost |
| S2 | 1 | `front_right_mm` | 2 |
| S3 | 2 | `rear_left_mm` | 3 |
| S4 | 3 | `rear_right_mm` | 4, rightmost |

All four sensors are on the rear bumper for this installation. The CSV names
are legacy labels, not front-bumper placement instructions. Verify the desired
viewing orientation with one target per sensor; adjust `--sensor-order` on the
Pi if cable order differs. Do not infer camera positions from these sensor names.

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
Camera-compatible supply -------> C1-C4 power inputs as individually specified
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
| C3 video output | V3 AHD input | Same condition |
| C4 video output | V4 AHD input | Same condition |
| V1-V4 USB | H1 downstream USB ports | Four independent V4L2 feeds |
| H1 upstream USB | P1 USB host | Hub data connection |
| P1 HDMI output used by the selector | D1 HDMI input | Appropriate cable for the Pi's connector |

If the selected adapters use standard BNC coax video, the center contact is the
video signal and the outer contact is its shield/return. This does not identify
the pins of an unknown four-pin automotive camera connector, camera power plug,
or combined power/video harness. Obtain the selected camera/adapter pinout
before terminating those cables; no specific models are established here.

One multi-input capture unit can replace the four logical V1-V4 interfaces only
when it exposes four independent usable feeds to the existing software. A
combined quad-view image does not meet that interface. The supplied
[camera configuration](../rpi-ahd-selector/config.json) lists `/dev/video0`,
`/dev/video2`, `/dev/video4`, and `/dev/video6` as placeholders; identify the actual
devices before assigning camera numbers. The [camera setup](../README.md#ahd-camera-selection-raspberry-pi)
describes capture requirements and stable device paths.

## Optional GPIO camera-warning draft

This section describes the separate
[draft sketch](../draft-gpio-link/arduino_camera_warning/arduino_camera_warning.ino)
and [Pi warning receiver](../draft-gpio-link/warning_receiver.py). It is not
enabled by the normal sensor or display sketch. Substituting the draft changes
the sensor firmware and its serial behavior; do not treat it as a simultaneous
feature of N1's normal USB/OLED setup.

For each of the four channels, the existing draft uses this circuit:

```text
Arduino Dn --- 10 kOhm ---+---- B   NPN transistor
                        |     C --------+------- Pi GPIO input
                     100 kOhm           |
                        |             10 kOhm
Common GND -------------+---- E         |
                                    Pi 3V3

Arduino GND ----------------------- Pi GND (physical pin 6, for example)
```

`B`, `C`, and `E` are transistor functions, not numbered package leads. Match the
actual transistor datasheet. Arduino HIGH turns the transistor on and pulls the
Pi input LOW. The collector pull-up goes to Pi **3.3 V**, never Arduino 5 V.
[Raspberry Pi GPIO voltage reference](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#voltage-specifications).

| Camera selection | Draft Arduino pin | Pi BCM GPIO | Pi physical header pin |
| --- | --- | --- | --- |
| 1 | D4 | GPIO17 | 11 |
| 2 | D5 | GPIO27 | 13 |
| 3 | D6 | GPIO22 | 15 |
| 4 | D7 | GPIO23 | 16 |

The receiver defaults to active-low. The four channels are held selection
signals, not I2C, distance values, or a binary-encoded number. See the
[draft instructions](../README.md#draft-arduino-to-pi-gpio-connection) for
receiver setup and its distinct limitations. A direct trigger/echo sensor
alternative mentioned in the older sensor document remains a proposal and is
not part of the implemented wiring shown here.

## Verification boundary

I checked the signal assignments against the current sensor/display sketches,
Pi bridge, camera configuration, GPIO draft, and the manufacturer references
linked in these documents. This work does not verify a physical assembly.

Before connecting power, confirm the exact board labels, ground continuity,
supply ratings, pull-ups, and address straps. Then verify each sensor's cable
and screen column independently, followed by the two USB roles and camera
device assignments. N1's cached CSV has no individual sensor ages; a failed
sensor can retain an old displayed distance while others continue reporting.
