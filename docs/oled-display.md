# Rear-bumper OLED display through Raspberry Pi USB

The four rear-bumper sensors appear as **1, 2, 3, 4 from left to right** on a
0.91-inch SSD1306 **128x32 I2C** OLED. Each distance is rounded to one decimal
place in feet. For example, 305, 610, 914, and 1219 mm display as:

```text
      1       2       3       4
     1.0     2.0     3.0     4.0
                 ft
```

Values such as `10.0` and `16.4` still fit their columns. `--.-` means unavailable.
There is no scrolling or alternating between sensors. The label stays above its
fixed column; numbers never reorder themselves by distance.

## Hardware roles and files

```text
Rear sensors 1  2  3  4 (leftmost to rightmost)
             |  |  |  |
TCA9548A     0  1  2  3
                  |
                 I2C
                  |
Sensor ELEGOO Nano (ATmega328P + CH340, existing firmware)
                  |
         USB-C to USB-A data cable
                  |
Raspberry Pi USB host running rpi-oled-bridge/bridge.py
                  |
         another USB-A to USB-C data cable
                  |
Display ELEGOO Nano (same ATmega328P board type, new firmware)
                  |
          A4/SDA and A5/SCL
                  |
         SSD1306 128x32 OLED
```

Both microcontrollers plug into separate Pi USB host ports. The Pi reads one USB
serial device and writes to the other. No direct Nano-to-Nano USB connection,
Pi GPIO connection, network service, or Pi I2C connection is used by this path.
Use data-capable cables with connectors matching the actual boards.

| Component | Program | Where to adjust it |
| --- | --- | --- |
| Sensor Nano | [Existing ultrasonic sketch](../optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino) | Existing `Config` polling and sensor settings. |
| Pi | [bridge.py](../rpi-oled-bridge/bridge.py) | CLI USB paths, `--sensor-order`, `--stale-seconds`, `--boot-seconds`; timing constants at the top. |
| Display Nano | [New display sketch](../optic_coyote_display/optic_coyote_display.ino) | `Config` OLED address, landscape rotation, and timeout. |
| Display protocol | [display_protocol.h](../optic_coyote_display/display_protocol.h) | Bounded input parsing and integer conversion to tenths of a foot. |

This program consumes the existing **ultrasonic** Nano's CSV. A different optical
sensor controller would need to produce the same CSV format or have an explicit
parser added; this implementation does not guess another device's protocol.
The camera selector and draft GPIO programs retain their separate interfaces.

## Sensor order

The default bridge mapping is the order of the four distance columns, independent
of their labels or the `nearest_zone` alarm field:

| Screen position | Rear-bumper sensor | Default mux channel | Existing CSV column label |
| --- | --- | --- | --- |
| Leftmost | 1 | 0 | `front_left_mm` |
| Second | 2 | 1 | `front_right_mm` |
| Third | 3 | 2 | `rear_left_mm` |
| Rightmost | 4 | 3 | `rear_right_mm` |

The old front/rear names remain in the sensor firmware for compatibility. For
this installation all four sensors are on the rear bumper. Arrange the physical
sensors in the desired left-to-right screen order and label their cables 1-4.
Check that order from the intended viewing orientation during installation.

If existing cables run in the reverse order, pass `--sensor-order 4 3 2 1` on
the Pi. Any permutation containing 1, 2, 3, and 4 exactly once is supported.
Those numbers select CSV distance positions, not raw mux channel numbers. If
the sensor sketch's `kMuxChannels` order changes, check the mapping again.

## Connect the OLED to the display Nano

Wire with power removed. Use the pin **labels**, not a presumed physical pin
order; SSD1306 breakout layouts differ.

| Display Nano connection | OLED connection |
| --- | --- |
| A4 / SDA | SDA |
| A5 / SCL | SCL, sometimes labeled SCK on an I2C module |
| GND | GND |
| Supply appropriate for the exact breakout | VCC |

The Nano uses 5 V logic. Connect VCC to Nano 5 V and SDA/SCL directly **only if
the complete OLED breakout explicitly supports 5 V supply and I2C signals**.
The SSD1306 controller name alone does not establish this. For a 3.3 V-only
breakout, use a suitable 3.3 V supply and a bidirectional I2C level shifter with
pull-ups to the corresponding supply on each side. Keep a common ground.
Check the breakout's documentation for regulator, pull-ups, reset, and supply
requirements. Do not join the two Nanos' 5 V rails together with extra wiring.

The sketch defaults to 7-bit address **0x3C**, no separate reset pin, and normal
landscape orientation. Change `Config::kOledAddress` to `0x3D` if required by the
module's address setting. Set `kRotation` to `2` to turn the image 180 degrees.
The display Nano needs no TCA9548A because it has only one OLED on its I2C bus.

The implementation uses the [Adafruit SSD1306 library](https://github.com/adafruit/Adafruit_SSD1306)
and [Adafruit GFX](https://github.com/adafruit/Adafruit-GFX-Library).
Their [128x32 I2C example](https://github.com/adafruit/Adafruit_SSD1306/blob/master/examples/ssd1306_128x32_i2c/ssd1306_128x32_i2c.ino)
documents the dimensions and default address. That example does not establish
the electrical compatibility of an unidentified third-party breakout.

## Upload the display Nano

1. Install **Arduino AVR Boards** in Arduino IDE's Boards Manager.
2. Install **Adafruit SSD1306**, **Adafruit GFX Library**, and **Adafruit BusIO**
   through Library Manager, accepting their dependencies.
3. Open `optic_coyote_display/optic_coyote_display.ino`. Keep
   `display_protocol.h` in the same folder.
4. Select **Arduino Nano**, **ATmega328P**, and the display Nano's port. If the
   actual board uses the older bootloader, choose **ATmega328P (Old Bootloader)**.
5. Upload to the **display Nano**. Keep the ultrasonic sketch on the sensor Nano.

With Arduino CLI and the AVR core installed, run these from the repository root:

```sh
arduino-cli lib install "Adafruit SSD1306" "Adafruit GFX Library" "Adafruit BusIO"
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 optic_coyote_display
# Replace DISPLAY_PORT with the display Nano's real serial port.
arduino-cli upload --fqbn arduino:avr:nano:cpu=atmega328 --port DISPLAY_PORT optic_coyote_display
```

Use `arduino:avr:nano:cpu=atmega328old` for the old bootloader when needed.
Do not upload while the Pi bridge or Serial Monitor owns that port.

## Run the Pi bridge

Use Python 3.10 or newer and pySerial. On Raspberry Pi OS:

```sh
sudo apt update
sudo apt install python3-serial
cd ~/ProjectOpticCoyote
python3 rpi-oled-bridge/bridge.py --list-ports
ls -l /dev/serial/by-id/ /dev/serial/by-path/
```

If installing offline, provision `python3-serial` from packages matching that Pi
OS beforehand. Runtime operation does not need a network connection. The bridge
uses [pySerial's timeout and exclusive-port APIs](https://pyserial.readthedocs.io/en/stable/pyserial_api.html).

Identify the two Nanos by plugging in one at a time and noting its device path.
Prefer unique `/dev/serial/by-id/` entries when present. Some CH340 boards have
no unique serial number; then use `/dev/serial/by-path/` to bind each role to a
particular physical USB port. Keep the cables in those same ports. Do not rely
on `/dev/ttyUSB0` remaining the sensor after unplugging or rebooting. The bridge
requires explicit role paths because identical adapters cannot safely be
distinguished by vendor/product IDs alone.

Replace both example paths with the actual values, then run:

```sh
python3 rpi-oled-bridge/bridge.py \
  --sensor-port /dev/serial/by-path/YOUR_SENSOR_NANO \
  --display-port /dev/serial/by-path/YOUR_DISPLAY_NANO
```

The Linux account needs permission to open both devices, normally membership in
`dialout`. If permission is denied, run `sudo usermod -aG dialout "$USER"`, then
log out and back in. Close Serial Monitor and any other process using either
port. The camera selector must not open either of these same serial devices.

The bridge stays in the foreground. Ctrl+C or SIGTERM requests shutdown, sends
`STOP` to the sensor and unavailable values to the OLED when possible, and closes
both ports. For boot startup, place the same command and stable paths in the
Pi's existing service setup; this repository does not install or enable a system
service automatically.

To reverse the sensor wiring order or change timing:

```sh
python3 rpi-oled-bridge/bridge.py \
  --sensor-port /dev/serial/by-path/YOUR_SENSOR_NANO \
  --display-port /dev/serial/by-path/YOUR_DISPLAY_NANO \
  --sensor-order 4 3 2 1 --boot-seconds 2 --stale-seconds 2
```

## Serial contract and failure behavior

Both links use **115200 baud, 8N1**, without flow control.

- **Sensor side:** the bridge waits two seconds after opening both ports,
  discards old input, and sends `START`. It repeats the idempotent command every
  two seconds so a sensor reset can recover without restarting the bridge.
  It accepts the existing eight-column CSV, including split USB reads.
- **Display side:** complete ASCII packets have the form
  `D,305,610,914,1219\n`. The four integers are millimetres, already arranged
  left to right by the Pi. Values must be `-1` or 0 through 30000. The display
  converts millimetres to feet using exactly 304.8 mm per foot and rounds once.
- **Rate:** the Pi keeps only the latest received snapshot and sends at most
  ten packets per second. Repeated values keep the display link alive but do
  not create new sensor readings. The OLED redraws changed text at most ten
  times per second.
- **No data:** startup, never-read sensors, and explicit `-1` values display
  `--.-`. A sensor stream silent for two seconds makes the Pi send four missing
  values. The display independently clears values after two seconds without a
  valid display packet, plus its next refresh interval. Invalid packets never
  refresh that timeout or partially update the screen.
- **Reconnection:** an open/read/write error closes both ports, discards the
  session's cached values, and retries every two seconds. Partial writes are
  treated as failed sessions. Leading newlines resynchronize frame boundaries.
- **OLED connection:** a missing I2C address is retried once a second. Wire has
  a 25 ms timeout for a stuck bus. Initialization/allocation or transfer failures
  are retried while serial continues to be serviced. A disconnected or frozen
  physical OLED cannot be guaranteed to show a fault message.

**Per-sensor freshness limitation:** the existing sensor firmware retains each
sensor's latest successful reading indefinitely. CSV does not include individual
ages or identify the sensor updated by each row. If one sensor fails while others
continue reporting, that sensor's previous value can remain displayed. The Pi
timeout detects a stopped entire stream only. This implementation preserves that
sensor protocol; it does not imply four newly measured values in every packet.

## Verify before installation

Software checks from the repository root:

```sh
python3 -m unittest discover -s rpi-oled-bridge -p "test_*.py" -v
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 optic_coyote_display
g++ -std=c++11 -Wall -Wextra -Werror -I tests/display tests/display/test_display.cpp -o /tmp/optic-coyote-display-test
/tmp/optic-coyote-display-test
```

On Windows with MinGW:

```powershell
g++ -std=c++11 -Wall -Wextra -Werror -static -I tests/display tests/display/test_display.cpp -o "$env:TEMP/optic-coyote-display-test.exe"
if ($LASTEXITCODE -eq 0) { & "$env:TEMP/optic-coyote-display-test.exe" }
```

The tests protect column order, decimal rounding, partial/malformed/oversized
frames, atomic updates, stale-stream behavior, reset/header handling, short
writes, port cleanup, millis rollover, and simulated OLED recovery. Host drawing
tests record text coordinates; they do not render through the physical display.

For an OLED-only bench check, close the bridge, open the display Nano in Serial
Monitor at 115200, wait for reset, and send `D,305,610,914,1219` with a newline.
Expect `1.0 2.0 3.0 4.0` under labels 1-4. Values expire after two seconds unless
you send another packet. Send `D,-1,0,5000,30000` to check `--.- 0.0 16.4 98.4`.
Then close Serial Monitor and start the Pi bridge.

On the assembled hardware, move an object in front of each rear sensor and
confirm the matching left-to-right column. Check measured distances, sensor
reset, display reset, Pi restart, each USB unplug/replug, and removal of the whole
sensor stream. Test a single sensor failure separately with the cache limitation
above in mind. Check actual readability, orientation, power, I2C levels, and
response time in the installation. Local compilation and simulated tests do not
establish any of those physical results.
