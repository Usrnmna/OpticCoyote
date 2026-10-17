# Documentation index

[Project overview](../README.md) · [Current source and release status](current-state.md)

## Installation and operation

| Task | Guide |
| --- | --- |
| Prepare the Raspberry Pi OS, dependencies, permissions, and HDMI | [Pi 5 setup](rpi5-setup.md) |
| Install the Debian package or offline bundle; configure services | [Installation package](installation-package.md) |
| Configure side cameras, blinker inputs, manual controls, and live output | [Camera setup](camera-setup.md) |
| Configure reverse activation and sensor/display operation | [Reverse trigger](reverse-trigger.md) |
| Install the OLED and interpret its distance values | [OLED display](oled-display.md) |
| Configure sensor firmware, I2C operation, and standalone serial output | [Ultrasonic sensing](ultrasonic-sensing.md) |
| Check simultaneous reverse, blinkers, and hazards | [Combined operation](combined-triggers.md) |
| Configure explicit optional sound playback | [Pi buzzer](pi-buzzer.md) |

The supported installation uses two rearward-facing exterior mirror-area cameras
and four directly rearward-facing bumper sensors. Reverse control is the default
Nano firmware mode. Standalone examples require the explicitly selected
standalone builds; they are not interchangeable with reverse session commands.

## Hardware references

| Reference | Coverage |
| --- | --- |
| [Project wiring](project-wiring.md) | Complete signal paths, power, ground, and protected vehicle inputs |
| [Component pinouts](component-pinouts.md) | Board/chip signal mappings and unverified connector details |
| [Sensor interface](nano-ultrasonic-pinout.md) | Nano/multiplexer wiring, sensor mode, serial contract, and timing |
| [Camera identities](camera-setup.md#hardware) | Specified cameras/adapters, dated vendor claims, and verification limits |

## Diagnostics and maintenance

| Task | Guide |
| --- | --- |
| Verify capture modes, delivery rate, decoding, and diagnostic reports | [Camera diagnostics](camera-diagnostics.md) |
| Inspect reverse GPIO/USB operation and diagnostic evidence | [Reverse diagnostics](reverse-diagnostics.md) |
| Adjust configuration constants, inspect code roles, or run regression checks | [Development and adjustment](development.md) |
| Distinguish current source behavior from distribution contents | [Current source status](current-state.md) |
| Review changes and upgrade considerations after the original beta artifacts | [Unreleased source notes](release-notes-unreleased.md) |
| Inspect the original beta artifacts and their recorded verification | [v0.5.1-beta release notes](release-notes-v0.5.1-beta.md) |

## Historical reference

The [retired four-camera GPIO prototype](../draft-gpio-link/README.md) is retained
for historical inspection. Its sensor-warning camera-selection protocol is
incompatible with the supported two-camera selector. It must not replace the
reverse-controlled sensor firmware or run alongside the blinker service.

## Evidence boundaries

Source-code and test links refer to a complete repository checkout. Installed
Pi package documentation contains the guides; Nano firmware and host tests
remain separate from the installed Python services.

Configuration validation, host simulations, and firmware compilation establish
software properties only. Device identity, camera orientation, acoustic coverage,
electrical compatibility, readable physical displays, and vehicle timing require
hardware acceptance. External component claims retain their recorded dates and
citations; they are not new hardware measurements.
