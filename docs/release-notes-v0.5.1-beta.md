# Project Optic Coyote — Version 0.5.1 - Beta

Release date: **2026-10-16**  
Release identifier: **`v0.5.1-beta`**  
Debian package version: **`0.5.1~beta`**

## Overview

This beta provides packaged Raspberry Pi deployment of the existing camera
selector and reverse-controlled ultrasonic/OLED bridge. It includes a Debian
package, an offline dependency bundle, installed CLI commands, an interactive
setup utility, and separate camera and reverse systemd services.

The recommended deployment target is **Raspberry Pi OS Lite 64-bit, Debian 13
Trixie, on Raspberry Pi 5 with 4 GB RAM**. Software checks passed without physical
hardware. Pi hardware compatibility and boot operation remain unverified.

## Included capabilities

- The Debian package installs readable Python sources, configuration templates,
  documentation, and eight CLI commands: `optic-coyote-setup`,
  `optic-coyote-check`, `optic-coyote-camera`, `optic-coyote-control`,
  `optic-coyote-reverse`, `optic-coyote-buzzer`, `optic-coyote-diagnose-camera`,
  and `optic-coyote-diagnose-reverse`.
- The offline bundle contains **427 packages**, covering the application and its
  Trixie arm64 dependency closure. Installation uses a temporary local APT source
  list and checks the payload inventory and SHA-256 hashes before invoking APT.
- Interactive setup collects explicit serial-device roles, reverse and blinker
  GPIO assignments, camera mappings, and capture pipelines. Component validators
  and the combined resource checker assess the candidate before saving it.
- Successful setup enables `optic-coyote-camera.service` and
  `optic-coyote-reverse.service` for subsequent boots without starting them
  immediately. Initial package installation leaves both disabled.
- The services retain independent configuration validation and recovery. The
  camera service owns blinker-driven capture and HDMI output; the reverse
  service owns reverse-controlled sensor acquisition and the OLED bridge.
- Local configuration resides in `/etc/project-optic-coyote`. Initialization
  preserves existing settings, and changed JSON files retain `.json.bak` backups.

## Corrections and reliability changes

- Incomplete device metadata rejects interactive configuration instead of
  saving it as a successful setup.
- Dependency, validation, write, interruption, and partial-enablement failures
  disable both services. Rollback failure is reported explicitly if systemd
  cannot perform the disable operation.
- Concurrent setup operations are prevented. Active or transitioning services
  block configuration changes, and conflicting setup operation flags are rejected.
- Services retry process failures every three seconds without a startup retry
  limit. Exit status `2`, used for configuration or command errors, requires
  correction and an explicit restart rather than automatic retries.
- Package permissions remain readable by the service account when built with a
  restrictive umask. Debian metadata now includes the installed payload size.
- Offline repository `Release` metadata records index hashes and sizes,
  eliminating the previous APT blank-filename errors during index discovery.
- Archive ownership and permissions are normalized independently of the build
  filesystem. Directories and the installer use `0755`; other files use `0644`.
- Installation guides, service instructions, release references, and ignore
  rules are synchronized with the packaging workflow.

## Installation and upgrade notes

Install a bootable Trixie OS before installing the application. The bundle is
not an OS image, and neither installer flashes Nano firmware or configures
vehicle wiring. Follow the [Pi setup guide](rpi5-setup.md) and the
[package installation guide](installation-package.md) for complete procedures.

For online installation, copy the Debian package to the Pi and run:

```sh
sudo apt update
sudo apt install ./project-optic-coyote_0.5.1~beta_all.deb
sudo optic-coyote-setup
```

Successful setup enables both services for the next boot. Complete hardware
acceptance checks before rebooting or explicitly starting them. Foreground
hardware diagnostics require the affected services to be stopped.

Upgrades stop both services before replacing code, preserve local configuration
and enabled state, and leave services stopped. Review configuration and run
`optic-coyote-check` before explicitly restarting. Rebooting starts services
that remain enabled. Removal stops and disables services; local configuration,
diagnostic reports, and the service account remain available, including after
purge.

The optional buzzer remains disabled by default and has no separate service.
Nano firmware installation remains a separate operation.

## Verification results

| Check | Recorded result |
| --- | --- |
| Python regression tests | **296 passed**: 30 packaging, 100 camera, 105 bridge/reverse, 27 buzzer, and 34 integration |
| Firmware host harnesses | Four C++ harnesses compiled and executed against host stubs |
| Service definitions and package scripts | `systemd-analyze verify` and shell syntax checks passed |
| Package lifecycle | Isolated Debian Trixie amd64 upgrade from `0.1.1` to `0.5.1~beta`, removal, purge, and reinstallation passed; settings were preserved |
| Installed commands and setup | CLI help/configuration checks and synthetic reverse diagnostics passed; setup created both real boot links and removed them after simulated validation failure |
| Debian package | Byte-identical rebuild, beta version ordering, payload-size metadata, ownership, and permissions verified |
| Offline bundle | All 427 package records and payload hashes verified; dependency resolution passed from fresh APT state with networking unavailable |
| Documentation | Local links, Markdown fences, and packaged documentation consistency checked |

Setup fixtures simulated Pi identity, inactive service state, and character-device
metadata. They exercised configuration and boot-link management without booting
systemd or operating physical devices. Host firmware checks did not upload code
to a Nano.

## Known limitations

- Native arm64 installation and service startup during an actual Pi boot remain
  unverified. The package lifecycle checks used amd64 user space.
- GPIO and USB access, DRM/KMS permissions, camera throughput, OLED behavior,
  electrical compatibility, and physical timing require bench validation.
- Metadata checks cannot establish physical device roles, wiring correctness,
  or suitability. Missing devices can prevent setup from completing.
- The offline dependency set is a repository snapshot. Incompatible installed
  packages may prevent installation; the installer refuses package removals.
- SHA-256 checks detect corruption but do not provide a publisher signature.

## Release artifacts

The Debian package contains architecture-independent Python and text files;
the offline dependency bundle targets `arm64` and `all` packages.

| Artifact | Filename |
| --- | --- |
| Debian package | `project-optic-coyote_0.5.1~beta_all.deb` |
| Offline bundle | `project-optic-coyote_0.5.1~beta_trixie_arm64_offline.tar.gz` |
| Bundle checksum | `project-optic-coyote_0.5.1~beta_trixie_arm64_offline.tar.gz.sha256` |

SHA-256 hashes for the verified release builds:

```text
4ec0db347711a391e4f47b9821f306d80c75ea2403f1d2bd0912b7911643cf76  project-optic-coyote_0.5.1~beta_all.deb
284a6a5348ad6001874ec8a8b81629a18ce77b5c2541cdf192cde2288fba49a6  project-optic-coyote_0.5.1~beta_trixie_arm64_offline.tar.gz
```

These release notes accompany the existing builds as a separate document. The
package and offline archive were not regenerated for this documentation addition.
