# Raspberry Pi installation package

[Documentation index](index.md) | [Project overview](../README.md)

The current release is **v0.5.2-beta**, represented as **`0.5.2~beta`** in Debian
metadata and filenames. Its Debian package and offline installer include the
updated Pi applications and maintained documentation. The accompanying source
archive includes both Nano firmware projects and their compiled default builds;
Nano upload remains a separate operation.

The examples below install v0.5.2-beta. Original v0.5.1-beta artifacts retain
their historical identities and hashes. See the
[current release notes](release-notes-v0.5.2-beta.md) for contents, checksums,
verification scope, and limitations.

## Target and contents

The package targets **Raspberry Pi OS Lite 64-bit Trixie on Raspberry Pi 5
(4 GB)**. Install the OS first using the [Pi setup guide](rpi5-setup.md).
The package supplies the existing Python applications, CLI wrappers, editable
configuration, documentation, and two independent systemd service definitions.
Application files remain readable Python source. Nano firmware installation is
a separate operation; no board is flashed by this installer.

The `.deb` has architecture `all` because its own payload is Python and text.
Its offline dependencies are specifically `arm64` or `all`. A bootable Trixie
system with Python 3, APT, and dpkg is required. An offline bundle is not an OS
image and does not install boot firmware or configure vehicle wiring.

## Online installation

Copy the built `.deb` to the Pi and install it with APT:

```sh
sudo apt update
sudo apt install ./project-optic-coyote_0.5.2~beta_all.deb
sudo optic-coyote-setup
```

Dependencies include GStreamer and its base/good/bad/libav plugins, V4L2 and DRM
utilities, Python GPIO Zero/lgpio, pySerial, GI/GStreamer diagnostic bindings,
systemd, and account management tools. `packaging/dependencies.txt` owns the list.

Installation creates the `optic-coyote` system account and initializes missing
configuration files in `/etc/project-optic-coyote`. Initial package installation
leaves both services disabled. Successful setup automatically enables both for
boot without starting them immediately. Source defaults remain installed under
`/usr/lib/project-optic-coyote`; local settings are never copied back there.

## Offline installation

Transfer the archive and its `.sha256` file to the Pi. From that directory:

```sh
sha256sum -c project-optic-coyote_0.5.2~beta_trixie_arm64_offline.tar.gz.sha256
tar -xzf project-optic-coyote_0.5.2~beta_trixie_arm64_offline.tar.gz
cd project-optic-coyote_0.5.2~beta_trixie_arm64_offline
python3 install.py --verify-only
sudo python3 install.py
sudo optic-coyote-setup
```

Use an extraction path without whitespace. The installer checks the complete
payload inventory and SHA-256 hashes before invoking APT. The local `Release`
file records index sizes and SHA-256 hashes, avoiding probes for unavailable
compression formats. Its temporary source
list references only the bundled local repository; normal repository settings
are not rewritten. APT resolves dependencies against the actual installed OS
and refuses package removals. Review its transaction before accepting it.

The bundle contains an empty-status dependency closure, including dependencies
normally present in the OS. APT installs only the packages needed by the target
system. Incompatible preinstalled versions or packages can still prevent a
transaction; do not force downgrades or remove OS packages to bypass a failure.
Rebuild a bundle for the updated baseline when required. The manifest records
exact versions and upstream sources; checksums detect corruption but are not a
publisher signature. Transfer the bundle through a trusted channel.

## Existing four-source configuration migration

Existing files in `/etc/project-optic-coyote/` are preserved during package
installation. A four-source `camera.json` is rejected by the two-camera
validator; setup does not guess physical camera identities or truncate it.

Before enabling the updated camera service:

1. Stop the camera and reverse services before changing their configuration.
2. Back up `camera.json`. Retain exactly the two physically identified mirror
   camera pipelines in `sources`, preferably using stable `/dev/v4l/by-id/` or
   `/dev/v4l/by-path/` identities. Set left=1 and right=2 when ordered left/right.
3. Set `initial_camera` to 1 or 2, `trigger_enabled` to `true`, and `gpio_pins`
   to `[]`. Retain the verified trigger polarity, pins, and timing. Camera
   commands 3/4 and four-value manual input snapshots are no longer accepted.
4. Run `sudo optic-coyote-setup --enable camera reverse` to validate assignments
   and enable boot startup. This does not start the services immediately.

The sensor firmware retains four distance slots and the existing reverse
protocol. Correct crossed sensor wiring in `kMuxChannels`, preserving physical
IDs 1-4 and the default bridge order; a foreground `--sensor-order` override
changes only the display and is not saved by setup. See
[sensor identity guidance](oled-display.md#preserve-physical-sensor-identities).
Standalone CSV headers and `nearest_zone` now use `rear_far_left`,
`rear_left_middle`, `rear_middle`, and `rear_far_right`. External CSV consumers
that match names must update those names. The Pi bridge continues accepting
older column labels by position. Sensor 3 remains rear-middle.

Hardware acceptance requires checking each blinker against the physical camera,
hazard blanking, hold through blink OFF gaps, direction changes, and simultaneous
reverse ranging. Measure activation-to-first-usable-image and left/right switching
time on the installed capture devices. Place a target at each numbered rear sensor
and verify its corresponding OLED column, including unavailable indications after
a sensor failure. Software tests do not establish these physical results.

## Configuration and CLI commands

`sudo optic-coyote-setup` checks Pi 5/Trixie/arm64, Python bindings, and required
GStreamer elements, lists stable device paths,
and collects sensor/display serial assignments, the reverse GPIO pin, left/right
blinker pins and camera mappings, and both capture pipelines (left and right). Empty input
retains existing values. Confirm physical roles explicitly, especially for
identical CH340 adapters. See [capture configuration](camera-setup.md#configure-the-capture-devices)
and [protected wiring](project-wiring.md).

Both services must be stopped before configuration or enablement changes;
starting, stopping, and reloading states also block setup. Setup runs are
serialized. Both services are disabled before dependency checks and editing.
Existing component validators and the combined resource checker validate the
candidate before files are written. An `INCOMPLETE` result rejects the candidate
and retains existing files. Successful validation saves the assignments, checks
the saved files, enables both services, and confirms persistent boot enablement.
Validation errors, write failures, interruption, or partial enablement leave both
disabled. A systemd failure that also prevents rollback is reported explicitly;
disabled state cannot be guaranteed in that case.

The previous version of each changed JSON file is saved as `.json.bak`. Writes
are atomic per file; an interrupted sequence can leave some validated files
updated while others retain their previous values. Services remain disabled
until setup succeeds again. Repeated initialization preserves existing files.
Configuration files can also be edited directly with a text editor; stop
services before changing GPIO or USB ownership, then use the validation and
enablement command below. Metadata validation does not qualify physical wiring.

| Command | Purpose |
| --- | --- |
| `optic-coyote-setup` | Configure assignments and automatically enable both services for boot after successful validation |
| `optic-coyote-setup --enable camera reverse` | Validate existing settings and enable both without changing assignments |
| `optic-coyote-setup --init-only` | Create missing local configuration without replacing existing settings or changing service enablement |
| `optic-coyote-setup --list-devices` | List stable video and serial paths without opening devices |
| `optic-coyote-setup --hdmi-720p60` | Append the HDMI0 720p60 boot mode; preserve a backup, reject conflicting modes, and preserve service enablement |
| `optic-coyote-camera` | Run the camera selector with installed camera configuration |
| `optic-coyote-control` | Existing JSON command generator or serial sender |
| `optic-coyote-reverse` | Run the reverse/OLED bridge with configured serial roles |
| `optic-coyote-buzzer` | Inspect or explicitly play configured buzzer patterns; disabled by default |
| `optic-coyote-check` | Validate combined configuration and device metadata without opening hardware |
| `optic-coyote-diagnose-camera` | Camera diagnostic; normal execution opens capture hardware |
| `optic-coyote-diagnose-reverse` | Synthetic reverse diagnostic by default; `--hardware` operates GPIO/USB |

Setup operation flags are mutually exclusive. `--enable camera` or
`--enable reverse` enables only the selected service and leaves the other
disabled; both still require complete combined assignment validation.
Every public command supports `--help`. Component options remain available,
including `--config`, `--reverse-config`, and explicit serial role overrides.
Examples:

```sh
optic-coyote-camera --check-config
optic-coyote-reverse --check-config
optic-coyote-buzzer --check-config
optic-coyote-reverse --list-ports
optic-coyote-diagnose-camera --check-config
optic-coyote-diagnose-reverse
optic-coyote-check
```

`optic-coyote-check` returns 0 for complete metadata coverage, 1 for incomplete
device/pipeline inspection, or 2 for configuration errors. It cannot establish
electrical compatibility or physical role suitability. `optic-coyote-control`
does not send commands to the running systemd service through a new IPC channel;
its existing stdout/serial transport behavior is retained. Blinker GPIO controls
the camera service. For foreground manual control, stop that service first and
use the existing command pipeline with a suitable manual-mode configuration.

Diagnostics write under the invoking account's
`~/.local/state/project-optic-coyote/`; `--report-dir` selects another writable
location. The configured login account needs the `video`, `render`, `gpio`, and
`dialout` groups for foreground hardware use, as specified in the Pi setup guide.
The service account receives these groups through its systemd units.

## Services and logs

The camera and reverse services remain separate. Neither depends on the other's
health. Startup validates its own configuration and the existing program owns
runtime recovery. Systemd retries failed processes every three seconds without
a startup retry limit, allowing delayed device availability. Configuration or
command errors exiting with status 2 are not retried; correct the settings and
start the affected service explicitly. Both use a non-login service account,
systemd journal output,
restricted filesystem writes, and `/var/lib/project-optic-coyote` as their
working directory. Device access remains available for GPIO, USB, and DRM.

Successful interactive setup has already enabled both services for the next
boot. Before rebooting, complete the
[hardware acceptance procedure](rpi5-setup.md#5-perform-hardware-acceptance-checks).
For settings edited manually, validate and enable them with
`sudo optic-coyote-setup --enable camera reverse`. To start the configured
services immediately and inspect them:

```sh
sudo systemctl start optic-coyote-camera.service optic-coyote-reverse.service
systemctl status optic-coyote-camera.service optic-coyote-reverse.service
journalctl -u optic-coyote-camera.service -u optic-coyote-reverse.service -b
```

Enablement performs the combined metadata check and configures future boot;
it does not start services immediately. Run from console boot without a desktop
compositor owning DRM. The actual KMS permissions, startup timing, and visible
output must be verified on the Pi. Do not run foreground applications or live
diagnostics while a service owns their hardware:

```sh
sudo systemctl stop optic-coyote-camera.service optic-coyote-reverse.service
sudo systemctl disable optic-coyote-camera.service optic-coyote-reverse.service
```

## Upgrades and removal

Install the newer `.deb` through APT. Upgrades stop both services before replacing
code, preserve configuration and enabled state, and leave services stopped.
Review configuration and run `optic-coyote-check` before explicitly restarting.
Rebooting will start services that remain enabled.

`sudo apt remove project-optic-coyote` stops and disables services. Local
configuration, diagnostic reports, and the system account are retained for
recovery, including on purge. Delete those separately only after deciding that
they are no longer needed. Installation does not modify console boot selection,
network settings, or HDMI arguments unless the explicit setup option is used.

## Build and verification

Run on Linux or WSL with Python 3.11+, `dpkg-deb`, and APT; host verification also
requires `g++` and systemd utilities. The offline output path must not contain
whitespace, quotes, or commas:

```sh
python3 packaging/build_package.py
python3 packaging/build_offline.py --package dist/project-optic-coyote_0.5.2~beta_all.deb
python3 packaging/verify_host.py
```

`packaging/VERSION` owns the default version. The package builder uses an
explicit inventory and normalizes permissions, line endings, ownership, and
timestamps. Package metadata includes the installed payload size. Offline
archives normalize directory and installer modes to `0755`, other files to
`0644`, and ownership to root independently of the build filesystem.
Set `SOURCE_DATE_EPOCH` to the release timestamp for reproducible
package builds. Generated files are written to ignored `dist/`.

The offline builder authenticates Debian Trixie, updates, security, and Raspberry
Pi Trixie repositories using archive keys fetched from official HTTPS endpoints.
The Raspberry Pi keyring package is pinned by SHA-256; its current certificate
avoids the obsolete SHA-1 certification in the legacy standalone key file.
It resolves arm64 dependencies against an empty installed-package database,
without changing host sources, installed packages, or enabled architectures.
It then repeats dependency resolution using only the generated local repository.
Each build requires a new output directory if that version's bundle already
exists. Preserve the prior artifact rather than merging dependency snapshots.

The archive includes installation instructions, exact package versions,
checksums, and the local dependency-resolution report. It is a snapshot of the
repositories at build time, not a promise that a later rebuild resolves the
same versions. Package installation can be tested in an isolated Linux root;
simulation alone does not prove maintainer-script execution or boot behavior.
No physical Pi, camera, GPIO, USB, or display result follows from host checks.

### Changes included in v0.5.2-beta

The [current release notes](release-notes-v0.5.2-beta.md) describe the two-camera
selection and sensor-identity corrections, OLED layout and freshness fixes,
documentation reorganization and review, and Git-file maintenance. Updated Pi
code and documentation are included in the rebuilt package and offline installer.
Firmware sources, tests, and compiled Nano builds accompany the source archive.

The historical results below describe earlier revisions. Current release
software results and artifact checks are documented separately in the
[v0.5.2-beta verification record](release-notes-v0.5.2-beta.md#recorded-verification-and-limitations).

### Two-camera revision verification, 2026-10-16

The two-camera source revision passed 303 Python tests (32 packaging, 104 camera,
106 bridge/reverse, 27 buzzer, and 34 integration), plus 11 retained prototype
compatibility tests. Four firmware host harnesses and shell/systemd definition
checks passed in WSL. The sensor firmware compiled for
`arduino:avr:nano:cpu=atmega328`; no device was flashed.

The checks cover two-source validation, rejected camera 3/4 commands, physical-role
setup role assignments, sensor CSV labels/order, blink gaps, hazard blanking, reverse
coexistence, and simulated device faults. Physical camera identity/orientation,
video latency, vehicle signal behavior, and ultrasonic accuracy remain unverified.
The earlier release lifecycle evidence below applies to that release baseline;
it is not a new installation or hardware result for this source revision.

### Recorded verification, 2026-10-16

These host results cover **v0.5.1-beta** (`0.5.1~beta` in Debian metadata).
Archive hashes and dependency versions are recorded alongside each generated
release. Host checks do not establish Pi hardware compatibility.

| Check | Result and boundary |
| --- | --- |
| Python regression suites | 296 tests passed: 30 packaging, 100 camera, 105 bridge/reverse, 27 buzzer, and 34 integration tests |
| Firmware host harnesses | Four C++ builds and executions passed using Nano/display stubs; no firmware was uploaded |
| Unit and maintainer scripts | `systemd-analyze verify` and `sh -n` passed; no service was run against hardware |
| Isolated Debian Trixie amd64 installation | Real Debian/Raspberry Pi repository dependencies installed; all eight CLI help commands and applicable software checks passed |
| Upgrade and removal | Upgrade from 0.1.1 to 0.5.1~beta preserved edited configuration and enabled state; removal, purge, and beta reinstallation retained configuration; reinstallation left both services disabled |
| Automatic boot enablement | Real offline systemd links were created for both services and removed after failed reconfiguration; installed setup was also exercised in the isolated root with simulated Pi identity, stopped state, and character-device metadata |
| Failure handling | Dependency, validation, configuration-write, interruption, partial-enablement, and unconfirmed-enablement failures left both services disabled in host tests; active and transitioning service states blocked writes |
| Platform guard | Setup rejected the non-Pi test host before configuration changes |
| arm64 offline repository | Dependency closure and checksum verification are separate from native installation; the amd64 lifecycle check does not prove arm64 execution |

Host logs are generated under ignored `dist/verification/`. The isolated
installation check used a disposable Debian root with the current Raspberry Pi
archive keyring. Setup fixtures supplied metadata only; they did not boot
systemd, emulate Pi devices, or establish physical device suitability. Physical
hardware was unavailable. Service startup at Pi boot, GPIO/USB access, KMS
permissions, camera throughput, and OLED behavior remain unverified.

References: [Debian dependency metadata](https://www.debian.org/doc/manuals/debian-handbook/sect.package-meta-information.en.html),
[APT download and simulation options](https://manpages.debian.org/trixie/apt/apt-get.8.en.html),
and [Debian maintainer scripts](https://www.debian.org/doc/debian-policy/ch-maintainerscripts.html).
