#include <Wire.h>

/*
  DRAFT GPIO CAMERA LINK: standalone copy of the ultrasonic sketch.
  Upload this sketch INSTEAD OF the original. See the root README for wiring.
  CameraLink settings and publishCameraWarning() are the added interface.
  Four outputs encode one camera number, not a binary number or pulse count.

  Four RCWL-1655 ultrasonic sensors through a TCA9548A I2C multiplexer.

  Target: Arduino-compatible board using the standard Wire library.
  RCWL-1655 I2C address: 0x57 (fixed)
  TCA9548A default address: 0x70

  Each RCWL-1655 must be placed in I2C mode (R7 = 100 kOhm):
    RCWL Trig/RX/SCL pin -> TCA9548A channel SCL
    RCWL Echo/TX/SDA pin -> TCA9548A channel SDA

  Serial output is one CSV record per completed four-sensor scan.
  Start manual review with Config, then serviceSensorPolling(), then
  publishCompletedScan(). Function comments describe inputs and side effects.
*/

// Fixed protocol/filter design. Changing these requires reviewing the matching
// decoding/filter functions; they are not installation tuning parameters.
namespace Design {
constexpr uint8_t kMuxChannelCount = 8;
constexpr uint8_t kStartMeasurementCommand = 0x01;
constexpr uint8_t kDistanceByteCount = 3;  // Big-endian 24-bit micrometres.
constexpr uint32_t kMicrometresPerMillimetre = 1000UL;
constexpr uint8_t kHistorySize = 3;  // medianOfHistory() implements three slots.
constexpr uint8_t kDisabledOutputPin = 255;
}  // namespace Design

// INSTALLATION SETTINGS: edit this section, then rebuild/upload the sketch.
namespace Config {
// I2C addresses are 7-bit. The sensor address is fixed for the RCWL-1655;
// change the mux address only to match its physical A0/A1/A2 address straps.
constexpr uint8_t kMuxAddress = 0x70;
constexpr uint8_t kSensorAddress = 0x57;
constexpr uint32_t kI2cClockHz = 100000UL;

// Fixed four-zone project layout, not a sensor-count tuning option.
constexpr uint8_t kSensorCount = 4;

// Matching indexes define the zone, physical mux port, and CSV column order.
// Channels must be distinct, in 0..7. Labels must be nonempty and contain no
// commas/newlines. Renaming a label changes its CSV header and nearest_zone.
constexpr uint8_t kMuxChannels[] = {0, 1, 2, 3};
const char *const kZoneLabels[] = {
    "front_left", "front_right", "rear_left", "rear_right"};

// Milliseconds: wait for one measurement, then pause before the next sensor.
// The datasheet allows up to 100 ms; verify hardware before reducing this wait.
constexpr uint16_t kMeasurementTimeMs = 100;
constexpr uint8_t kInterSensorGuardMs = 5;

// Inclusive accepted range in mm. Samples outside it are invalid, not clipped.
constexpr uint16_t kMinimumDistanceMm = 200;
constexpr uint16_t kMaximumDistanceMm = 5000;

// Inclusive thresholds in mm, applied to filtered readings at scan completion.
// WARNING and CRITICAL both activate the same alarm pin; CRITICAL changes CSV.
constexpr uint16_t kWarningDistanceMm = 600;
constexpr uint16_t kCriticalDistanceMm = 300;

// Board digital pin numbers. Set either pin to 255 to disable that output.
constexpr uint8_t kAlarmPin = 8;
constexpr bool kAlarmActiveHigh = true;
constexpr uint8_t kHeartbeatPin = LED_BUILTIN;
// Time between LED toggles; 500 ms means one complete on/off cycle per second.
constexpr uint32_t kHeartbeatToggleMs = 500;

constexpr uint32_t kSerialBaud = 115200;
}  // namespace Config

// DRAFT LINK SETTINGS: camera order is independent of sensor/mux order.
// Defaults target a classic Uno/Nano. Verify free pins on other boards.
namespace CameraLink {
constexpr uint8_t kCameraCount = 4;
// Camera 1, 2, 3, 4 respectively. HIGH drives an NPN transistor ON, pulling
// the corresponding Pi input LOW. Never connect a 5 V output directly to Pi.
constexpr uint8_t kOutputPins[] = {4, 5, 6, 7};
// Sensor order: front_left, front_right, rear_left, rear_right.
constexpr uint8_t kCameraForSensor[] = {1, 2, 3, 4};
}  // namespace CameraLink

static_assert(sizeof(CameraLink::kOutputPins) == CameraLink::kCameraCount,
              "Provide four uint8_t camera output pins");
static_assert(sizeof(CameraLink::kCameraForSensor) == Config::kSensorCount,
              "Provide one uint8_t camera number per sensor");

// Catch common editing mistakes before a sketch can be uploaded.
static_assert(Config::kSensorCount == 4, "This sketch uses four sensor zones");
static_assert(sizeof(Config::kMuxChannels) / sizeof(Config::kMuxChannels[0]) ==
                  Config::kSensorCount,
              "Provide one mux channel for each sensor zone");
static_assert(sizeof(Config::kZoneLabels) / sizeof(Config::kZoneLabels[0]) ==
                  Config::kSensorCount,
              "Provide one label for each sensor zone");
static_assert(Config::kMuxChannels[0] < Design::kMuxChannelCount &&
                  Config::kMuxChannels[1] < Design::kMuxChannelCount &&
                  Config::kMuxChannels[2] < Design::kMuxChannelCount &&
                  Config::kMuxChannels[3] < Design::kMuxChannelCount,
              "Mux channel numbers must be in 0..7");
static_assert(Config::kMuxChannels[0] != Config::kMuxChannels[1] &&
                  Config::kMuxChannels[0] != Config::kMuxChannels[2] &&
                  Config::kMuxChannels[0] != Config::kMuxChannels[3] &&
                  Config::kMuxChannels[1] != Config::kMuxChannels[2] &&
                  Config::kMuxChannels[1] != Config::kMuxChannels[3] &&
                  Config::kMuxChannels[2] != Config::kMuxChannels[3],
              "Each sensor needs a distinct mux channel");
static_assert(Config::kMinimumDistanceMm <= Config::kMaximumDistanceMm,
              "Minimum accepted distance must not exceed maximum");
static_assert(Config::kCriticalDistanceMm <= Config::kWarningDistanceMm,
              "Critical threshold must not exceed warning threshold");
static_assert(Config::kMeasurementTimeMs > 0 && Config::kI2cClockHz > 0 &&
                  Config::kSerialBaud > 0,
              "Measurement wait and bus/serial rates must be positive");
static_assert(Config::kHeartbeatToggleMs > 0 &&
                  Config::kHeartbeatToggleMs < 0x80000000UL,
              "Heartbeat interval must be positive and fit deadline arithmetic");
static_assert(Config::kAlarmPin == Design::kDisabledOutputPin ||
                  Config::kHeartbeatPin == Design::kDisabledOutputPin ||
                  Config::kAlarmPin != Config::kHeartbeatPin,
              "Alarm and heartbeat must use different enabled pins");

// RUNTIME STATE: no user settings below this point.
// History contains only successful samples and survives failures. 'valid'
// describes the latest attempt; an invalid sensor is excluded from decisions.
struct SensorState {
  uint16_t historyMm[Design::kHistorySize];
  uint16_t filteredDistanceMm;
  uint8_t historyCount;
  uint8_t historyIndex;
  uint8_t consecutiveErrors;  // Saturates at 255; diagnostic only, not in CSV.
  bool valid;
};

// Validate editable link settings before configuring any outputs. Multiple
// zones may map to one camera, but outputs must be distinct and avoid the
// sensor bus, alarm, heartbeat and serial pins. Return false on a conflict.
bool cameraLinkSettingsValid() {
  for (uint8_t i = 0; i < CameraLink::kCameraCount; ++i) {
    const uint8_t pin = CameraLink::kOutputPins[i];
    if (pin >= NUM_DIGITAL_PINS || pin == Design::kDisabledOutputPin ||
        pin == 0 || pin == 1 ||
        pin == SDA || pin == SCL || pin == Config::kAlarmPin ||
        pin == Config::kHeartbeatPin) {
      return false;
    }
    for (uint8_t j = 0; j < i; ++j) {
      if (pin == CameraLink::kOutputPins[j]) {
        return false;
      }
    }
  }
  for (uint8_t i = 0; i < Config::kSensorCount; ++i) {
    if (CameraLink::kCameraForSensor[i] < 1 ||
        CameraLink::kCameraForSensor[i] > CameraLink::kCameraCount) {
      return false;
    }
  }
  return true;
}

// Start all camera transistors OFF. Preload LOW before enabling each output
// to avoid a deliberate startup warning. External base pull-downs cover reset.
void setupCameraLink() {
  for (uint8_t i = 0; i < CameraLink::kCameraCount; ++i) {
    digitalWrite(CameraLink::kOutputPins[i], LOW);
    pinMode(CameraLink::kOutputPins[i], OUTPUT);
  }
}

// Publish a held one-of-four selection after a scan. Invalid/no-warning input
// clears all outputs. Turn the old selection OFF before enabling a new one;
// the receiver debounces the short gap. Repeated selections produce no writes.
void publishCameraWarning(int8_t nearestSensor, bool warning) {
  static uint8_t previousCamera = 0;
  uint8_t camera = 0;
  if (warning && nearestSensor >= 0 && nearestSensor < Config::kSensorCount) {
    camera = CameraLink::kCameraForSensor[nearestSensor];
  }
  if (camera == previousCamera) {
    return;
  }
  for (uint8_t i = 0; i < CameraLink::kCameraCount; ++i) {
    digitalWrite(CameraLink::kOutputPins[i], LOW);
  }
  if (camera != 0) {
    digitalWrite(CameraLink::kOutputPins[camera - 1], HIGH);
  }
  previousCamera = camera;
}

SensorState sensors[Config::kSensorCount] = {};  // All readings initially invalid.

// START -> WAIT -> finishCurrentSensor() -> GUARD -> START of next sensor.
// A failed trigger skips WAIT. A CSV row is published after the fourth attempt.
enum class PollPhase : uint8_t {
  kStartMeasurement,
  kWaitForMeasurement,
  kGuardTime,
};

PollPhase pollPhase = PollPhase::kStartMeasurement;
uint8_t currentSensor = 0;
uint32_t phaseDeadlineMs = 0;
uint32_t heartbeatDeadlineMs = 0;
bool heartbeatState = false;

// DEADLINES AND I2C: select one sensor, trigger it, then read its result.
// Return whether a millis() deadline has elapsed, including counter wraparound.
// Intervals and time between servicing must remain below 2^31 milliseconds.
bool deadlineReached(uint32_t now, uint32_t deadline) {
  return static_cast<int32_t>(now - deadline) >= 0;
}

// Enable exactly one physical mux channel (0..7); return false on invalid input
// or an I2C write error. This changes which sensor is connected to the bus.
bool selectMuxChannel(uint8_t channel) {
  if (channel >= Design::kMuxChannelCount) {
    return false;
  }

  Wire.beginTransmission(Config::kMuxAddress);
  Wire.write(static_cast<uint8_t>(1U << channel));
  return Wire.endTransmission() == 0;
}

// Request isolation of all sensors. The I2C result is intentionally not checked;
// a failed mux write can leave a channel enabled until a later successful write.
void disableAllMuxChannels() {
  Wire.beginTransmission(Config::kMuxAddress);
  Wire.write(static_cast<uint8_t>(0));
  Wire.endTransmission();
}

// Select a logical sensor index (0..kSensorCount-1) and send one-shot trigger.
// Return true only when both writes succeed; conversion is waited for elsewhere.
bool startRanging(uint8_t sensorIndex) {
  if (!selectMuxChannel(Config::kMuxChannels[sensorIndex])) {
    return false;
  }

  Wire.beginTransmission(Config::kSensorAddress);
  Wire.write(Design::kStartMeasurementCommand);
  return Wire.endTransmission() == 0;
}

// Read the already-selected sensor after conversion. Return true and assign
// distanceMm only for a complete, in-range result; leave the output unchanged
// on failure. Fractional millimetres are discarded during integer conversion.
bool readDistanceMm(uint16_t &distanceMm) {
  const uint8_t received = Wire.requestFrom(
      Config::kSensorAddress, Design::kDistanceByteCount);

  if (received != Design::kDistanceByteCount ||
      Wire.available() < Design::kDistanceByteCount) {
    while (Wire.available() > 0) {
      Wire.read();
    }
    return false;
  }

  const uint32_t rawMicrometres =
      (static_cast<uint32_t>(Wire.read()) << 16) |
      (static_cast<uint32_t>(Wire.read()) << 8) |
      static_cast<uint32_t>(Wire.read());

  const uint32_t measuredMm =
      rawMicrometres / Design::kMicrometresPerMillimetre;
  if (measuredMm < Config::kMinimumDistanceMm ||
      measuredMm > Config::kMaximumDistanceMm) {
    return false;
  }

  distanceMm = static_cast<uint16_t>(measuredMm);
  return true;
}

// FILTERING AND VALIDITY: successful history is separate from current validity.
// Read-only filter: return 0 for no samples, the sole sample for one, the
// integer average for two, or the median of the last three successful samples.
// This sorting implementation is deliberately fixed to a three-sample window.
uint16_t medianOfHistory(const SensorState &sensor) {
  if (sensor.historyCount == 0) {
    return 0;
  }

  if (sensor.historyCount == 1) {
    return sensor.historyMm[0];
  }

  if (sensor.historyCount == 2) {
    return static_cast<uint16_t>(
        (static_cast<uint32_t>(sensor.historyMm[0]) +
         sensor.historyMm[1]) /
        2UL);
  }

  uint16_t a = sensor.historyMm[0];
  uint16_t b = sensor.historyMm[1];
  uint16_t c = sensor.historyMm[2];

  if (a > b) {
    const uint16_t temporary = a;
    a = b;
    b = temporary;
  }
  if (b > c) {
    const uint16_t temporary = b;
    b = c;
    c = temporary;
  }
  if (a > b) {
    const uint16_t temporary = a;
    a = b;
    b = temporary;
  }

  return b;
}

// Store one accepted mm value for a logical index, refresh its filtered value,
// clear its error count, and mark it valid. Older successful history is reused
// even after failed attempts, so the first recovered output can include it.
void recordSuccessfulReading(uint8_t sensorIndex, uint16_t distanceMm) {
  SensorState &sensor = sensors[sensorIndex];
  sensor.historyMm[sensor.historyIndex] = distanceMm;
  sensor.historyIndex = static_cast<uint8_t>(
      (sensor.historyIndex + 1) % Design::kHistorySize);

  if (sensor.historyCount < Design::kHistorySize) {
    ++sensor.historyCount;
  }

  sensor.filteredDistanceMm = medianOfHistory(sensor);
  sensor.consecutiveErrors = 0;
  sensor.valid = true;
}

// Invalidate a logical sensor immediately and increment its diagnostic error
// count. Retain its last filtered distance and history; neither is published
// while invalid. This does not update the alarm until the scan is completed.
void recordFailedReading(uint8_t sensorIndex) {
  SensorState &sensor = sensors[sensorIndex];
  if (sensor.consecutiveErrors < 255) {
    ++sensor.consecutiveErrors;
  }

  // Exclude this sensor until a later successful attempt.
  sensor.valid = false;
}

// Return the valid sensor index with the smallest filtered distance, or -1 if
// none are valid. Equal distances choose the earlier configured zone. No writes.
int8_t findNearestSensor() {
  int8_t nearest = -1;

  for (uint8_t i = 0; i < Config::kSensorCount; ++i) {
    if (!sensors[i].valid) {
      continue;
    }

    if (nearest < 0 ||
        sensors[i].filteredDistanceMm <
            sensors[static_cast<uint8_t>(nearest)].filteredDistanceMm) {
      nearest = static_cast<int8_t>(i);
    }
  }

  return nearest;
}

// OUTPUTS: one alarm decision and CSV row per completed four-sensor scan.
// Drive the configured alarm level for active/inactive, respecting polarity.
// A disabled pin has no effect; this function does not decide alarm conditions.
void setAlarm(bool active) {
  if (Config::kAlarmPin == Design::kDisabledOutputPin) {
    return;
  }

  const uint8_t activeLevel = Config::kAlarmActiveHigh ? HIGH : LOW;
  const uint8_t inactiveLevel = Config::kAlarmActiveHigh ? LOW : HIGH;
  digitalWrite(Config::kAlarmPin, active ? activeLevel : inactiveLevel);
}

// Print one CSV distance field: filtered integer mm, or -1 when invalid.
// Does not print a delimiter or line ending, and does not alter sensor state.
void printDistanceOrInvalid(const SensorState &sensor) {
  if (sensor.valid) {
    Serial.print(sensor.filteredDistanceMm);
  } else {
    Serial.print(F("-1"));
  }
}

// Find the nearest filtered reading, update the alarm, and print one CSV row.
// Alarm changes occur once per complete scan, not at each individual reading.
// NO_VALID_SENSORS turns the alarm OFF; sensor failure has no separate alarm.
// CLEAR can include failed sensors if all remaining valid readings are distant.
// The four measurements were collected sequentially, not simultaneously.
void publishCompletedScan() {
  const int8_t nearest = findNearestSensor();
  const bool warning =
      nearest >= 0 &&
      sensors[static_cast<uint8_t>(nearest)].filteredDistanceMm <=
          Config::kWarningDistanceMm;
  const bool critical =
      nearest >= 0 &&
      sensors[static_cast<uint8_t>(nearest)].filteredDistanceMm <=
          Config::kCriticalDistanceMm;

  setAlarm(warning);
  publishCameraWarning(nearest, warning);

  Serial.print(millis());
  for (uint8_t i = 0; i < Config::kSensorCount; ++i) {
    Serial.print(',');
    printDistanceOrInvalid(sensors[i]);
  }

  Serial.print(',');
  if (nearest >= 0) {
    Serial.print(Config::kZoneLabels[static_cast<uint8_t>(nearest)]);
  } else {
    Serial.print(F("none"));
  }

  Serial.print(',');
  if (nearest >= 0) {
    Serial.print(sensors[static_cast<uint8_t>(nearest)].filteredDistanceMm);
  } else {
    Serial.print(F("-1"));
  }

  Serial.print(',');
  if (critical) {
    Serial.println(F("CRITICAL"));
  } else if (warning) {
    Serial.println(F("WARNING"));
  } else if (nearest >= 0) {
    Serial.println(F("CLEAR"));
  } else {
    Serial.println(F("NO_VALID_SENSORS"));
  }
}

// SCHEDULER: loop() repeatedly services these short polling/heartbeat steps.
// Close this sensor attempt: disable the mux, publish if it was the last zone,
// advance the index, and schedule the guard interval from the supplied millis().
void finishCurrentSensor(uint32_t now) {
  disableAllMuxChannels();

  if (currentSensor == Config::kSensorCount - 1) {
    publishCompletedScan();
  }

  currentSensor = static_cast<uint8_t>(
      (currentSensor + 1) % Config::kSensorCount);
  pollPhase = PollPhase::kGuardTime;
  phaseDeadlineMs = now + Config::kInterSensorGuardMs;
}

// Advance at most one polling phase using the supplied millis() timestamp.
// Conversion/guard waits use deadlines, but Wire and Serial calls can still
// block; this sketch configures no board-specific I2C timeout or recovery.
void serviceSensorPolling(uint32_t now) {
  switch (pollPhase) {
    case PollPhase::kStartMeasurement:
      if (startRanging(currentSensor)) {
        phaseDeadlineMs = now + Config::kMeasurementTimeMs;
        pollPhase = PollPhase::kWaitForMeasurement;
      } else {
        recordFailedReading(currentSensor);
        finishCurrentSensor(now);
      }
      break;

    case PollPhase::kWaitForMeasurement:
      if (deadlineReached(now, phaseDeadlineMs)) {
        uint16_t distanceMm = 0;
        if (readDistanceMm(distanceMm)) {
          recordSuccessfulReading(currentSensor, distanceMm);
        } else {
          recordFailedReading(currentSensor);
        }
        finishCurrentSensor(now);
      }
      break;

    case PollPhase::kGuardTime:
      if (deadlineReached(now, phaseDeadlineMs)) {
        pollPhase = PollPhase::kStartMeasurement;
      }
      break;
  }
}

// Toggle the enabled heartbeat output when due, then schedule from now.
// Shows that loop() is running, not that measurements are valid. Missed toggles
// are not replayed; default zero deadline means the first loop drives the pin HIGH.
void serviceHeartbeat(uint32_t now) {
  if (Config::kHeartbeatPin == Design::kDisabledOutputPin) {
    return;
  }
  if (!deadlineReached(now, heartbeatDeadlineMs)) {
    return;
  }

  heartbeatState = !heartbeatState;
  digitalWrite(Config::kHeartbeatPin, heartbeatState ? HIGH : LOW);
  heartbeatDeadlineMs = now + Config::kHeartbeatToggleMs;
}

// ARDUINO ENTRY POINTS.
// Arduino startup: configure outputs and buses, request mux isolation, and
// print the CSV header once. No sensor availability check is made here.
void setup() {
  Serial.begin(Config::kSerialBaud);
  if (!cameraLinkSettingsValid()) {
    Serial.println(F("ERROR: check CameraLink pins and sensor-to-camera map"));
    // Configuration error: halt before touching GPIO or starting measurements.
    while (true) {}
  }
  setupCameraLink();
  if (Config::kHeartbeatPin != Design::kDisabledOutputPin) {
    pinMode(Config::kHeartbeatPin, OUTPUT);
  }
  if (Config::kAlarmPin != Design::kDisabledOutputPin) {
    pinMode(Config::kAlarmPin, OUTPUT);
  }
  setAlarm(false);

  Wire.begin();
  Wire.setClock(Config::kI2cClockHz);

  disableAllMuxChannels();

  Serial.print(F("time_ms"));
  for (uint8_t i = 0; i < Config::kSensorCount; ++i) {
    Serial.print(',');
    Serial.print(Config::kZoneLabels[i]);
    Serial.print(F("_mm"));
  }
  Serial.println(F(",nearest_zone,nearest_mm,state"));
}

// Arduino main loop: sample the clock once and service polling and heartbeat.
// Add independent work here only if it returns promptly on every invocation.
void loop() {
  const uint32_t now = millis();
  serviceSensorPolling(now);
  serviceHeartbeat(now);

  // Add other non-blocking application work here, such as motor control,
  // communications, or a display update. Avoid delay().
}
