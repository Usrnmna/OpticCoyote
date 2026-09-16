#include <Wire.h>

/*
  Four RCWL-1655 ultrasonic sensors through a TCA9548A I2C multiplexer.

  Target: Arduino-compatible board using the standard Wire library.
  RCWL-1655 I2C address: 0x57 (fixed)
  TCA9548A default address: 0x70

  Each RCWL-1655 must be placed in I2C mode (R7 = 100 kOhm):
    RCWL Trig/RX/SCL pin -> TCA9548A channel SCL
    RCWL Echo/TX/SDA pin -> TCA9548A channel SDA

  Serial output is one CSV record per completed four-sensor scan.
*/

namespace Config {
constexpr uint8_t kMuxAddress = 0x70;
constexpr uint8_t kSensorAddress = 0x57;
constexpr uint8_t kSensorCount = 4;

// Sensor channels on the TCA9548A. Change these if different mux ports are used.
constexpr uint8_t kMuxChannels[kSensorCount] = {0, 1, 2, 3};

// The datasheet allows up to 100 ms for a one-shot measurement.
constexpr uint16_t kMeasurementTimeMs = 100;
constexpr uint8_t kInterSensorGuardMs = 5;

// Expected usable RCWL-1655 range for this installation.
constexpr uint16_t kMinimumDistanceMm = 200;
constexpr uint16_t kMaximumDistanceMm = 5000;

// Object-detection thresholds. Tune these for the actual machine/vehicle.
constexpr uint16_t kWarningDistanceMm = 600;
constexpr uint16_t kCriticalDistanceMm = 300;

// Set to 255 if no alarm output is required.
constexpr uint8_t kAlarmPin = 8;
constexpr bool kAlarmActiveHigh = true;

constexpr uint32_t kSerialBaud = 115200;
}  // namespace Config

struct SensorState {
  const char *zone;
  uint16_t historyMm[3];
  uint16_t filteredDistanceMm;
  uint8_t historyCount;
  uint8_t historyIndex;
  uint8_t consecutiveErrors;
  bool valid;
};

SensorState sensors[Config::kSensorCount] = {
    {"front_left", {0, 0, 0}, 0, 0, 0, 0, false},
    {"front_right", {0, 0, 0}, 0, 0, 0, 0, false},
    {"rear_left", {0, 0, 0}, 0, 0, 0, 0, false},
    {"rear_right", {0, 0, 0}, 0, 0, 0, 0, false},
};

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

bool deadlineReached(uint32_t now, uint32_t deadline) {
  return static_cast<int32_t>(now - deadline) >= 0;
}

bool selectMuxChannel(uint8_t channel) {
  if (channel > 7) {
    return false;
  }

  Wire.beginTransmission(Config::kMuxAddress);
  Wire.write(static_cast<uint8_t>(1U << channel));
  return Wire.endTransmission() == 0;
}

void disableAllMuxChannels() {
  Wire.beginTransmission(Config::kMuxAddress);
  Wire.write(static_cast<uint8_t>(0));
  Wire.endTransmission();
}

bool startRanging(uint8_t sensorIndex) {
  if (!selectMuxChannel(Config::kMuxChannels[sensorIndex])) {
    return false;
  }

  Wire.beginTransmission(Config::kSensorAddress);
  Wire.write(static_cast<uint8_t>(0x01));
  return Wire.endTransmission() == 0;
}

bool readDistanceMm(uint16_t &distanceMm) {
  const uint8_t received = Wire.requestFrom(
      Config::kSensorAddress, static_cast<uint8_t>(3));

  if (received != 3 || Wire.available() < 3) {
    while (Wire.available() > 0) {
      Wire.read();
    }
    return false;
  }

  const uint32_t rawMicrometres =
      (static_cast<uint32_t>(Wire.read()) << 16) |
      (static_cast<uint32_t>(Wire.read()) << 8) |
      static_cast<uint32_t>(Wire.read());

  const uint32_t measuredMm = rawMicrometres / 1000UL;
  if (measuredMm < Config::kMinimumDistanceMm ||
      measuredMm > Config::kMaximumDistanceMm) {
    return false;
  }

  distanceMm = static_cast<uint16_t>(measuredMm);
  return true;
}

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

void recordSuccessfulReading(uint8_t sensorIndex, uint16_t distanceMm) {
  SensorState &sensor = sensors[sensorIndex];
  sensor.historyMm[sensor.historyIndex] = distanceMm;
  sensor.historyIndex = static_cast<uint8_t>((sensor.historyIndex + 1) % 3);

  if (sensor.historyCount < 3) {
    ++sensor.historyCount;
  }

  sensor.filteredDistanceMm = medianOfHistory(sensor);
  sensor.consecutiveErrors = 0;
  sensor.valid = true;
}

void recordFailedReading(uint8_t sensorIndex) {
  SensorState &sensor = sensors[sensorIndex];
  if (sensor.consecutiveErrors < 255) {
    ++sensor.consecutiveErrors;
  }

  // Do not make object decisions using a stale reading.
  sensor.valid = false;
}

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

void setAlarm(bool active) {
  if (Config::kAlarmPin == 255) {
    return;
  }

  const uint8_t activeLevel = Config::kAlarmActiveHigh ? HIGH : LOW;
  const uint8_t inactiveLevel = Config::kAlarmActiveHigh ? LOW : HIGH;
  digitalWrite(Config::kAlarmPin, active ? activeLevel : inactiveLevel);
}

void printDistanceOrInvalid(const SensorState &sensor) {
  if (sensor.valid) {
    Serial.print(sensor.filteredDistanceMm);
  } else {
    Serial.print(F("-1"));
  }
}

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

  Serial.print(millis());
  for (uint8_t i = 0; i < Config::kSensorCount; ++i) {
    Serial.print(',');
    printDistanceOrInvalid(sensors[i]);
  }

  Serial.print(',');
  if (nearest >= 0) {
    Serial.print(sensors[static_cast<uint8_t>(nearest)].zone);
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

void serviceHeartbeat(uint32_t now) {
  if (!deadlineReached(now, heartbeatDeadlineMs)) {
    return;
  }

  heartbeatState = !heartbeatState;
  digitalWrite(LED_BUILTIN, heartbeatState ? HIGH : LOW);
  heartbeatDeadlineMs = now + 500;
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  if (Config::kAlarmPin != 255) {
    pinMode(Config::kAlarmPin, OUTPUT);
  }
  setAlarm(false);

  Serial.begin(Config::kSerialBaud);
  Wire.begin();
  Wire.setClock(100000UL);

  disableAllMuxChannels();

  Serial.println(F("time_ms,front_left_mm,front_right_mm,rear_left_mm,"
                   "rear_right_mm,nearest_zone,nearest_mm,state"));
}

void loop() {
  const uint32_t now = millis();
  serviceSensorPolling(now);
  serviceHeartbeat(now);

  // Add other non-blocking application work here, such as motor control,
  // communications, or a display update. Avoid delay().
}
