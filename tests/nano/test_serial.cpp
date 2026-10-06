// Run against the actual .ino with simulated clocks, USB serial, and I2C.
// These tests do not establish physical sensor accuracy or USB timing.
#include "Wire.h"
#include <iostream>
#include <vector>
uint32_t fakeNow = 0;
FakeSerial Serial;
FakeWire Wire;
#include "../../optic_coyote_ultrasonic/optic_coyote_ultrasonic.ino"

void advance(uint32_t duration) {
  for (uint32_t i = 0; i < duration; ++i) { loop(); ++fakeNow; }
}

void command(const std::string &text) {
  Serial.send(text);
  advance(static_cast<uint32_t>(text.size() / 32 + 1));
}

std::vector<std::string> lines() {
  std::vector<std::string> result;
  std::istringstream stream(Serial.output);
  std::string line;
  while (std::getline(stream, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (!line.empty()) result.push_back(line);
  }
  return result;
}

std::vector<std::string> fields(const std::string &line) {
  std::vector<std::string> result;
  std::istringstream stream(line);
  std::string field;
  while (std::getline(stream, field, ',')) result.push_back(field);
  return result;
}

// Reset the simulation as if the board had rebooted.
void reset() {
  fakeNow = 0;
  Serial = FakeSerial{};
  Wire = FakeWire{};
  for (auto &sensor : sensors) sensor = SensorState{};
  pollPhase = PollPhase::kStartMeasurement;
  currentSensor = 0;
  phaseDeadlineMs = heartbeatDeadlineMs = nextScanDeadlineMs = 0;
  heartbeatState = streamingEnabled = discardSerialCommand = false;
  serialCommandLength = 0;
  serialPacketLength = serialPacketOffset = 0;
  serialHeaderPending = serialReadingPending = serialPacketIsCurrentData = haveSentDistances = false;
  setup();
}

// Each successful read must produce exactly one row in that same loop,
// including unchanged distances. Failed attempts must not produce data rows.
void checkPushes(uint32_t ticks) {
  for (uint32_t i = 0; i < ticks; ++i) {
    const auto before = lines().size();
    const unsigned reads = Wire.successfulReads;
    loop();
    assert(lines().size() - before == Wire.successfulReads - reads);
    if (Wire.successfulReads != reads) {
      const auto row = fields(lines().back());
      assert(row.size() == 8);
      for (int sensor = 0; sensor < 4; ++sensor) {
        const int cached = sensors[sensor].historyCount ? sensors[sensor].latestDistanceMm : -1;
        assert(std::stoi(row[sensor + 1]) == cached);
      }
    }
    ++fakeNow;
  }
}

int main() {
  reset();
  advance(1000);
  assert(Serial.output.empty());
  command("STARTER\nstart\n START\n");
  command(std::string("START\0\n", 7));
  command(std::string(100, 'X') + "START\n");
  advance(500);
  assert(Serial.output.empty());
  command("STA");
  advance(500);
  assert(Serial.output.empty());
  command("RT\r\n");
  assert(lines().size() == 1 && lines()[0].find("time_ms,") == 0);
  checkPushes(1000);
  assert(lines().size() > 5);
  assert(sensors[0].latestDistanceMm > sensors[0].filteredDistanceMm);
  Serial.output.clear();
  command("START\n");
  checkPushes(500);
  for (const auto &line : lines()) assert(line.find("time_ms") != 0);
  command("STOP\n");
  Serial.output.clear();
  advance(500);
  assert(Serial.output.empty());
  command("START\nSTOP\n");
  Serial.output.clear();
  advance(500);
  assert(Serial.output.empty());

  // The first sensor reports before any of the other three has returned.
  reset();
  command("START\n");
  checkPushes(100);
  auto row = fields(lines().back());
  assert(lines().size() == 2);
  assert(row[1] == "1010" && row[2] == "-1" && row[3] == "-1" && row[4] == "-1");
  assert(Wire.generations[1] == 0);
  checkPushes(350);
  assert(lines().size() == 5);
  auto first = fields(lines()[1]);
  auto second = fields(lines()[2]);
  assert(first[1] == second[1] && second[2] == "1110");

  // A fresh return still sends a packet when its numeric distance is unchanged.
  reset();
  Wire.constantDistances = true;
  command("START\n");
  checkPushes(950);
  assert(lines().size() >= 9);
  assert(fields(lines()[1])[1] == fields(lines()[5])[1]);

  // Each zone can be the sole responding sensor, regardless of scan position.
  for (int working = 0; working < 4; ++working) {
    reset();
    Wire.readFailMask = static_cast<uint8_t>(15 ^ (1U << working));
    command("START\n");
    checkPushes(950);
    assert(lines().size() >= 3);
    for (size_t i = 1; i < lines().size(); ++i) {
      row = fields(lines()[i]);
      for (int sensor = 0; sensor < 4; ++sensor) {
        assert(sensor == working ? std::stoi(row[sensor + 1]) > 0 : row[sensor + 1] == "-1");
      }
    }
  }

  // Trigger failures, missing/partial replies and out-of-range results preserve
  // the last successful cache. Other sensors continue pushing full snapshots.
  reset();
  command("START\n");
  checkPushes(450);
  const auto cached = sensors[1].latestDistanceMm;
  for (int failure = 0; failure < 4; ++failure) {
    Wire.failMask = failure == 0 ? 2 : 0;
    Wire.readFailMask = failure == 1 ? 2 : 0;
    Wire.shortMask = failure == 2 ? 2 : 0;
    Wire.invalidMask = failure == 3 ? 2 : 0;
    Serial.output.clear();
    checkPushes(900);
    assert(!lines().empty() && !sensors[1].valid);
    for (const auto &line : lines()) assert(std::stoi(fields(line)[2]) == cached);
  }
  Wire.invalidMask = 0;
  checkPushes(500);
  assert(sensors[1].valid && sensors[1].latestDistanceMm > cached);

  // No success means no packets, even though cached values remain available.
  Wire.readFailMask = 15;
  Serial.output.clear();
  checkPushes(900);
  assert(Serial.output.empty());
  assert(findNearestSensor() == -1);
  Wire.readFailMask = 0;

  // I2C read latency must not consume the mandatory post-read cooldown.
  Wire.readDelayMs = 17;
  checkPushes(1000);  // FakeWire asserts >=10 ms between read completion and trigger.

  // START during a measurement enables that result; it doesn't wait for a scan.
  reset();
  advance(50);
  command("START\n");
  checkPushes(50);
  assert(lines().size() == 2);
  command("STOP\n");
  advance(450);
  Serial.output.clear();
  command("START\n");
  checkPushes(120);
  assert(lines().size() >= 2);

  // Move the running clock and deadlines together across millis() rollover.
  const uint32_t shift = UINT32_MAX - 50 - fakeNow;
  fakeNow += shift;
  phaseDeadlineMs += shift;
  nextScanDeadlineMs += shift;
  heartbeatDeadlineMs += shift;
  for (auto &time : Wire.lastReadFinished) time += shift;
  for (auto &sensor : sensors) sensor.cooldownDeadlineMs += shift;
  for (auto &time : Wire.triggered) time += shift;
  Serial.output.clear();
  checkPushes(1000);
  assert(lines().size() >= 8);
  // Backpressure: freeze the in-flight snapshot, retain new readings, and
  // follow it with the latest complete set. Exercise short and zero writes.
  reset();
  command("START\n");
  Serial.output.clear();
  Serial.writable = 0;
  recordSuccessfulReading(0, 700);
  serviceSerialOutput();
  assert(Serial.output.empty());
  recordSuccessfulReading(1, 800);
  recordSuccessfulReading(0, 650);
  Serial.writable = 7;
  Serial.maxWrite = 3;
  serviceSerialOutput();
  assert(serialPacketOffset == 3);
  recordSuccessfulReading(2, 900);  // Arrives with a partially queued frame.
  Serial.maxWrite = 0;
  serviceSerialOutput();
  assert(serialPacketOffset == 3);
  Serial.maxWrite = 3;
  for (int n = 0; n < 150; ++n) serviceSerialOutput();
  auto packets = lines();
  assert(packets.size() == 2);
  auto oldPacket = fields(packets[0]);
  auto newPacket = fields(packets[1]);
  assert(oldPacket[1] == "700" && oldPacket[2] == "-1" && oldPacket[3] == "-1");
  assert(newPacket[1] == "650" && newPacket[2] == "800" && newPacket[3] == "900");
  assert(!serialReadingPending && !distancesChangedSinceSend());

  // The distance comparison catches a changed cache even without a read flag.
  Serial.output.clear();
  sensors[0].latestDistanceMm = 600;
  for (int n = 0; n < 100; ++n) serviceSerialOutput();
  assert(lines().size() == 1 && fields(lines()[0])[1] == "600");

  // Serial can send two updates within the same sensor's 10 ms cooldown.
  reset();
  command("START\n");
  Serial.output.clear();
  recordSuccessfulReading(0, 1000);
  finishCurrentSensor();
  const uint32_t cooldownEnd = sensors[0].cooldownDeadlineMs;
  serviceSerialOutput();
  recordSuccessfulReading(0, 950);  // Simulated captured sample, not a new pulse.
  serviceSerialOutput();
  assert(lines().size() == 2 && fields(lines()[1])[1] == "950");
  assert(!deadlineReached(fakeNow, cooldownEnd));
  serviceSensorPolling(fakeNow);  // Sensor 1 need not wait for sensor 0.
  assert(Wire.generations[1] == 1);
  const auto earlierTriggers = Wire.generations[0];
  currentSensor = 0;
  pollPhase = PollPhase::kStartMeasurement;
  nextScanDeadlineMs = fakeNow;
  serviceSensorPolling(fakeNow);
  assert(Wire.generations[0] == earlierTriggers);  // Same sensor is still in cooldown.
  fakeNow = cooldownEnd;
  currentSensor = 0;
  serviceSensorPolling(fakeNow);
  assert(Wire.generations[0] == earlierTriggers + 1);

  // Actual polling continues while TX is completely stalled.
  reset();
  command("START\n");
  Serial.output.clear();
  Serial.writable = 0;
  advance(1000);
  assert(Wire.successfulReads >= 8 && Serial.output.empty());
  assert(serialReadingPending);
  Serial.writable = 512;
  serviceSerialOutput();
  serviceSerialOutput();
  assert(lines().size() == 2);
  for (int sensor = 0; sensor < 4; ++sensor) {
    assert(std::stoi(fields(lines().back())[sensor + 1]) == sensors[sensor].latestDistanceMm);
  }

  // STOP/restart mid-frame never splices the new header into the old line.
  reset();
  command("START\n");
  Serial.output.clear();
  Serial.writable = 2;
  recordSuccessfulReading(0, 777);
  serviceSerialOutput();
  command("STOP\nSTART\n");
  for (int n = 0; n < 150; ++n) serviceSerialOutput();
  assert(lines().size() == 2);
  assert(fields(lines()[0])[1] == "777");
  assert(lines()[1].find("time_ms,") == 0);
  recordSuccessfulReading(1, 888);
  for (int n = 0; n < 100; ++n) serviceSerialOutput();
  assert(lines().size() == 3 && fields(lines().back())[2] == "888");

  std::cout << "PASS: command framing, per-reading cached packets, independent zones, failure/recovery, 10 ms per-sensor cooldown, conversion wait, restart, clock rollover, stalled/partial TX, snapshot follow-up, cooldown-time sends and mid-frame restart\n";
}
