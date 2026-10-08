# Controller, chip, and module pinouts

Use this reference with the [project wiring scheme](project-wiring.md).
**Board header labels, Raspberry Pi BCM numbers, physical header positions, and
chip package pin numbers are different numbering systems.** Each diagram states
which one it uses. Wire to board/module headers; chip references below help with
identification and tracing, not instructions to solder to an assembled IC.

## ELEGOO Nano N1 and N2

The project uses ATmega328P-based Nano boards with a CH340 USB-to-serial bridge.
[ELEGOO's Nano specification](https://eu.elegoo.com/en-be/products/elegoo-nano-v3-0)
confirms those chip families. USB-C is the specified project variant; connector
and power circuitry must be checked on the actual board.

### Classic Nano header arrangement

This is the classic Nano **component-side reference, USB connector at the top**,
based on the [Arduino Nano pinout](https://docs.arduino.cc/resources/pinouts/A000005-full-pinout.pdf).
Confirm the ELEGOO board's silkscreen before using the physical arrangement.
The original Arduino's USB bridge and power specifications are not a substitute
for the CH340 board's schematic.

```text
                        USB connector
                    +------------------+
             D13 ---|                  |--- D12
             3V3 ---|                  |--- D11
            AREF ---|                  |--- D10
              A0 ---|                  |--- D9
              A1 ---|      NANO        |--- D8
              A2 ---|                  |--- D7
              A3 ---|                  |--- D6
         SDA / A4 ---|                  |--- D5
         SCL / A5 ---|                  |--- D4
              A6 ---|                  |--- D3
              A7 ---|                  |--- D2
              5V ---|                  |--- GND
           RESET ---|                  |--- RESET
             GND ---|                  |--- D0 / RX
             VIN ---|                  |--- D1 / TX
                    +------------------+
```

### Header use by firmware

| Nano header | Sensor Nano N1 | Display Nano N2 |
| --- | --- | --- |
| USB connector | Pi sensor USB port; START/STOP and CSV | Pi display USB port; four-distance packets |
| A4 / SDA | M1 upstream SDA | O1 SDA, with level shifting if needed |
| A5 / SCL | M1 upstream SCL | O1 SCL, with level shifting if needed |
| GND | M1 and sensor ground | O1 ground |
| D0 / RX | Onboard USB bridge's UART output | Same onboard function |
| D1 / TX | Onboard USB bridge's UART input | Same onboard function |
| D8 | Active-high alarm logic output | Unused by display sketch |
| D13 | Onboard heartbeat LED | No application heartbeat configured |
| D2-D7, D9-D12 | Unused by normal sensor sketch | Unused by display sketch |
| A0-A3, A6-A7 | Unused by normal sensor sketch | Unused by display sketch |
| 5V | Conditional peripheral supply; check power budget | Conditional OLED supply; check breakout voltage |
| 3V3 | No connection specified | No connection specified; do not assume current capacity |
| VIN, AREF, RESET | No added connection required for this USB setup | Same |

Leave D0/D1 free of external drivers while using USB serial. D8 needs an
appropriate external driver if used for a load; the project does not specify a
siren/relay circuit. The optional camera draft uses D4-D7 instead of leaving
them unused. See [its separate scheme](project-wiring.md#optional-gpio-camera-warning-draft).

### ATmega328P signal-to-chip reference

The following physical numbers apply specifically to the **32-pin TQFP**
ATmega328P, viewed from the top. They do not apply to the 28-pin DIP package.
Check the package and pin-1 mark on the installed chip. Source:
[Microchip ATmega328P pin configuration, Figure 1-1](https://ww1.microchip.com/downloads/aemDocuments/documents/MCU08/ProductDocuments/DataSheets/Atmel-7810-Automotive-Microcontrollers-ATmega328P_Datasheet.pdf).

| Project/header signal | AVR signal | TQFP physical pin |
| --- | --- | --- |
| A4 / SDA | PC4 / SDA | 27 |
| A5 / SCL | PC5 / SCL | 28 |
| D0 / RX | PD0 / RXD | 30 |
| D1 / TX | PD1 / TXD | 31 |
| D8 alarm | PB0 | 12 |
| D13 / LED | PB5 | 17 |
| RESET | PC6 / RESET | 29 |
| Digital supply | VCC | 4, 6 |
| Analog supply | AVCC | 18 |
| Ground | GND | 3, 5, 21 |
| Analog reference | AREF | 20 |

The assembled Nano already provides its clock, reset, decoupling, and supply
connections. This selected-pin reference is not a standalone bare-MCU schematic.

### CH340 internal connection scheme

```text
Pi USB host <--> data cable <--> Nano USB connector
                                      |
                                 USB data pair
                                      |
                              +-------+-------+
                              |     CH340     |
                              | TXD output    |----> ATmega PD0 / D0 / RX
                              | RXD input     |<---- ATmega PD1 / D1 / TX
                              +---------------+
```

This shows existing onboard connectivity, not added jumper wires. The CH340
suffix/package and board reset circuit are not identified, so no numeric CH340
lead assignments or reset-control rewiring are specified. Use the actual board
schematic and matching CH340 datasheet for repair or chip-level work.

## TCA9548A M1

### Breakout signal groups

```text
                    +-------------------------+
N1 A4 <------------>| SDA     TCA9548A     SD0 |<--> S1 SDA
N1 A5 ------------->| SCL                 SC0 |----> S1 SCL
Common GND ---------| GND                 SD1 |<--> S2 SDA
Compatible supply --| VCC / VIN           SC1 |----> S2 SCL
GND ----------------| A0                  SD2 |<--> S3 SDA
GND ----------------| A1                  SC2 |----> S3 SCL
GND ----------------| A2                  SD3 |<--> S4 SDA
Pull-up to VCC -----| /RESET              SC3 |----> S4 SCL
                    |              SD4..SD7  |     unused
                    |              SC4..SC7  |     unused
                    +-------------------------+
```

This is a **logical grouping**, not a breakout's physical header order. A0-A2
LOW select `0x70`. The sensor sketch does not drive reset; keep `/RESET` HIGH
through a suitable pull-up, including an existing breakout resistor when fitted.

### Bare-chip package reference

**24-pin TSSOP (PW) / VSSOP (DGS), top view**. These numbers do **not** apply to
the VQFN (RGE) package, which has a different pin map. See
[TI Figure 4-1 and Table 4-1](https://www.ti.com/lit/ds/symlink/tca9548a.pdf).

```text
                  pin-1 mark
                 +---------+
            A0  1| o       |24 VCC
            A1  2|         |23 SDA
        /RESET  3|         |22 SCL
           SD0  4|         |21 A2
           SC0  5|         |20 SC7
           SD1  6|         |19 SD7
           SC1  7|         |18 SC6
           SD2  8|         |17 SD6
           SC2  9|         |16 SC5
           SD3 10|         |15 SD5
           SC3 11|         |14 SC4
           GND 12|         |13 SD4
                 +---------+
```

The chip supports a 1.65-5.5 V supply; a breakout's regulator or other components
can narrow usable supply choices. Do not equate a board's `VIN` label with a
bare-chip VCC rating without its schematic.

## Ultrasonic modules S1-S4

All four modules use the same functional connections on separate mux channels:

```text
          RCWL-1655 configured for I2C
       +--------------------------------+
       | VCC  <--- compatible supply    |
       | GND  ---- common sensor ground |
       | Trig / RX / SCL <--- M1 SCn    |
       | Echo / TX / SDA <--> M1 SDn    |
       |                 ultrasonic head|
       +--------------------------------+
```

This is a **signal list**, not physical connector order. The aliases are the
RCWL-1655 interface used by the [sensor sketch](../optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino).
In I2C mode these two pins carry clock and data, not a direct trigger pulse and
timed echo pulse from the Nano.

| Module position | `n` in SCn / SDn | Screen column |
| --- | --- | --- |
| S1 | 0 | 1 |
| S2 | 1 | 2 |
| S3 | 2 | 3 |
| S4 | 3 | 4 |

An AJ-SR04M is supported only when its exact revision matches the documented
I2C protocol and electrical requirements. Its connector positions and mode
selection are not established by the RCWL aliases. Use the module's labeled
I2C SDA/SCL pins after checking that revision's documentation. Do not copy a
mode-resistor change or transducer connector pinout from a different module.
The [sensor reference](nano-ultrasonic-pinout.md) records the protocol, mode
assumptions, and existing datasheet link; compatibility is not bench-proven.

## SSD1306 OLED O1

```text
       Four-wire I2C module, logical pin list
       +------------------------------------+
       | GND  -------- N2 GND               |
       | VCC  <------- module-rated supply  |
       | SCL  <------- N2 A5 / SCL (*)       |
       | SDA  <------> N2 A4 / SDA (*)       |
       |              128 x 32 pixel panel |
       +------------------------------------+
       (*) Level shift if required by the breakout.
```

Actual connector order varies. Some I2C boards print `SCK` instead of `SCL`;
confirm the board is configured for I2C rather than an SPI variant with the
same display controller. The current firmware has no CS, DC, or separate reset
wire. Address `0x3C` and no external reset pin are its defaults; see
[the OLED setup guide](oled-display.md#connect-the-oled-to-the-display-nano).

The OLED module's four header pins are not the SSD1306 bare controller's package
pins. Supply regulation, charge-pump capacitors, bus-mode straps, and panel
connections belong to the module. No bare-controller or ribbon-cable pinout is
inferred for an unidentified display assembly.

## Raspberry Pi P1

For the primary distance/OLED path, use USB-A host ports for N1 and N2; leave the
40-pin GPIO header unconnected. The camera path uses USB capture and HDMI output.
The selected Pi model determines the physical port locations.

The optional GPIO draft uses the following portion of the standard 40-pin
header. Numbers in parentheses are **physical pin positions**; GPIO names are
**BCM numbers**. Orient by the board's pin-1 marking, not this page's position
relative to the Pi's USB connectors. Unshown pins are not needed by the draft.
Reference: [Raspberry Pi GPIO documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio-and-the-40-pin-header).

```text
       Odd-numbered side          Even-numbered side
         3V3     (1)  o     o  (2)  5V       [do not use for GPIO pull-ups]
         GPIO2   (3)  o     o  (4)  5V       [do not use for GPIO pull-ups]
         GPIO3   (5)  o     o  (6)  GND      <-- common ground
         GPIO4   (7)  o     o  (8)  GPIO14
         GND     (9)  o     o (10)  GPIO15
camera 1 GPIO17  (11)  o     o (12)  GPIO18
camera 2 GPIO27  (13)  o     o (14)  GND
camera 3 GPIO22  (15)  o     o (16)  GPIO23   <-- camera 4
         3V3    (17)  o     o (18)  GPIO24
               ... remaining pins omitted ...
```

The GPIO inputs are 3.3 V signals. Use the
[four-transistor level interface](project-wiring.md#optional-gpio-camera-warning-draft)
for the draft's 5 V Arduino outputs. GPIO2/GPIO3 shown above are **not** used to
connect the project's OLED or sensor mux; both I2C buses belong to the Nanos.

## Optional transistor and unspecified connectors

| Part/interface | Pin naming to use | Detail still dependent on selected hardware |
| --- | --- | --- |
| NPN transistor in GPIO draft | B = base, C = collector, E = emitter | Numbered lead order; check actual manufacturer/package |
| Camera output | Video signal and return/shield | Camera harness connector, power pins and voltage |
| AHD capture input | AHD video input | Connector and supported video formats |
| USB | Complete data cable and board connector | Connector variant; do not hand-wire by wire color |
| HDMI | Complete compatible cable | Pi-side connector size and chosen output |

The text diagrams intentionally leave these unknown mechanical details open.
Document the actual part numbers and harness pin assignments before fabricating
custom cables. Source/configuration checks establish the logical signal scheme;
they do not establish physical assembly correctness or electrical measurements.
