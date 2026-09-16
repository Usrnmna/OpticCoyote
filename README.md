# Project Optic Coyote: Four-Sensor Ultrasonic Framework

This Arduino sketch polls four fixed-address RCWL-1655 ultrasonic sensors through a TCA9548A I2C multiplexer. It reads one sensor at a time, applies a three-reading median filter, finds the nearest object, drives an alarm output, and publishes one CSV record per complete scan.

## Required hardware

- One Arduino-compatible controller
- Four RCWL-1655 modules configured for I2C mode
- One TCA9548A I2C multiplexer at its default `0x70` address
- A regulated supply appropriate for the Arduino logic voltage
- I2C pull-up resistors if they are not already present on the TCA9548A breakout
- One `0.1 uF` bypass capacitor at each sensor, plus a bulk `10-47 uF` capacitor near the power distribution point

## Sensor configuration

Install `100 kOhm` at the RCWL-1655 `R7` position to select I2C mode. The four sensor signals are wired to separate mux channels:

| RCWL-1655 pin/function | TCA9548A connection |
| --- | --- |
| VCC | Common regulated supply |
| GND | Common ground |
| Trig / RX / SCL | `SC0`, `SC1`, `SC2`, or `SC3` |
| Echo / TX / SDA | `SD0`, `SD1`, `SD2`, or `SD3` |

The TCA9548A upstream `SCL` and `SDA` connect to the Arduino's hardware I2C pins. All grounds must be connected together. Keep all I2C pull-ups tied to the selected logic supply; do not mix 3.3 V and 5 V pull-ups.

## Build and upload

Open `optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino` in the Arduino IDE, choose the correct board and serial port, then upload it. The sketch only needs the standard `Wire` library.

The defaults suit a classic Arduino Uno/Nano:

- Serial rate: `115200`
- Alarm output: digital pin `8`, active high
- Status heartbeat: built-in LED
- TCA9548A channels: `0`, `1`, `2`, `3`
- Warning threshold: `600 mm`
- Critical threshold: `300 mm`
- Accepted sensor range: `200-5000 mm`

All of these values are grouped in the `Config` namespace near the top of the sketch.

## Serial output

The program prints a header followed by CSV records:

```text
time_ms,front_left_mm,front_right_mm,rear_left_mm,rear_right_mm,nearest_zone,nearest_mm,state
1680,742,515,1204,980,front_right,515,WARNING
2100,738,509,1198,977,front_right,509,WARNING
```

An invalid or missing sensor is reported as `-1`. Possible system states are `CLEAR`, `WARNING`, `CRITICAL`, and `NO_VALID_SENSORS`.

## Timing and control integration

The sketch uses a non-blocking state machine instead of `delay()`. A measurement is triggered with command `0x01`, read after 100 ms, and converted from the returned 24-bit micrometre value to millimetres. The mux channel is then disabled before the next sensor is selected.

One complete four-sensor scan takes about 420 ms with the conservative default timing. Application logic can run alongside the scanner by adding non-blocking work to `loop()`. For motor control, treat `CRITICAL` as an immediate stop condition and `WARNING` as a slow-down or avoidance condition after testing the thresholds on the actual platform.

## First-power-up checks

1. Power the system with the sensor heads aimed in different directions.
2. Confirm that the TCA9548A responds at `0x70`.
3. Confirm that `0x57` appears only after selecting one mux channel.
4. Watch the Serial Monitor at `115200` baud.
5. Move a broad, flat target through each zone and verify its reported direction.
6. Tune the range and warning constants for the installation.

Do not fire all four sensors simultaneously. Reflections from one transducer can be received by another and create false detections.







Used Repos - RCWL_1601_i2c:
<b><a href><https://github.com/markwal/RCWL_1601_i2c>
  <b></n>An Arduino library for communicating with a RCWL-1601 distance sensor in i2c mode.</b>
