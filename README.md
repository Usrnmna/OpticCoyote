# Project Optic Coyote

Project Optic Coyote provides local side-camera views and rear-obstacle distance
readouts for a vehicle. Two exterior cameras serve the left and right blind-spot
views; four rear-bumper ultrasonic sensors feed a separate OLED display.

## Main features

- **Blinker-controlled camera views:** the left signal selects the left camera,
  and the right signal selects the right camera. Both cameras sit near the side
  mirrors and face rearward along the outside of the vehicle.
- **Continuous views through blink gaps:** the selected view remains visible
  through normal signal OFF intervals. Both-active hazard input stops camera
  capture and requests a black HDMI screen.
- **Reverse-controlled rear sensing:** qualified reverse activation starts the
  four rear sensors and their OLED distance view. Reverse deactivation stops
  acquisition and returns the OLED to its idle view, currently blank.
- **Readable distance values:** four fixed columns display feet as `0.0` through
  `9.9`, `≥10` for higher rounded values, and `-.-` for unavailable readings.
  Sensor numbers and a shared `ft` label remain visible.
- **Independent operation:** reverse sensing continues during left/right camera
  selection and hazards. Camera and OLED connection faults have separate recovery
  paths.
- **Local operation:** live video and sensor processing require no cloud service
  or network connection. The supplied camera pipelines do not record video.

## Vehicle layout

Left and right refer to the vehicle facing forward. All four bumper sensors
face directly rearward, and their OLED columns remain in this physical order:

| Sensor | Rear-bumper position |
| --- | --- |
| 1 | Far left |
| 2 | Left-middle |
| 3 | Rear-middle |
| 4 | Far right |

Rear sensors indicate rear obstacles; they do not select side cameras or
establish side blind-spot clearance.

## Hardware and setup

The target assembly uses a Raspberry Pi 5 with 4 GB RAM, two AHD cameras with
compatible USB capture adapters, an HDMI monitor, and two ATmega328P Nano boards.
One Nano reads the four ultrasonic sensors; the other drives a 128×32 OLED.
The documented OS target is Raspberry Pi OS Lite 64-bit, Debian 13 Trixie.

1. Follow the [Pi setup guide](docs/rpi5-setup.md) and
   [installation package guide](docs/installation-package.md).
2. Check the [wiring and power requirements](docs/project-wiring.md), including
   protected vehicle-signal inputs. Vehicle voltage must not connect directly
   to Pi GPIO.
3. Configure [side cameras and blinkers](docs/camera-setup.md) and
   [reverse sensing](docs/reverse-trigger.md).
4. Complete the [combined-operation checks](docs/combined-triggers.md) and
   [OLED setup checks](docs/oled-display.md) before vehicle operation.

An [optional Pi buzzer](docs/pi-buzzer.md) supports explicit sound commands;
it is disabled by default and has no automatic reverse or blinker binding.

## Further documentation

The [documentation index](docs/index.md) organizes installation, operation,
diagnostics, wiring, and technical references. Detailed configuration tables,
firmware behavior, code maps, and test commands are in the
[development guide](docs/development.md).

## Source and release status

The release baseline is **v0.5.1-beta**. Current source includes later two-camera,
sensor-identity, and OLED changes; existing packages and installers have not
been rebuilt to include all of them. Consult the
[current source status](docs/current-state.md) before using an older artifact.

Software tests and firmware compilation do not establish physical camera,
sensor, electrical, or display performance. Hardware acceptance remains pending.
