# Project Optic Coyote — Version 0.5.2 - Beta

[Documentation index](index.md) | [Current source status](current-state.md)

Release identifier: **`v0.5.2-beta`**  
Debian package version: **`0.5.2~beta`**

This release includes the two-camera, rear-sensor, OLED, documentation, and
Git-file changes listed below. The Debian package and offline installer contain
the updated Pi applications and documentation. The accompanying source archive
contains both Nano sketches, their headers, tests, and the complete maintained
repository files. Nano firmware deployment remains separate from Pi installation.

The original v0.5.1-beta artifacts remain historical builds. Use the filenames
and checksums for v0.5.2-beta when installing this release.

## Cameras and rear sensors

- Camera selection supports exactly two exterior mirror-area cameras facing
  rearward. Left and right blinkers select their corresponding cameras. The
  default source mapping is left=1 and right=2; distinct swapped mappings are
  supported.
- Both-active hazard input inhibits capture and requests black HDMI output.
  Reverse-controlled acquisition and OLED operation continue independently of
  blinker selection and hazards.
- Four rear-bumper sensors retain physical identities: 1 far left, 2 left-middle,
  3 rear-middle, and 4 far right. All face directly rearward. Firmware channel
  mapping preserves these identities and serial packet positions.
- Setup and validation reject obsolete four-camera configurations rather than
  silently removing sources. The earlier four-camera GPIO prototype remains a
  historical reference outside supported operation.

## OLED presentation and timing

- Four fixed columns use 9×16 distance glyphs with sensor labels and a shared
  `ft` label within the 128×32 display bounds.
- Values display as rounded `0.0`–`9.9`, followed by `≥10` for higher rounded
  values. The boundary is 3032 mm → `9.9`, 3033 mm → `≥10`; the marker is a
  presentation cap, not a raw-distance threshold of 3048 mm.
- Missing, invalid, and stale measurements display `-.-`. Raw millimetre data
  and alarm thresholds remain unchanged.
- Freshness is checked before drawing and transfer. Data that expires during
  drawing is replaced with unavailable markers; expired display ownership
  selects the idle view. Qualified reverse HIGH activates ranging and display
  ownership, and observed reverse LOW releases them. The current idle view is blank.

See the [OLED guide](oled-display.md#fixed-pixel-layout) for pixel geometry,
formatting, freshness limits, and verification procedures.

## Documentation and repository maintenance

- The main README now contains the user-facing overview and setup links.
  Dedicated guides cover sensor operation, camera setup, capture diagnostics,
  configuration, code structure, and verification.
- The documentation review clarified source-checkout and installed command
  paths, local configuration selection, standalone firmware requirements,
  reverse snapshot timing, and the distinction between source changes and
  existing artifacts. The sensor connectivity diagram includes the multiplexer.
- Documentation uses impersonal technical descriptions and separates software
  evidence from unverified physical behavior.
- Ignore rules cover package outputs generated at the repository root or in
  `packaging/`, compiler coverage data, and stack-usage output. Source, tests,
  configuration defaults, and maintained documentation images remain trackable.
- `.gitattributes` specifies LF text handling and binary asset handling without
  character-encoding conversion. Existing working files are not automatically
  rewritten. See [Git file handling](development.md#git-file-handling).

## Upgrade considerations

Existing installation settings remain preserved. Before deploying updated
source, follow the [four-source configuration migration](installation-package.md#existing-four-source-configuration-migration)
and verify both physical camera identities. Standalone CSV consumers matching
column names must accommodate the rear-sensor labels; the bridge accepts older
labels by position. Display ordering overrides do not reassign physical sensor
identities or persist through setup.

Nano firmware is installed separately from the Pi package. The default sensor
and display builds use reverse control; standalone CSV/OLED operation requires
the corresponding explicit standalone builds and bridge procedure. Complete
the [combined-operation checks](combined-triggers.md) before vehicle use.

## Release artifacts

| Artifact | Filename |
| --- | --- |
| Debian package | `project-optic-coyote_0.5.2~beta_all.deb` |
| Package metadata and checksum | `project-optic-coyote_0.5.2~beta_all.json` |
| Offline installer and arm64 dependency repository | `project-optic-coyote_0.5.2~beta_trixie_arm64_offline.tar.gz` |
| Offline archive checksum | `project-optic-coyote_0.5.2~beta_trixie_arm64_offline.tar.gz.sha256` |
| Complete source archive, including Nano firmware | `project-optic-coyote_0.5.2~beta_source.tar.gz` |
| Release checksums | `SHA256SUMS` |
| Artifact verification record | `verification.json` |

The release output directory is `dist/v0.5.2-beta/`. Check `SHA256SUMS` from that
directory with `sha256sum -c SHA256SUMS`. Hashes are stored beside the artifacts,
rather than inside documentation embedded in those same artifacts. The offline
bundle also verifies its complete payload through `python3 install.py --verify-only`.
Its `manifest.json` records exact dependency versions, sources, and package count.

The source archive includes the compiled default reverse-mode Nano `.hex` files
under `firmware/nano/`, plus build details in `firmware/nano/BUILD.md`. These files
are built for `arduino:avr:nano:cpu=atmega328` and do not contain a bootloader.
Flashing requires a separately connected matching Nano and explicit board/port
selection. Neither the Debian package nor the offline installer flashes a board.

## Recorded verification and limitations

Release software verification passed **304 Python tests**: 32 packaging,
104 camera, 106 bridge/reverse, 27 buzzer, and 35 integration. Four C++ firmware
host harnesses, maintainer-script shell syntax, and systemd unit checks passed.
Both default reverse-mode Nano sketches compiled for
`arduino:avr:nano:cpu=atmega328`: sensor firmware uses 9210 bytes of flash and
826 bytes of static RAM; display firmware uses 19488 bytes of flash and 700 bytes
of static RAM, plus its dynamically allocated framebuffer. No device was flashed.

Artifact verification checks package version ordering, payload contents,
documentation byte equality, permissions, checksums, and reproducible Debian
package output. The offline builder resolves dependencies using its isolated
arm64 APT state and repeats resolution against the generated local repository.
The accompanying `verification.json` records completed artifact checks and their
scope. Earlier review results remain in the
[current source verification record](current-state.md#recorded-software-verification).

The documentation review checked 38 external URLs: 32 responded successfully,
and six Raspberry Pi URLs returned HTTP 403 and remained unconfirmed. Successful
HTTP responses do not establish component compatibility or validate every remote
page fragment.

Physical Pi boot, GPIO conditioning, camera capture and orientation, ultrasonic
coverage, USB recovery, OLED visibility, and end-to-end timing remain unverified.
Historical artifact hashes and original release evidence remain in the
[v0.5.1-beta release notes](release-notes-v0.5.1-beta.md).
