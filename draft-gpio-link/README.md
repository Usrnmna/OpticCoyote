# Retired four-camera GPIO prototype

Current project release: [v0.5.2-beta](../docs/release-notes-v0.5.2-beta.md) (Debian `0.5.2~beta`).

Historical reference only. This prototype is outside the supported two-camera,
four-rear-sensor installation. Its sensor labels and four-camera protocol are
retained as historical behavior; commands for cameras 3 and 4 are rejected by
the current selector. The setup instructions below do not apply to the current
installation. Use the reverse sensor firmware and blinker service instead.

## Draft Arduino-to-Pi GPIO connection



This draft establishes a local wired connection with no network communication or recording. Upload its standalone Arduino sketch instead of the sensor-only sketch, then run the Pi listener. The listener can report camera numbers by itself or send JSON commands through the camera selector's standard input.



The Pi listener must already be running to read GPIO. A wire changing level does not itself launch a Linux program. Start the listener once using the command below; it then reacts to incoming warnings until stopped. Automatic boot startup and launching a new process for each warning are outside this draft.



### Draft files and manual adjustment



| File | Review and edit here |

| --- | --- |

| [`arduino_camera_warning.ino`](arduino_camera_warning/arduino_camera_warning.ino) | `Config` contains the sensor settings. `CameraLink` contains output pins and the sensor-to-camera map. `setupCameraLink()` initializes outputs; `publishCameraWarning()` updates them from `publishCompletedScan()`. This self-contained reference prototype retains automatic filtered CSV output; it does not implement the Nano USB stream protocol. |

| [`warning_receiver.py`](warning_receiver.py) | Top-level defaults and `--help` expose GPIO and timing settings. `decode_camera()` reads the logical selection, `StableCamera` filters short transitions, `report_camera()` formats it, and `listen()` owns GPIO setup/cleanup. |

| [`test_warning_receiver.py`](test_warning_receiver.py) | Software checks for all 16 wire combinations, transitions, cleanup, settings, and command acceptance by the camera selector. |



### Signal and camera mapping



Four signal wires encode one camera number by holding **exactly one** active. This is a held selection, not binary encoding, a pulse count, or a distance measurement. Both WARNING and CRITICAL select the nearest valid sensor's associated camera. Equal distances favor the earlier sensor in the configured order. A complete scan updates the selection, approximately every 420 ms plus processing overhead with default settings when all triggers succeed. Failed triggers skip the measurement wait.



| Sensor zone | Camera number | Arduino output | Pi BCM input | Pi physical header pin |

| --- | --- | --- | --- | --- |

| front_left | 1 | D4 | GPIO17 | 11 |

| front_right | 2 | D5 | GPIO27 | 13 |

| rear_left | 3 | D6 | GPIO22 | 15 |

| rear_right | 4 | D7 | GPIO23 | 16 |



Historical camera numbers refer to entries 1-4 in a four-source configuration. The current selector accepts only two sources; this mapping is retained solely as a prototype reference. Edit `CameraLink::kCameraForSensor` to match where the physical cameras actually face. Multiple zones may share a camera. The output pins always remain ordered camera 1, 2, 3, 4. Pins D4-D7 assume a classic Uno/Nano; check availability on the actual Arduino board.



At startup, `cameraLinkSettingsValid()` checks that output pins are distinct, within the board's digital-pin range, and do not overlap serial pins 0/1, SDA/SCL, alarm, or heartbeat. Each sensor must map to camera 1-4. Invalid settings print `ERROR: check CameraLink pins and sensor-to-camera map` and halt before GPIO setup or measurements. Valid settings initialize all camera outputs LOW. On a selection change, the sketch clears every output before setting the selected output HIGH; repeated selections do not rewrite the pins.



The default listener prints a number on each stable change:



- `1` through `4`: that camera has the nearest warning.

- `0`: all lines inactive. This includes clear readings, no valid sensors, Arduino reset/power loss, or disconnected wiring; these conditions cannot be distinguished by this link.

- `-1`: multiple lines are active, an invalid combination. A diagnostic also goes to standard error.



The default warning threshold is 600 mm and the critical threshold is 300 mm, inherited from the sensor sketch. Invalid sensors are excluded. There is no fault wire, acknowledgement, link heartbeat, or timeout: a frozen Arduino output can look like a continuing warning. This is a connection prototype, not a validated protective control.



### Wiring the draft link



**Never connect a 5 V Arduino GPIO directly to a Pi input.** Pi GPIO uses 3.3 V logic; see the [official Raspberry Pi GPIO voltage documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#voltage-specifications). The following draft interface uses four NPN transistor stages, one per camera, to keep Arduino voltage off the Pi GPIO and make Pi LOW mean active.



For each row in the mapping table, wire a small-signal NPN transistor (for example a 2N3904; verify its actual collector/base/emitter pinout):



```text

Arduino D4/D5/D6/D7 ---- 10 kOhm ---- NPN base

                                     |

                                  100 kOhm

                                     |

Common GND --------------------------+---- NPN emitter



Pi 3.3 V ---- 10 kOhm ----+---- corresponding Pi GPIO input

                         |

                         +---- NPN collector



Arduino GND ------------------ Pi GND (for example physical pin 6)

```



Repeat all three resistors and the transistor for each of the four channels. The collector pull-up goes to **Pi 3.3 V**, physical pin 1 or 17, never Arduino 5 V. Grounds are shared; do not join the boards' 5 V supply rails. The base pull-down holds each transistor off while the Arduino output is an input during reset. Arduino HIGH turns that channel on, making its Pi input LOW. Inactive Pi inputs read HIGH. Keep the default receiver polarity for this circuit; `--active-high` is only for a separately designed non-inverting 3.3 V interface.



Wire with power removed. Before attaching the signal inputs to the Pi, power the interface and check that each collector is near 3.3 V when inactive and near 0 V when selected. Check transistor pinouts and all four channels. Keep prototype wires short; long cable noise and vehicle electrical protection are not addressed by this draft.



### Upload and run the standalone draft



1. Open [`draft-gpio-link/arduino_camera_warning/arduino_camera_warning.ino`](arduino_camera_warning/arduino_camera_warning.ino) in Arduino IDE. Choose the target board and port; upload only to a separate prototype bench controller. This sketch must not replace either supported reverse-controlled Nano sketch. It requires only the board's standard `Wire` library. Sensor wiring remains as documented below. This older standalone draft streams filtered CSV automatically at boot; it does not implement the Nano firmware's `START`/`STOP` commands or polling interval setting.

2. Copy this project to the Pi, for example `~/ProjectOpticCoyote`. Provide `python3-gpiozero` and `python3-lgpio` using the existing Pi installation instructions, or provision packages offline. The receiver uses [GPIO Zero's input device API](https://gpiozero.readthedocs.io/en/stable/api_input.html#digitalinputdevice) and [lgpio pin factory](https://gpiozero.readthedocs.io/en/stable/api_pins.html#lgpio).

3. Start the listener from a Pi terminal:



```sh

cd ~/ProjectOpticCoyote

python3 draft-gpio-link/warning_receiver.py

```



The listener samples every 10 ms and accepts a state after 30 ms of stability. It reports an already-held warning at startup, prints changes only, and releases GPIO on Ctrl+C or SIGTERM. The listener does not start or switch the camera program in its default mode.



To change wiring or timing without editing Python:



```sh

python3 draft-gpio-link/warning_receiver.py --pins 17 27 22 23 --debounce-seconds 0.05

```



### Receiver options



Run `python3 draft-gpio-link/warning_receiver.py --help` from the project root for the command-line interface.



| Option | Default | Behavior |

| --- | --- | --- |

| `--pins BCM BCM BCM BCM` | `17 27 22 23` | Four distinct BCM numbers in 0-27, ordered camera 1-4; check board availability separately. |

| `--sample-seconds` | `0.01` | Finite polling interval from 0.001 to 1 second. |

| `--debounce-seconds` | `0.03` | Finite stable-state interval from 0 to 5 seconds. Zero accepts the current state on its first sample. |

| `--active-high` | Off | Use HIGH-active inputs with pull-downs; requires a compatible interface instead of the documented NPN circuit. |

| `--selector-json` | Off | Emit JSON for camera 1-4 only; suppress clear/conflict commands. |

| `--simulate STATE ...` | Off | Immediately report supplied values from -1 through 4 without GPIO or debounce; repeated values are printed too. |



### Optional connection to the camera program



After the standalone wiring test, pipe the listener's optional JSON output into the existing selector's standard input:



```sh

cd ~/ProjectOpticCoyote

python3 draft-gpio-link/warning_receiver.py --selector-json | python3 rpi-ahd-selector/selector.py

```



The receiver sends commands such as `{"camera": 2}` only for valid warnings. Clear or conflicting inputs send no camera command; the selector in manual mode keeps displaying its last selected camera. The pipe uses the selector's standard-input interface. The supplied camera configuration has `gpio_pins: []`, `serial_port: null`, and `trigger_enabled: false`. Keep those settings for this test, and stop any other running selector instance first: only the draft listener should own these GPIO inputs. The draft is separate from blinker trigger mode and does not provide its BOTH/stop behavior. Capture device configuration and video dependencies still need to match the installation.



Use Ctrl+C in the foreground terminal to stop both programs. If the listener exits alone, the existing selector deliberately continues displaying its last camera after input closes; stop it separately if needed. This draft does not supervise the camera process or automatically restart either program.



### Draft checks and validation boundary



Run software tests and a simulated report from the project root (use `python` instead of `python3` on Windows if needed):



```sh

python3 -m unittest discover -s draft-gpio-link -p "test_*.py" -v

python3 draft-gpio-link/warning_receiver.py --simulate 0 1 2 3 4 0

python3 draft-gpio-link/warning_receiver.py --selector-json --simulate 0 1 2 3 4 0

```



Simulation checks output formatting only; it does not read GPIO or exercise timing. On hardware, test clear startup, an object in each zone, overlapping warnings, warning removal, Arduino reset, and receiver restart during a held warning. Compare Arduino CSV `nearest_zone` with the Pi camera number. In camera mode, verify each number displays the intended physical camera. Expect sensor scan/filter delay plus GPIO debounce; software timing does not establish actual end-to-end response time.



The receiver tests use simulated inputs and fake GPIO resources. They cover decoding, debounce transitions, output formatting, selector command acceptance, argument validation, and cleanup. They do not validate Arduino firmware execution, electrical behavior, sensor response, or live camera switching. Compile the draft for the actual board and perform the wiring checks before use.


