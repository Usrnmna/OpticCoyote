# Raspberry Pi 5 operating system and setup

## Recommended operating system

**Raspberry Pi OS Lite (64-bit), Debian 13 Trixie**, is the recommended
operating system for the **Raspberry Pi 5 with 4 GB RAM**. Select the Lite
edition without a desktop environment from the
[official OS downloads](https://www.raspberrypi.com/software/operating-systems/).

The camera selector uses Linux V4L2 capture and GStreamer's `kmssink` for direct
HDMI output. A desktop compositor is unnecessary and can compete for display
ownership. The reverse/OLED bridge uses USB serial and GPIO Zero with `lgpio`.
These components operate locally after their dependencies are installed.
Lite still supports camera video on the HDMI monitor; it does not require a
graphical desktop for this output.

This is a recommended deployment baseline, not a completed Trixie hardware
qualification. Capture performance, HDMI behavior, GPIO timing, and simultaneous
USB operation require validation on the assembled system.

## 1. Prepare and install the OS

1. Prepare a microSD card, a keyboard, and a 720p60-capable HDMI monitor with a
   micro-HDMI cable. A 32 GB card is a practical project recommendation for
   packages and diagnostic reports. Provide Pi 5-compatible power and adequate
   cooling; use the project's powered USB hub for the capture interfaces.
   Follow the [hardware wiring reference](project-wiring.md) for separate
   camera supplies and protected GPIO interfaces.
2. Open [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on a setup
   computer. Select Raspberry Pi 5 and **Raspberry Pi OS Lite (64-bit)**,
   confirming **Trixie / Debian 13** in the image description.
3. Select the intended microSD card. Writing the image erases that card.
   Configure a hostname, a non-root login account, locale, and time zone.
   Configure networking for package installation if available; enable SSH
   only when remote administration is needed.
4. Write and verify the image, eject the card, and insert it into the Pi.
   Connect the monitor to the port marked **HDMI0**, attach the keyboard,
   and apply power. Log in with the configured account.

The official [installation guide](https://www.raspberrypi.com/documentation/computers/getting-started.html)
provides the current Imager and hardware setup procedure.

## 2. Install dependencies and permissions

The [Debian package and offline bundle](installation-package.md) provide the
application installation path, dependencies, CLI commands, and separate services.
After installing the OS, that procedure can replace the manual dependency and
source-copy steps below. Retain the device configuration and hardware acceptance
checks; package installation alone does not complete them. Successful
`sudo optic-coyote-setup` enables both camera and reverse services for boot;
configuration failure leaves both disabled. Setup does not start services
immediately. The installed configuration resides in `/etc/project-optic-coyote`;
the source-copy commands below use separate local files and are an alternative
workflow. Stop installed services before running foreground hardware commands.

Run the following on the Pi while package repositories are reachable:

```sh
sudo apt update
sudo apt full-upgrade
sudo apt install python3 gstreamer1.0-tools gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav \
  v4l-utils libdrm-tests python3-gpiozero python3-lgpio python3-serial \
  python3-gi gir1.2-gstreamer-1.0
sudo usermod -aG video,render,gpio,dialout "$USER"
sudo reboot
```

The GI packages support the adapter diagnostic. Group membership grants the
login account access to video/render devices, GPIO, and serial devices. Reboot
before continuing. These commands use distribution packages with system
`python3`; a Python virtual environment is not required.

For an entirely offline installation, prepare an image with these packages
already installed, or supply their complete dependencies for the same Trixie
arm64 release. Runtime operation does not require networking. Package updates
and diagnostic downloads are separate provisioning activities.

Confirm the installed baseline and package availability:

```sh
cat /etc/os-release
dpkg --print-architecture
uname -r
id -nG
python3 -c "import serial, gpiozero, lgpio, gi"
gst-inspect-1.0 v4l2src
gst-inspect-1.0 jpegdec
gst-inspect-1.0 kmssink
```

Expect `VERSION_CODENAME=trixie` and architecture `arm64`. Record the kernel
version with hardware test results. Imports and plugin discovery establish
installation only; they do not exercise the connected equipment.

## 3. Copy the complete project and configure HDMI

Copy the complete repository to `~/ProjectOpticCoyote` using removable storage
or another available transfer method. Retain its directory structure: the
combined setup checker needs the camera, OLED bridge, and supporting modules.
Component firmware must also be installed on the appropriate Nano boards as
described in the [OLED guide](oled-display.md).

Boot to a text console. Lite provides this by default; an installation with a
desktop must be configured for console boot through `sudo raspi-config` before
using direct KMS output. Run initial HDMI checks from the local console.

For a monitor supporting 720p60, edit `/boot/firmware/cmdline.txt`:

```sh
sudo nano /boot/firmware/cmdline.txt
```

Append the following argument to the **existing single line**, separated by a
space, preserving all existing boot arguments. Do not add a second, conflicting
setting for the same connector:

```text
video=HDMI-A-1:1280x720@60D
```

Reboot after saving. The selector's default sink is
`kmssink driver-name=vc4 force-modesetting=true sync=false`. Check the monitor's
information screen for the actual resolution and refresh rate. For multiple
displays, inspect connectors with `modetest -M vc4 -c` and follow the
[camera installation guidance](../README.md#install-on-the-pi).

## 4. Configure and validate the components

From the repository root, create a local camera configuration:

```sh
cd ~/ProjectOpticCoyote
cp rpi-ahd-selector/config.json rpi-ahd-selector/config.local.json
v4l2-ctl --list-devices
python3 rpi-oled-bridge/bridge.py --list-ports
```

Create the copy only on initial setup; preserve existing local settings during
updates. Replace placeholder capture nodes with verified stable paths using
the [capture configuration procedure](../README.md#configure-the-capture-devices).
Configure blinker mappings and GPIO assignments using the
[blinker setup](../README.md#blinker-trigger-mode) and check the local file:

```sh
python3 rpi-ahd-selector/selector.py --config rpi-ahd-selector/config.local.json --check-config
```

Follow the [reverse setup](reverse-trigger.md) to create `reverse.local.json`,
assign a distinct protected GPIO input, and identify the sensor and display
Nano ports. The [combined trigger guide](combined-triggers.md) supplies the
cross-component conflict check and concurrent operating procedure. Configure
the [optional buzzer](pi-buzzer.md) only when its hardware and pin are assigned.
Pi I2C does not need enabling for the USB-connected Nano sensor/OLED path.

## 5. Perform hardware acceptance checks

1. Run the [adapter diagnostic and capture checks](../README.md#pi-side-adapter-diagnostic)
   for each actual camera/adapter and the intended hub configuration.
2. Start the selector from the local console with the configured file:
   `python3 rpi-ahd-selector/selector.py --config rpi-ahd-selector/config.local.json`.
   Confirm visible HDMI output and the configured LEFT/RIGHT/BOTH transitions.
3. Run the [reverse diagnostic procedure](reverse-diagnostics.md), then verify
   physical sensor acquisition, displayed distances, and release on reverse LOW.
4. Follow the [combined operation checks](combined-triggers.md) with camera
   capture and reverse/OLED operation active together. Record OS/kernel,
   device paths, capture modes, visible results, and observed failures.

Configuration validation and synthetic tests do not establish physical timing,
distinct camera exposure rate, or electrical behavior. Complete these checks
before unattended operation. After testing, stop the processes and use
`sudo poweroff` before disconnecting power.
