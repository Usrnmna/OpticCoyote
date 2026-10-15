// Exercise the actual reverse firmware with simulated clock, serial, and I2C.
// These checks establish software behavior, not electrical or acoustic behavior.
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

std::vector<std::string> split(const std::string &text, char delimiter) {
  std::vector<std::string> result;
  std::istringstream stream(text);
  std::string part;
  while (std::getline(stream, part, delimiter)) {
    if (!part.empty() && part.back() == '\r') part.pop_back();
    if (!part.empty()) result.push_back(part);
  }
  return result;
}

std::vector<std::string> latest() {
  const auto rows = split(Serial.output, '\n');
  assert(!rows.empty());
  auto row = split(rows.back(), ',');
  assert(row.size() == 12 && row[0] == "S");
  return row;
}

unsigned triggerCount() {
  unsigned total = 0;
  for (unsigned count : Wire.generations) total += count;
  return total;
}

// Reset every main-loop-owned state as if the board had restarted.
void reset(uint32_t now = 0) {
  fakeNow = now;
  millisAdvancePerRead() = 0;
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
  acquisitionEnabled = restartGuardActive = false;
  reverseSessionToken = retiredReverseSessionToken = reverseSessionStartedMs = 0;
  reverseRequestId = reverseLeaseMs = reverseLeaseDeadlineMs = 0;
  nextReverseReportMs = restartGuardDeadlineMs = 0;
  setup();
}

void assertStopped() {
  assert(!acquisitionEnabled && !streamingEnabled);
  assert(Wire.selected == -1 && pinLevels()[Config::kAlarmPin] == LOW);
  for (const auto &sensor : sensors) assert(!sensor.valid && sensor.historyCount == 0);
}

int main() {
  assert(ReverseConfig::kEnabled);
  reset();
  assert(Wire.timeoutUs == ReverseConfig::kI2cTimeoutUs && Wire.resetOnTimeout);
  advance(2000);
  command("START\nSTOP\n");
  assertStopped();
  assert(triggerCount() == 0 && Wire.successfulReads == 0 && Serial.output.empty());

  // Unknown, truncated, overflowing, binary, and oversized lines never acquire.
  const std::vector<std::string> invalid = {
      "R\n", "R,\n", "R,0,500\n", "R,1,199\n", "R,1,10001\n", "R,1,\n",
      "R,-1,500\n", "R,+1,500\n", "R, 1,500\n", "R,1,500,9\n", "r,1,500\n",
      "R,4294967296,500\n", "R,1,4294967296\n", "K,1\n",
      std::string("R,1,500\0\n", 9), std::string(90, 'Z') + "R,1,500\n"};
  for (const auto &input : invalid) command(input);
  command("R,1,");
  advance(1000);
  assert(triggerCount() == 0 && Serial.output.empty());
  command("1500\r\n");
  assert(acquisitionEnabled && reverseSessionToken == 1 && triggerCount() == 1);
  auto row = latest();
  assert(row[1] == "1" && row[2] == "0");
  for (int i = 4; i < 12; i += 2) assert(row[i] == "-1" && row[i + 1] == "0");

  // Session reports use current values and sample ages, including failure state.
  advance(500);
  row = latest();
  assert(std::stoul(row[3]) >= 400);
  for (int i = 4; i < 12; i += 2) assert(std::stoi(row[i]) >= 1000);
  const auto sessionStart = reverseSessionStartedMs;
  const auto leaseDeadline = reverseLeaseDeadlineMs;
  const auto history = sensors[0].historyCount;
  command("R,1,10000\n");
  assert(reverseSessionStartedMs == sessionStart && reverseLeaseDeadlineMs == leaseDeadline);
  assert(sensors[0].historyCount == history);
  command("K,2,1\nK,1\nK,1,0\nK,1,1,9\nK,1,4294967296\n");
  assert(reverseLeaseDeadlineMs == leaseDeadline);
  command("K,1,1\n");
  assert(reverseLeaseDeadlineMs > leaseDeadline);
  assert(reverseRequestId == 1);
  command("K,1,3\n");
  const auto newerDeadline = reverseLeaseDeadlineMs;
  command("K,1,3\nK,1,2\nK,2,4\nK,1\nK,1,0\nK,1,4,9\nK,1,4294967296\n");
  assert(reverseLeaseDeadlineMs == newerDeadline && reverseRequestId == 3);
  command("R,1,10000\n");
  assert(reverseLeaseDeadlineMs == newerDeadline && reverseRequestId == 3);
  command("X\n");
  assertStopped();
  const auto stoppedCount = triggerCount();
  advance(2000);
  command("K,1,2\nR,1,1500\nSTART\n");
  assertStopped();
  assert(triggerCount() == stoppedCount);

  // A delayed start from the last retired session cannot replace the current
  // session, renew its lease, or erase its measurements.
  reset();
  command("R,1,1500\n");
  command("R,2,1500\n");
  advance(250);
  assert(reverseSessionToken == 2 && retiredReverseSessionToken == 1);
  const auto secondStart = reverseSessionStartedMs;
  const auto secondDeadline = reverseLeaseDeadlineMs;
  const auto secondHistory = sensors[0].historyCount;
  command("R,1,10000\n");
  assert(acquisitionEnabled && reverseSessionToken == 2);
  assert(reverseSessionStartedMs == secondStart && reverseLeaseDeadlineMs == secondDeadline);
  assert(sensors[0].historyCount == secondHistory);
  command("X\nX\nR,2,10000\n");
  assertStopped();
  assert(retiredReverseSessionToken == 2);

  // Stopping an in-flight conversion discards it and preserves the acoustic
  // guard even through repeated stops and immediate new session commands.
  reset();
  command("R,10,1500\n");
  const uint32_t conversionEnd = phaseDeadlineMs;
  advance(25);
  command("X\nR,11,1500\nX\nR,12,1500\n");
  assert(acquisitionEnabled && sensors[0].historyCount == 0);
  fakeNow = conversionEnd + Config::kSensorCooldownMs - 1;
  loop();
  assert(triggerCount() == 1 && Wire.successfulReads == 0);
  ++fakeNow;
  loop();
  assert(triggerCount() == 2 && Wire.successfulReads == 0);
  advance(101);
  assert(sensors[0].valid && Wire.successfulReads == 1);

  // Lease expiry precedes reads and polling. Late renewals cannot resurrect it.
  reset();
  command("R,20,200\n");
  fakeNow = reverseLeaseDeadlineMs;
  command("K,20,1\nR,20,200\n");
  assertStopped();
  assert(Wire.successfulReads == 0 && triggerCount() == 1);
  command("R,21,200\n");
  assert(acquisitionEnabled);
  Serial.send(std::string(1024, 'Z'));
  fakeNow = reverseLeaseDeadlineMs;
  loop();
  assertStopped();
  assert(Serial.available() > 900);  // Input work is bounded while expiry proceeds.

  // A hardware timer interrupt between command entry and renewal cannot extend
  // a lease whose deadline was reached while the command was being parsed.
  reset();
  command("R,22,200\n");
  fakeNow = reverseLeaseDeadlineMs - 1;
  millisAdvancePerRead() = 1;
  handleReverseCommand("K,22,1");
  millisAdvancePerRead() = 0;
  assertStopped();

  // Slow I2C operations cannot authorize a new trigger or retain a reading
  // past expiry. A discarded late read still requires post-read cooldown.
  reset();
  command("R,30,200\n");
  fakeNow = phaseDeadlineMs;
  Wire.readDelayMs = 100;
  loop();
  assertStopped();
  const uint32_t readFinished = fakeNow;
  Wire.readDelayMs = 0;
  command("R,31,200\n");
  assert(triggerCount() == 1);
  fakeNow = readFinished + Config::kSensorCooldownMs;
  loop();
  assert(triggerCount() == 2);
  reset();
  Wire.muxDelayMs = 200;
  command("R,32,200\n");
  assertStopped();
  assert(triggerCount() == 0);

  // Exact freshness boundary and per-sensor errors invalidate each field
  // independently; packet emission continues even with no valid sensors.
  reset();
  command("R,40,10000\n");
  Serial.output.clear();
  fakeNow = 100;
  recordSuccessfulReading(0, 250);
  recordSuccessfulReading(1, 800);
  updateAlarm();
  assert(pinLevels()[Config::kAlarmPin] == HIGH);
  recordFailedReading(1);
  fakeNow = 100 + ReverseConfig::kStaleMs - 1;
  serviceSerialOutput();
  row = latest();
  assert(row[4] == "250" && std::stoul(row[5]) == ReverseConfig::kStaleMs - 1);
  assert(row[6] == "-1" && row[7] == "0");
  ++fakeNow;
  nextReverseReportMs = fakeNow;
  serviceSerialOutput();
  updateAlarm();
  row = latest();
  for (int i = 4; i < 12; i += 2) assert(row[i] == "-1" && row[i + 1] == "0");
  assert(pinLevels()[Config::kAlarmPin] == LOW);
  assert(split(Serial.output, '\n').size() == 2);

  // Recovery cannot make expired median history fresh again. A prior close
  // object must not reassert the alarm after a long outage and a clear reading.
  reset();
  command("R,41,10000\n");
  fakeNow = 100;
  recordSuccessfulReading(0, 250);
  recordSuccessfulReading(0, 250);
  recordSuccessfulReading(0, 250);
  recordFailedReading(0);
  fakeNow += ReverseConfig::kStaleMs;
  recordSuccessfulReading(0, 5000);
  updateAlarm();
  assert(sensors[0].valid && sensors[0].historyCount == 1);
  assert(sensors[0].filteredDistanceMm == 5000);
  assert(pinLevels()[Config::kAlarmPin] == LOW);

  // The expiry comparison is wrap-safe and includes the exact boundary; a
  // brief interruption before it retains the useful recent filter history.
  reset(UINT32_MAX - 100);
  command("R,42,10000\n");
  recordSuccessfulReading(0, 250);
  const uint32_t priorSuccess = sensors[0].lastSuccessMs;
  fakeNow = priorSuccess + ReverseConfig::kStaleMs - 1;
  recordSuccessfulReading(0, 5000);
  assert(sensors[0].historyCount == 2);
  fakeNow += ReverseConfig::kStaleMs;
  recordSuccessfulReading(0, 6000);
  assert(sensors[0].historyCount == 1 && sensors[0].filteredDistanceMm == 6000);

  // Failed attempts discard last-good values in reverse reports. Other sensor
  // fields continue updating and the failed sensor recovers independently.
  reset();
  command("R,50,10000\n");
  advance(450);
  Wire.readFailMask = 2;
  advance(450);
  row = latest();
  assert(row[4] != "-1" && row[6] == "-1" && row[7] == "0");
  Wire.readFailMask = 0;
  advance(450);
  row = latest();
  assert(row[6] != "-1");

  // Partial packets finish with their original token. New session data starts
  // only after that newline and contains no distances from the retired session.
  reset();
  command("R,60,10000\n");
  Serial.output.clear();
  fakeNow = 100;
  recordSuccessfulReading(0, 900);
  Serial.writable = 3;
  Serial.maxWrite = 2;
  serviceSerialOutput();
  assert(serialPacketOffset == 2);
  command("X\nR,61,10000\n");
  for (int i = 0; i < 200; ++i) serviceSerialOutput();
  const auto packets = split(Serial.output, '\n');
  assert(packets.size() == 2);
  const auto old = split(packets[0], ',');
  row = split(packets[1], ',');
  assert(old.size() == 12 && old[1] == "60" && old[4] == "900");
  assert(row.size() == 12 && row[1] == "61" && row[4] == "-1");

  // A renewal cannot rewrite the request echoed by a partially transmitted
  // snapshot. The following snapshot carries the new request identifier.
  reset();
  command("R,62,10000\n");
  Serial.output.clear();
  fakeNow = 100;
  recordSuccessfulReading(0, 950);
  Serial.writable = Serial.maxWrite = 2;
  serviceSerialOutput();
  assert(serialPacketOffset == 2);
  command("K,62,1\n");
  assert(reverseRequestId == 1);
  fakeNow = 200;
  for (int i = 0; i < 200; ++i) serviceSerialOutput();
  const auto echoed = split(Serial.output, '\n');
  assert(echoed.size() == 2);
  const auto beforeRenewal = split(echoed[0], ',');
  const auto afterRenewal = split(echoed[1], ',');
  assert(beforeRenewal.size() == 12 && beforeRenewal[2] == "0" && beforeRenewal[3] == "100");
  assert(afterRenewal.size() == 12 && afterRenewal[2] == "1" && afterRenewal[3] == "200");

  // A fully stalled TX path cannot prevent lease expiry or allow stale restart.
  reset();
  Serial.writable = 0;
  command("R,70,200\n");
  advance(300);
  assertStopped();
  assert(serialPacketLength == 0 && Serial.output.empty());
  command("R,70,10000\n");
  assertStopped();

  // Unsigned token maximum, clock rollover, renewal, elapsed ages and expiry
  // use 32-bit arithmetic rather than ordering raw millis() values.
  reset(UINT32_MAX - 150);
  command("R,4294967295,500\n");
  advance(250);
  assert(acquisitionEnabled);
  row = latest();
  assert(row[1] == "4294967295" && std::stoul(row[3]) >= 200);
  command("K,4294967295,4294967295\n");
  const uint32_t renewed = reverseLeaseDeadlineMs;
  assert(reverseRequestId == UINT32_MAX);
  command("K,4294967295,4294967295\nK,4294967295,1\n");
  assert(reverseRequestId == UINT32_MAX && reverseLeaseDeadlineMs == renewed);
  fakeNow = renewed - 1;
  loop();
  assert(acquisitionEnabled);
  fakeNow = renewed;
  loop();
  assertStopped();

  std::cout << "PASS: inactive boot, strict commands, acquisition sessions, renewal/expiry, retired tokens, acoustic guards, I2C expiry, per-sensor freshness, alarm reset, partial/stalled TX and rollover\n";
}
