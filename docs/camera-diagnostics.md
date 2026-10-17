# Camera capture diagnostics

[Documentation index](index.md) · [Project overview](../README.md)

This guide covers capture-mode verification and diagnostic reports. Complete
[camera setup](camera-setup.md) first. Commands run from `rpi-ahd-selector/`
unless another working directory is specified. For a complete checkout, enter
`~/ProjectOpticCoyote/rpi-ahd-selector`; a camera-only copy may instead reside at
`~/rpi-ahd-selector`. Package installations provide
`optic-coyote-diagnose-camera` with the same diagnostic options; see the
[installed commands](installation-package.md#configuration-and-cli-commands).

## Verify MJPEG 720p60 on the Pi

For an automated report, use the [Pi-side adapter diagnostic](#pi-side-adapter-diagnostic).
The manual commands below remain useful for inspecting individual steps.

These are **bench procedures to run on the Raspberry Pi 5 (4 GB), not completed test results**. Stop the selector and any other capture program first. Connect and independently power a compatible AHD camera. Run each adapter separately using its actual video-capture node; repeat with the intended hub and cabling. Install the dependencies listed in [camera setup](camera-setup.md#install-on-the-pi) before testing.

1. Enumerate devices and advertised driver modes:

   ```sh
   v4l2-ctl --list-devices
   ls -l /dev/v4l/by-id/ /dev/v4l/by-path/
   capture_device='/dev/video0'
   v4l2-ctl --device="$capture_device" --all
   v4l2-ctl --device="$capture_device" --list-formats-ext
   ```

   Replace `/dev/video0` with the identified capture node before proceeding, preferably its stable path. Look for FourCC **`MJPG`**, **1280×720**, and **60.000 fps** (approximately 0.016667 seconds per frame). This establishes only what the driver exposes. A 59.94 fps mode is distinct from exact 60 fps; use its reported interval rather than forcing `60/1`.

2. Request the mode, read back the accepted settings, and receive 600 buffers in one device session:

   ```sh
   timeout --signal=INT --kill-after=5s 30s \
     v4l2-ctl --device="$capture_device" \
       --set-fmt-video=width=1280,height=720,pixelformat=MJPG \
       --set-parm=60 --get-fmt-video --get-parm \
       --stream-mmap=4 --stream-count=600 --stream-to=/dev/null
   ```

   Confirm the returned format and rate, rather than assuming the request was accepted unchanged. Check the reported capture rate and any driver errors or dropped-buffer reports. At 60 buffers/s, 600 buffers represent about ten seconds of capture plus startup overhead. A timeout, fallback format, lower rate, or error is not a pass. `/dev/null` discards the video; nothing is recorded. Command references: upstream [V4L2 streaming options](https://github.com/gjasny/v4l-utils/blob/master/utils/v4l2-ctl/v4l2-ctl-streaming.cpp) and [frame-rate options](https://github.com/gjasny/v4l-utils/blob/master/utils/v4l2-ctl/v4l2-ctl-misc.cpp).

3. Exercise MJPEG negotiation and JPEG decoding without HDMI or frame-rate conversion:

   ```sh
   timeout --signal=INT --kill-after=5s 30s \
     gst-launch-1.0 -e -v \
       v4l2src device="$capture_device" num-buffers=600 do-timestamp=true \
       ! image/jpeg,width=1280,height=720,framerate=60/1 \
       ! jpegdec ! fakesink sync=false
   ```

   Require successful negotiation of the requested caps and normal end-of-stream after 600 buffers, without decoder errors or timeout. This tests receipt and decoding; the caps alone do not measure sustained throughput. No `videorate` is used, so this procedure does not insert frames to satisfy the requested output rate. GStreamer references: [v4l2src](https://gstreamer.freedesktop.org/documentation/video4linux2/v4l2src.html) and [jpegdec](https://gstreamer.freedesktop.org/documentation/jpeg/jpegdec.html).

After successful capture/decode checks, update the appropriate `sources` entries with the verified stable paths and mode, run `python3 selector.py --check-config`, then test actual HDMI playback and LEFT/RIGHT/BOTH transitions. The supplied JSON remains automatically negotiated until installation-specific values are verified. Driver enumeration, successful frame receipt, decoded output, distinct camera frames, HDMI refresh, and end-to-end latency are separate findings; none implies all the others. Record the test date, Pi OS/kernel, adapter identifiers/revision, camera mode, hub/port, accepted format/rate, observed buffer rate, and errors. No hardware result should be marked verified from listing text or host-only tests.

## Pi-side adapter diagnostic

[`diagnose_adapter.py`](../rpi-ahd-selector/diagnose_adapter.py) inventories one
explicit V4L2 device and performs separate compressed-capture and JPEG-decoding
tests. It runs locally on the **Raspberry Pi 5 with 4 GB RAM**, discards video
buffers, and saves readable `.txt` and structured `.json` reports. It does not
change selector configuration or start/stop the selector service. Stop other
capture programs and connect a continuously powered compatible AHD camera before
running it. Repeat for each adapter and the intended USB hub/port arrangement.

Install the additional GStreamer Python bindings, then identify the capture node:

```sh
sudo apt install python3-gi gir1.2-gstreamer-1.0
v4l2-ctl --list-devices
python3 diagnose_adapter.py --device /dev/video0
```

Replace `/dev/video0` with the verified capture node or stable
`/dev/v4l/by-id/...` or `/dev/v4l/by-path/...` path. The script does not select a
device automatically. Use the system `python3` with the installed GI bindings.
The [camera setup dependencies](camera-setup.md#install-on-the-pi) provide `v4l2-ctl`, `v4l2src`, and `jpegdec`.
Dependencies can be pre-provisioned for offline operation.

All test settings are in [`diagnostic.json`](../rpi-ahd-selector/diagnostic.json),
separate from the playback configuration:

| Setting | Default | Meaning |
| --- | --- | --- |
| `device` | `null` | Explicit capture path; `--device` overrides this value. |
| `width`, `height`, `fps` | `1280`, `720`, `60` | Required MJPEG mode, using integer fps. Fractional 59.94 fps is not exact 60 fps. |
| `warmup_buffers` | `60` | Initial buffers excluded from rate measurement. |
| `measurement_buffers` | `600` | Buffers counted after warmup, approximately ten seconds at 60 fps. |
| `rate_tolerance_percent` | `5.0` | Allowed mean delivery-rate deviation in either direction; default 57–63 buffers/s. Negotiated caps must still be exact 60/1. |
| `max_buffer_gap_seconds` | `0.25` | Maximum interval between delivered buffers after warmup, including the boundary from the final warmup buffer. A longer gap fails even if subsequent bursts restore the mean rate. |
| `test_timeout_seconds` | `30.0` | Total limit per capture/decode worker, including startup and teardown. Must exceed nominal warmup plus measurement duration. |
| `probe_timeout_seconds` | `10.0` | Limit per V4L2 inventory command. |
| `cleanup_timeout_seconds` | `3.0` | Additional bounded wait for process termination after a timeout or interruption. Unconfirmed cleanup stops further device operations. |

For installation-specific tuning, copy the settings to `diagnostic.local.json`:

```sh
cp diagnostic.json diagnostic.local.json
python3 diagnose_adapter.py --config diagnostic.local.json --check-config
python3 diagnose_adapter.py --config diagnostic.local.json --device /dev/video0
python3 diagnose_adapter.py --device /dev/video0 --capabilities-only
```

`--check-config` performs no hardware access. `--capabilities-only` reads device
identity and modes but marks both hardware tests **SKIPPED**. Test runs save
timestamped reports under `diagnostic-reports/` beside the script; `--report-dir`
selects another directory. The default report directory and local configuration
are ignored by Git. Reports retain configuration, observed host model/kernel,
reported memory, V4L2 identity/modes, negotiated caps, counts, timing, warnings,
maximum measured gap, cleanup status/PID, errors, and command output. Existing
local configurations must include both `max_buffer_gap_seconds` and
`cleanup_timeout_seconds`; missing settings are rejected before device access.
The specified Pi 5 4 GB model is recorded separately
from observed host information; reported usable memory is not an independent
validation of the nominal RAM variant. Adapter model/revision, camera mode, and
physical hub/cable details still require a bench record.

The report separates three evidence levels:

- **Detected capabilities:** discrete `MJPG` modes returned by V4L2 enumeration.
  Unsupported output formats or continuous/stepwise ranges remain in the raw
  log and are not inferred as discrete support. A detected mode is never a pass.
- **Capture test:** exact negotiated MJPEG input/output caps, full nonempty buffer
  counts, normal end-of-stream, measured rate within tolerance, and maximum
  measured gap within its configured limit.
- **Decode test:** the same conditions with `jpegdec` inserted, checking raw
  output dimensions/rate and counting compressed input and decoded output
  separately. Wrong output dimensions or dropped frames fail. Empty input,
  CORRUPTED, GAP, and DECODE_ONLY flags are rejected before decoding, even if the
  decoder removes those flags. Invalid output buffers also fail. Capture success
  does not imply decode success.

Each test reports **PASS**, **FAIL**, **INCONCLUSIVE**, or **SKIPPED**. Timeouts,
GStreamer errors, incomplete/invalid buffers, wrong caps, out-of-range rates,
excessive gaps, and failed pipeline teardown fail. Queued errors/warnings are
drained after EOS before teardown; EOS alone is insufficient for a pass.
Missing tools/bindings, malformed evidence, warnings, or worker stderr
produce an inconclusive result requiring inspection. Capture and decode run
sequentially in isolated workers. After timeout or Ctrl+C, the parent kills the
worker and waits for at most `cleanup_timeout_seconds` to confirm exit. If exit
cannot be confirmed, the PID is reported and subsequent device operations are
skipped. Inspect the process and device before running another diagnostic. OS
process creation is not interruptible by the Python timeout, and an
uninterruptible kernel wait can prevent immediate reaping even after kill.
Process creation time is deducted from the remaining test budget; a completed
worker that exceeds the total budget cannot pass. Ctrl+C cancels the run without
claiming a completed report.

Exit status is `0` only when both hardware tests pass; `1` indicates at least one
non-pass result, including capabilities-only runs; `2` indicates a configuration
or report-writing error; `130` indicates interruption. A missing V4L2 utility
leaves inventory unconfirmed even if independent GStreamer tests pass.

With warmup enabled, rate is `measured buffers / (last measured arrival - last
warmup arrival)`. With zero warmup, the first arrival establishes the baseline,
so rate is `(measured buffers - 1) / (last arrival - first arrival)`. Both use a
monotonic clock. The maximum gap covers the same interval, including the first
post-warmup interval. Evidence validation checks finite, consistent counts,
durations, rates, gaps, caps types, and parent-observed elapsed time; malformed
evidence cannot pass. There is no frame-rate conversion, display synchronization,
recording, or network transport. A pass covers only the measured duration and
configured tolerance and gap limit; it does not prove long-term stability, absence of jitter,
distinct camera exposures, image correctness, HDMI output, or trigger timing.
The implementation uses GStreamer's [fakesink handoff signal](https://gstreamer.freedesktop.org/documentation/coreelements/fakesink.html)
and [bus error/EOS handling](https://gstreamer.freedesktop.org/documentation/tutorials/basic/concepts.html).
Decoded output uses the [jpegdec raw-video interface](https://gstreamer.freedesktop.org/documentation/jpeg/jpegdec.html).

Host checks use synthetic modes, measurements, and subprocess outcomes:

```sh
python3 -m unittest test_diagnose_adapter -v
```

These checks verify software classification, simulated decoder failures, report
generation, and actual host child-process timeout cleanup, not adapter
or Pi hardware behavior. No physical diagnostic result is supplied by the repository.

