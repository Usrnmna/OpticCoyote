#include <Wire.h>
#include <string.h>
#include <stdio.h>
#include "reverse_config.h"

/*
  Four RCWL-1655 or compatible AJ-SR04M I2C ultrasonic sensors through a
  TCA9548A multiplexer. Either type may occupy any channel.

  AJ-SR04M compatibility requires address 0x57, trigger byte 0x01, and a
  three-byte big-endian micrometre result. Verify the exact board's I2C mode,
  pin labels, voltage, timing, and range; model name alone is insufficient.
  Both types use the same polling, cooldown, filtering, and USB operations.

  Target: Arduino-compatible board using the standard Wire library.
  RCWL-1655 I2C address: 0x57 (fixed)
  TCA9548A default address: 0x70

  Each RCWL-1655 must be placed in I2C mode (R7 = 100 kOhm):
    RCWL Trig/RX/SCL pin -> TCA9548A channel SCL
    RCWL Echo/TX/SDA pin -> TCA9548A channel SDA

  Reverse mode boots with ranging disabled and accepts session-tagged R/K/X
  acquisition commands at 115200 baud, 8N1. reverse_config.h selects the mode.
  Standalone mode ranges continuously; START/STOP control its legacy CSV output.
  Pending updates merge while a previous packet is still being queued.
  Start manual review with Config, then serviceSensorPolling(), then
  serviceSerialOutput(). Function comments describe inputs and side effects.
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
constexpr uint16_t kSerialPacketCapacity = 192;
}  // namespace Design

// INSTALLATION SETTINGS: edit this section, then rebuild/upload the sketch.
namespace Config {
// POLLING INTERVAL (milliseconds): requested minimum time between scan starts.
// EDIT HERE to change the requested rate. 400 ms is about 2.5 scans/second.
// HARDWARE LIMIT: four sequential I2C conversions need about 400 ms.
// Faster requested intervals cannot shorten conversions; scans never overlap
// and old scans are never retransmitted to imitate a faster measurement rate.
constexpr uint32_t kPollingIntervalMs = 400;

// I2C addresses are 7-bit. The sensor address is fixed for the RCWL-1655;
// change the mux address only to match its physical A0/A1/A2 address straps.
constexpr uint8_t kMuxAddress = 0x70;
constexpr uint8_t kSensorAddress = 0x57;
constexpr uint32_t kI2cClockHz = 100000UL;

// Fixed four-zone project layout, not a sensor-count tuning option.
constexpr uint8_t kSensorCount = 4;

// Matching indexes define the zone, physical mux port, and CSV column order.
// Channels must be distinct, in 0..7. Labels must be nonempty and contain no
// commas/newlines and at most 23 characters to fit the serial packet buffer.
// Renaming a label changes its CSV header and nearest_zone.
// The Pi OLED bridge maps these four column positions to rear-bumper sensors
// 1..4 left to right. The legacy labels below do not set their physical location;
// see docs/oled-display.md for the bridge's adjustable cable mapping.
constexpr uint8_t kMuxChannels[] = {0, 1, 2, 3};
const char *const kZoneLabels[] = {
    "front_left", "front_right", "rear_left", "rear_right"};

// Milliseconds: wait for one I2C measurement.
// I2C mode requires at least 100 ms after each trigger (datasheet page 5).
constexpr uint16_t kMeasurementTimeMs = 100;
// Mandatory cooldown before retriggering the SAME sensor; USB never waits for it.
// Other sensors may trigger while this sensor cools down. The module itself
// generates the 40 kHz acoustic burst; this is not the I2C clock.
constexpr uint8_t kSensorCooldownMs = 10;

// Inclusive accepted range in mm. Samples outside it are invalid, not clipped.
constexpr uint16_t kMinimumDistanceMm = 200;
constexpr uint16_t kMaximumDistanceMm = 5000;

// Inclusive thresholds in mm, applied to filtered readings after each attempt.
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
static_assert(Config::kMeasurementTimeMs >= 100 && Config::kI2cClockHz > 0 &&
                  Config::kSerialBaud > 0,
              "RCWL-1655 I2C wait must be >=100 ms; bus/serial rates positive");
static_assert(Config::kSensorCooldownMs >= 10,
              "Allow at least 10 ms after reading before retriggering that sensor");
static_assert(Config::kHeartbeatToggleMs > 0 &&
                  Config::kHeartbeatToggleMs < 0x80000000UL,
              "Heartbeat interval must be positive and fit deadline arithmetic");
static_assert(Config::kPollingIntervalMs > 0 &&
                  Config::kPollingIntervalMs < 0x80000000UL,
              "Polling interval must be positive and fit deadline arithmetic");
static_assert(Config::kAlarmPin == Design::kDisabledOutputPin ||
                  Config::kHeartbeatPin == Design::kDisabledOutputPin ||
                  Config::kAlarmPin != Config::kHeartbeatPin,
              "Alarm and heartbeat must use different enabled pins");

// RUNTIME STATE: no user settings below this point.
// History/cache survive failures within one session. Reverse reports require a
// valid, fresh latest attempt; standalone CSV can retain the last-good cache.
struct SensorState {
  uint16_t historyMm[Design::kHistorySize];
  uint16_t latestDistanceMm;  // Fresh sample for USB; filtering is alarm-only.
  uint16_t filteredDistanceMm;
  uint8_t historyCount;
  uint8_t historyIndex;
  uint8_t consecutiveErrors;  // Saturates at 255; diagnostic only, not in CSV.
  bool valid;
  uint32_t cooldownDeadlineMs;
  bool coolingDown;
  uint32_t lastSuccessMs;
};

SensorState sensors[Config::kSensorCount] = {};  // All readings initially invalid.

// START -> WAIT -> finishCurrentSensor() -> START of next sensor.
// A failed trigger skips WAIT. Every successful read publishes independently.
enum class PollPhase : uint8_t {
  kStartMeasurement,
  kWaitForMeasurement,
};

PollPhase pollPhase = PollPhase::kStartMeasurement;
uint8_t currentSensor = 0;
uint32_t phaseDeadlineMs = 0;
uint32_t heartbeatDeadlineMs = 0;
bool heartbeatState = false;
bool streamingEnabled = false;
uint32_t nextScanDeadlineMs = 0;
char serialCommand[32] = {};  // Full acquisition command; no dynamic allocation.
uint8_t serialCommandLength = 0;
bool discardSerialCommand = false;

// Main-loop-owned TX state: immutable in-flight bytes plus latest pending data.
// These are not ISR-safe; a future echo ISR must hand samples to the main loop.
char serialPacket[Design::kSerialPacketCapacity] = {};
uint16_t serialPacketLength = 0;
uint16_t serialPacketOffset = 0;
bool serialHeaderPending = false;
bool serialReadingPending = false;
bool serialPacketIsCurrentData = false;
bool haveSentDistances = false;
int32_t packetDistances[Config::kSensorCount] = {};
int32_t sentDistances[Config::kSensorCount] = {};

bool acquisitionEnabled = false;
uint32_t reverseSessionToken = 0;
uint32_t retiredReverseSessionToken = 0;  // Last stopped/replaced session.
uint32_t reverseRequestId = 0;  // Latest strictly increasing K request; R uses zero.
uint32_t reverseSessionStartedMs = 0;
uint32_t reverseLeaseMs = 0;
uint32_t reverseLeaseDeadlineMs = 0;
uint32_t nextReverseReportMs = 0;
bool restartGuardActive = false;
uint32_t restartGuardDeadlineMs = 0;


// DEADLINES AND I2C: select one sensor, trigger it, then read its result.
// Return whether a millis() deadline has elapsed, including counter wraparound.
// Intervals and time between servicing must remain below 2^31 milliseconds.
bool deadlineReached(uint32_t now, uint32_t deadline) {
  return static_cast<int32_t>(now - deadline) >= 0;
}

// Recheck between bounded I2C operations so an expired lease cannot authorize
// another trigger after a slow mux transaction.
bool acquisitionPermitted(uint32_t now) {
  return !ReverseConfig::kEnabled ||
      (acquisitionEnabled && !deadlineReached(now, reverseLeaseDeadlineMs));
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
  if (!acquisitionPermitted(millis())) return false;

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
// clear its error count, and mark it valid. Reverse mode discards expired filter
// history before recovery so old values cannot regain freshness in the alarm.
// Standalone mode retains its original successful-history filtering behavior.
void recordSuccessfulReading(uint8_t sensorIndex, uint16_t distanceMm) {
  SensorState &sensor = sensors[sensorIndex];
  const uint32_t now = millis();
  if (ReverseConfig::kEnabled && sensor.historyCount &&
      static_cast<uint32_t>(now - sensor.lastSuccessMs) >= ReverseConfig::kStaleMs) {
    sensor.historyCount = 0;
    sensor.historyIndex = 0;
  }
  sensor.latestDistanceMm = distanceMm;
  sensor.historyMm[sensor.historyIndex] = distanceMm;
  sensor.historyIndex = static_cast<uint8_t>(
      (sensor.historyIndex + 1) % Design::kHistorySize);

  if (sensor.historyCount < Design::kHistorySize) {
    ++sensor.historyCount;
  }

  sensor.filteredDistanceMm = medianOfHistory(sensor);
  sensor.consecutiveErrors = 0;
  sensor.valid = true;
  sensor.lastSuccessMs = now;
  if (!ReverseConfig::kEnabled && streamingEnabled) serialReadingPending = true;
}

// Invalidate a logical sensor immediately and increment its diagnostic error
// count. Retain filter history and the standalone CSV cache. Reverse snapshots
// mark the sensor unavailable until a new success; alarms exclude it immediately.
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
    if (!sensors[i].valid || (ReverseConfig::kEnabled &&
        static_cast<uint32_t>(millis() - sensors[i].lastSuccessMs) >= ReverseConfig::kStaleMs)) {
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

// OUTPUTS: update alarms and transmit mode-specific snapshots without blocking.
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

// Return a cached raw distance, or -1 until this sensor first succeeds.
int32_t cachedDistance(uint8_t index) {
  return sensors[index].historyCount ? static_cast<int32_t>(sensors[index].latestDistanceMm) : -1;
}

// Update the alarm independently of serial progress, excluding expired leases
// and stale reverse samples as well as failed attempts.
void updateAlarm() {
  if (ReverseConfig::kEnabled && !acquisitionPermitted(millis())) {
    setAlarm(false);
    return;
  }
  const int8_t nearest = findNearestSensor();
  setAlarm(nearest >= 0 &&
           sensors[static_cast<uint8_t>(nearest)].filteredDistanceMm <=
               Config::kWarningDistanceMm);
}

// Retain the latest physical conversion/cooldown deadline across cache resets.
// A stopped conversion cannot be cancelled acoustically; its result is ignored.
void retainRestartGuard(uint32_t now, uint32_t deadline) {
  if (deadlineReached(now, deadline)) return;
  if (!restartGuardActive || deadlineReached(now, restartGuardDeadlineMs) ||
      static_cast<uint32_t>(deadline - now) >
          static_cast<uint32_t>(restartGuardDeadlineMs - now)) {
    restartGuardActive = true;
    restartGuardDeadlineMs = deadline;
  }
}

// Revoke acquisition, clear histories, silence the alarm, and isolate the mux.
// Keep a partially queued packet intact through its newline. Its session token
// allows the host to reject delayed bytes after the reverse view is released.
void stopReverseAcquisition() {
  const uint32_t now = millis();
  if (acquisitionEnabled) retiredReverseSessionToken = reverseSessionToken;
  if (pollPhase == PollPhase::kWaitForMeasurement) {
    retainRestartGuard(now, phaseDeadlineMs + Config::kSensorCooldownMs);
  }
  for (uint8_t i = 0; i < Config::kSensorCount; ++i) {
    if (sensors[i].coolingDown) retainRestartGuard(now, sensors[i].cooldownDeadlineMs);
  }
  acquisitionEnabled = false;
  streamingEnabled = false;
  memset(sensors, 0, sizeof(sensors));
  pollPhase = PollPhase::kStartMeasurement;
  currentSensor = 0;
  serialHeaderPending = serialReadingPending = serialPacketIsCurrentData = false;
  haveSentDistances = false;
  if (serialPacketOffset == 0) serialPacketLength = 0;
  setAlarm(false);
  disableAllMuxChannels();
}

// Start a fresh session only. Repeated or retired tokens neither reset history
// nor renew a lease; renewal requires an explicit K command while still active.
void startReverseAcquisition(uint32_t token, uint32_t leaseMs) {
  if (token == reverseSessionToken || token == retiredReverseSessionToken) return;
  stopReverseAcquisition();
  const uint32_t now = millis();
  reverseSessionToken = token;
  reverseRequestId = 0;
  reverseSessionStartedMs = now;
  reverseLeaseMs = leaseMs;
  reverseLeaseDeadlineMs = now + leaseMs;
  nextScanDeadlineMs = nextReverseReportMs = now;
  acquisitionEnabled = true;
}

// Parse unsigned decimal fields without accepting signs, whitespace, overflow,
// omitted digits, or extra fields. The cursor remains at the required separator.
bool parseUnsignedField(const char *&cursor, uint32_t &value) {
  value = 0;
  if (*cursor < '0' || *cursor > '9') return false;
  while (*cursor >= '0' && *cursor <= '9') {
    const uint8_t digit = static_cast<uint8_t>(*cursor - '0');
    if (value > (UINT32_MAX - digit) / 10UL) return false;
    value = value * 10UL + digit;
    ++cursor;
  }
  return true;
}

// Apply one complete command. Legacy START/STOP never enable reverse ranging.
// A renewal arriving at or after expiry cannot resurrect the expired session.
// K includes a strictly increasing nonzero request identifier. Replayed requests
// do not extend a lease; snapshots echo the identifier frozen when prepared.
void handleReverseCommand(const char *command) {
  if (acquisitionEnabled && deadlineReached(millis(), reverseLeaseDeadlineMs)) {
    stopReverseAcquisition();
  }
  if (strcmp(command, "X") == 0) {
    stopReverseAcquisition();
    return;
  }
  if ((command[0] != 'R' && command[0] != 'K') || command[1] != ',') return;
  const char *cursor = command + 2;
  uint32_t token = 0;
  if (!parseUnsignedField(cursor, token) || token == 0) return;
  if (command[0] == 'K') {
    if (*cursor++ != ',') return;
    uint32_t requestId = 0;
    if (!parseUnsignedField(cursor, requestId) || *cursor != '\0' || requestId == 0) return;
    if (acquisitionEnabled && token == reverseSessionToken && requestId > reverseRequestId) {
      const uint32_t now = millis();
      // Parsing can straddle a timer tick. Recheck at the renewal decision,
      // rather than relying on the earlier command-entry expiry check.
      if (deadlineReached(now, reverseLeaseDeadlineMs)) {
        stopReverseAcquisition();
        return;
      }
      reverseRequestId = requestId;
      reverseLeaseDeadlineMs = now + reverseLeaseMs;
    }
    return;
  }
  if (*cursor++ != ',') return;
  uint32_t leaseMs = 0;
  if (!parseUnsignedField(cursor, leaseMs) || *cursor != '\0' ||
      leaseMs < ReverseConfig::kMinimumLeaseMs ||
      leaseMs > ReverseConfig::kMaximumLeaseMs) return;
  startReverseAcquisition(token, leaseMs);
}

// Freeze a complete session snapshot, including unavailable sensors and the
// last renewal request. Its echo bounds transport delay without synchronizing
// device clocks; elapsed time permits duplicate/backward packet detection.
void prepareReversePacket(uint32_t now) {
  int32_t distance[Config::kSensorCount];
  uint32_t age[Config::kSensorCount];
  for (uint8_t i = 0; i < Config::kSensorCount; ++i) {
    const uint32_t elapsed = now - sensors[i].lastSuccessMs;
    const bool fresh = sensors[i].valid && elapsed < ReverseConfig::kStaleMs;
    distance[i] = fresh ? sensors[i].latestDistanceMm : -1;
    age[i] = fresh ? elapsed : 0;
  }
  const int length = snprintf(serialPacket, sizeof(serialPacket),
      "S,%lu,%lu,%lu,%ld,%lu,%ld,%lu,%ld,%lu,%ld,%lu\r\n",
      static_cast<unsigned long>(reverseSessionToken),
      static_cast<unsigned long>(reverseRequestId),
      static_cast<unsigned long>(now - reverseSessionStartedMs),
      static_cast<long>(distance[0]), static_cast<unsigned long>(age[0]),
      static_cast<long>(distance[1]), static_cast<unsigned long>(age[1]),
      static_cast<long>(distance[2]), static_cast<unsigned long>(age[2]),
      static_cast<long>(distance[3]), static_cast<unsigned long>(age[3]));
  if (length <= 0 || static_cast<size_t>(length) >= sizeof(serialPacket)) return;
  serialPacketLength = static_cast<uint16_t>(length);
  serialPacketOffset = 0;
  serialPacketIsCurrentData = false;
  nextReverseReportMs = now + ReverseConfig::kReportIntervalMs;
}

// Compare distance values only, not the timestamp (which always changes).
bool distancesChangedSinceSend() {
  if (!haveSentDistances) return false;
  for (uint8_t i = 0; i < Config::kSensorCount; ++i) {
    if (cachedDistance(i) != sentDistances[i]) return true;
  }
  return false;
}

// Create a frozen header/data frame only after the preceding frame is queued.
// Never emit a truncated frame if installation labels exceed the buffer.
void prepareSerialPacket() {
  int length = 0;
  if (serialHeaderPending) {
    length = snprintf(serialPacket, sizeof(serialPacket),
        "time_ms,%s_mm,%s_mm,%s_mm,%s_mm,nearest_zone,nearest_mm,state\r\n",
        Config::kZoneLabels[0], Config::kZoneLabels[1],
        Config::kZoneLabels[2], Config::kZoneLabels[3]);
  } else {
    for (uint8_t i = 0; i < Config::kSensorCount; ++i) {
      packetDistances[i] = cachedDistance(i);
    }
    const int8_t nearest = findNearestSensor();
    const int32_t nearestMm = nearest < 0 ? -1 :
        static_cast<int32_t>(sensors[static_cast<uint8_t>(nearest)].filteredDistanceMm);
    const char *state = nearest < 0 ? "NO_VALID_SENSORS" :
        nearestMm <= Config::kCriticalDistanceMm ? "CRITICAL" :
        nearestMm <= Config::kWarningDistanceMm ? "WARNING" : "CLEAR";
    length = snprintf(serialPacket, sizeof(serialPacket),
        "%lu,%ld,%ld,%ld,%ld,%s,%ld,%s\r\n",
        static_cast<unsigned long>(millis()),
        static_cast<long>(packetDistances[0]), static_cast<long>(packetDistances[1]),
        static_cast<long>(packetDistances[2]), static_cast<long>(packetDistances[3]),
        nearest < 0 ? "none" : Config::kZoneLabels[static_cast<uint8_t>(nearest)],
        static_cast<long>(nearestMm), state);
  }
  if (length <= 0 || static_cast<size_t>(length) >= sizeof(serialPacket)) return;
  serialPacketIsCurrentData = !serialHeaderPending;
  if (serialHeaderPending) serialHeaderPending = false;
  else serialReadingPending = false;  // Consume only readings in THIS snapshot.
  serialPacketLength = static_cast<uint16_t>(length);
  serialPacketOffset = 0;
}

// Queue only bytes that fit now. A full UART buffer never blocks sensor polling.
// Completion acknowledges this snapshot, never any newer reading in the cache.
// "Sent" here means queued to the UART, not acknowledged by the USB host.
void serviceSerialOutput() {
  if (serialPacketLength == 0) {
    if (ReverseConfig::kEnabled) {
      const uint32_t now = millis();
      if (!acquisitionPermitted(now) || !deadlineReached(now, nextReverseReportMs)) return;
      prepareReversePacket(now);
    } else {
      if (!streamingEnabled || (!serialHeaderPending && !serialReadingPending &&
                               !distancesChangedSinceSend())) return;
      prepareSerialPacket();
    }
  }
  if (serialPacketLength == 0) return;
  const int capacity = Serial.availableForWrite();
  if (capacity <= 0) return;
  const uint16_t remaining = serialPacketLength - serialPacketOffset;
  const uint16_t count = capacity < remaining ? static_cast<uint16_t>(capacity) : remaining;
  serialPacketOffset += Serial.write(
      reinterpret_cast<const uint8_t *>(serialPacket + serialPacketOffset), count);
  if (serialPacketOffset != serialPacketLength) return;
  if (serialPacketIsCurrentData) {
    memcpy(sentDistances, packetDistances, sizeof(sentDistances));
    haveSentDistances = true;
  }
  serialPacketLength = serialPacketOffset = 0;
  serialPacketIsCurrentData = false;
}

// Accept complete acquisition or legacy commands terminated by CR, LF, or CRLF.
// Ignore unknown, binary, and oversized lines in full; a suffix cannot execute.
// Bound work per loop so a busy host cannot starve sensing.
void serviceSerialCommands() {
  for (uint8_t count = 0; count < 32 && Serial.available() > 0; ++count) {
    const char input = static_cast<char>(Serial.read());
    if (input == '\r' || input == '\n') {
      if (!discardSerialCommand) {
        serialCommand[serialCommandLength] = '\0';
        if (ReverseConfig::kEnabled) {
          handleReverseCommand(serialCommand);
        } else if (strcmp(serialCommand, "START") == 0 && !streamingEnabled) {
          streamingEnabled = true;
          serialHeaderPending = true;
          serialReadingPending = false;
          haveSentDistances = false;
        } else if (strcmp(serialCommand, "STOP") == 0) {
          streamingEnabled = false;
          serialHeaderPending = serialReadingPending = false;
          serialPacketIsCurrentData = false;
          haveSentDistances = false;
          // Finish a partially queued line to preserve CSV framing. Discard an
          // unstarted line; a later START puts its header after any old suffix.
          if (serialPacketOffset == 0) serialPacketLength = 0;
        }
      }
      serialCommandLength = 0;
      discardSerialCommand = false;
    } else if (!discardSerialCommand) {
      const bool permitted = (input >= 'A' && input <= 'Z') ||
          (ReverseConfig::kEnabled && ((input >= '0' && input <= '9') || input == ','));
      if (!permitted ||
          serialCommandLength >= sizeof(serialCommand) - 1) {
        discardSerialCommand = true;
      } else {
        serialCommand[serialCommandLength++] = input;
      }
    }
  }
}

// Cool only the sensor whose attempt ended, starting AFTER I2C completes.
// USB output and the next sensor are independent of this cooldown.
void finishCurrentSensor() {
  disableAllMuxChannels();
  sensors[currentSensor].cooldownDeadlineMs = millis() + Config::kSensorCooldownMs;
  sensors[currentSensor].coolingDown = true;
  updateAlarm();

  currentSensor = static_cast<uint8_t>(
      (currentSensor + 1) % Config::kSensorCount);
  pollPhase = PollPhase::kStartMeasurement;
}

// Advance at most one polling phase using the supplied millis() timestamp.
// Conversion/guard waits use deadlines. Supported Wire implementations bound
// bus operations with the timeout configured in setup().
void serviceSensorPolling(uint32_t now) {
  if (ReverseConfig::kEnabled) {
    if (!acquisitionPermitted(now)) {
      if (acquisitionEnabled) stopReverseAcquisition();
      return;
    }
    if (restartGuardActive) {
      if (!deadlineReached(now, restartGuardDeadlineMs)) return;
      restartGuardActive = false;
    }
  }
  switch (pollPhase) {
    case PollPhase::kStartMeasurement:
      if (sensors[currentSensor].coolingDown &&
          !deadlineReached(now, sensors[currentSensor].cooldownDeadlineMs)) {
        currentSensor = static_cast<uint8_t>((currentSensor + 1) % Config::kSensorCount);
        return;
      }
      sensors[currentSensor].coolingDown = false;
      if (currentSensor == 0) {
        if (!deadlineReached(now, nextScanDeadlineMs)) {
          return;
        }
        nextScanDeadlineMs = now + Config::kPollingIntervalMs;
      }
      if (startRanging(currentSensor)) {
        // Count the conversion wait after the trigger transaction finishes.
        phaseDeadlineMs = millis() + Config::kMeasurementTimeMs;
        pollPhase = PollPhase::kWaitForMeasurement;
      } else {
        recordFailedReading(currentSensor);
        finishCurrentSensor();
      }
      break;

    case PollPhase::kWaitForMeasurement:
      if (deadlineReached(now, phaseDeadlineMs)) {
        uint16_t distanceMm = 0;
        const bool readingReturned = readDistanceMm(distanceMm);
        if (!acquisitionPermitted(millis())) {
          retainRestartGuard(millis(), millis() + Config::kSensorCooldownMs);
          stopReverseAcquisition();
          return;
        }
        if (readingReturned) {
          recordSuccessfulReading(currentSensor, distanceMm);
        } else {
          recordFailedReading(currentSensor);
        }
        finishCurrentSensor();
      }
      break;
  }
  if (ReverseConfig::kEnabled && !acquisitionPermitted(millis())) stopReverseAcquisition();
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
// remain inactive until a reverse session (or silent until legacy START).
// No sensor availability check is made here.
void setup() {
  if (Config::kHeartbeatPin != Design::kDisabledOutputPin) {
    pinMode(Config::kHeartbeatPin, OUTPUT);
  }
  if (Config::kAlarmPin != Design::kDisabledOutputPin) {
    pinMode(Config::kAlarmPin, OUTPUT);
  }
  setAlarm(false);

  Serial.begin(Config::kSerialBaud);
  Wire.begin();
  Wire.setClock(Config::kI2cClockHz);
#if defined(WIRE_HAS_TIMEOUT)
  Wire.setWireTimeout(ReverseConfig::kI2cTimeoutUs, true);
#endif

  disableAllMuxChannels();
}

// Arduino main loop: sample the clock once and service polling and heartbeat.
// Add independent work here only if it returns promptly on every invocation.
void loop() {
  serviceSerialCommands();
  const uint32_t now = millis();
  serviceSensorPolling(now);
  if (ReverseConfig::kEnabled) updateAlarm();
  serviceHeartbeat(now);
  serviceSerialOutput();

  // Add other non-blocking application work here, such as motor control,
  // communications, or a display update. Avoid delay().
}
