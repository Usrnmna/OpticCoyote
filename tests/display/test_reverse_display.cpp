// Exercise the actual reverse display sketch with fake USB/I2C/time.
// These host checks establish protocol behavior, not physical OLED operation.
#include "Wire.h"
#include <iostream>
uint32_t fakeNow = 0;
FakeSerial Serial;
FakeWire Wire;
#include "../../optic_coyote_display/optic_coyote_display.ino"

void advance(uint32_t milliseconds) {
  for (uint32_t i = 0; i < milliseconds; ++i) { ++fakeNow; loop(); }
}

void send(const std::string &packet) {
  Serial.send(packet);
  while (Serial.available()) loop();
}

#include "layout_checks.h"

void expectIdle() {
  assert(!reverseReceiver.active);
  assert(!reverseReceiver.havePacket);
  for (uint8_t i = 0; i < 4; ++i) assert(reverseReceiver.distances[i] == -1);
  advance(100);
  assert(oled.drawing.empty());
  for (const auto pixel : oled.pixels) assert(pixel == 0);
  assert(oledReady);
  assert(paintedMode == DisplayMode::Idle);
}

int main() {
  checkAllGlyphBounds();
  setup();
  expectIdle();

  // Data cannot acquire ownership, including the original untagged protocol.
  send("D,1,305,610,914,1219\nD,305,610,914,1219\nK,1\n");
  expectIdle();
  assert(Serial.output.empty());

  // Invalid opening frames cannot activate; delimiters are LF or CRLF only.
  const std::string invalid[] = {"R,0,1000\n", "R,4294967296,1000\n",
      "R,-1,1000\n", "R,1,199\n", "R,1,10001\n", "R,1,1000,x\n",
      "R,+1,1000\n", "R, 1,1000\n", "R,1,1000\rR,1,1000\n",
      std::string("x\0R,1,1000\n", 12),
      std::string(81, 'x') + "R,1,1000\n"};
  for (const auto &packet : invalid) { send(packet); assert(!reverseReceiver.active); }

  send("R,1,1500\r\n");
  assert(reverseReceiver.active && reverseReceiver.token == 1);
  assert(Serial.output == "A,1,0\n");
  advance(100);
  expectFields("-.-", "-.-", "-.-", "-.-");
  send("D,1,305,610,914,1219\n");
  advance(100);
  expectFields("1.0", "2.0", "3.0", "4.0");

  // A malformed fourth value cannot commit any values or refresh freshness.
  const uint32_t lastGood = reverseReceiver.lastPacketMs;
  const std::string invalidData[] = {"D,1,1,2,3,-2\n", "D,1,1,2,3,30001\n",
      "D,1,1,2,3,9999999999\n", "D,1,1,2,3,4,5\n", "D,1,1,2,3\n",
      "D,1,1,2,3,4x\n", "D,1,1,2,3,+1\n", "D,1,1,2,3,\n",
      "D,2,1,2,3,4\n", "D,1,1,2,3,4\rD,1,1,2,3,4\n"};
  for (const auto &packet : invalidData) send(packet);
  assert(reverseReceiver.lastPacketMs == lastGood);
  assert(reverseReceiver.distances[0] == 305 && reverseReceiver.distances[3] == 1219);

  // Repeated R is idempotent: neither data nor the original lease is reset.
  send("R,1,10000\n");
  assert(reverseReceiver.havePacket && reverseReceiver.lastPacketMs == lastGood);
  advance(1300);
  assert(!reverseReceiver.active);
  send("K,1,1\nR,1,1500\nD,1,305,610,914,1219\n");
  expectIdle();

  // X releases immediately in firmware; the next refresh clears prior values.
  send("R,2,1500\nD,2,305,610,914,1219\n");
  advance(100);
  expectFields("1.0", "2.0", "3.0", "4.0");
  send("X\n");
  expectIdle();
  const unsigned blankTransfers = oled.transfers;
  advance(300);
  assert(oled.transfers == blankTransfers);
  send("R,2,1500\nD,2,305,610,914,1219\nK,2,1\n");
  expectIdle();

  // A new session requires fresh data; an old token cannot replace it.
  send("R,3,1500\nR,2,1500\nD,2,305,610,914,1219\n");
  assert(reverseReceiver.token == 3 && !reverseReceiver.havePacket);
  advance(100);
  expectFields("-.-", "-.-", "-.-", "-.-");
  send("D,3,305,610,914,1219\n");
  advance(100);
  expectFields("1.0", "2.0", "3.0", "4.0");
  for (unsigned i = 0; i < 9; ++i) {
    advance(250);
    send("K,3," + std::to_string(i + 1) + "\n");
  }
  advance(100);
  assert(reverseReceiver.active && reverseReceiver.havePacket);
  expectFields("-.-", "-.-", "-.-", "-.-");

  // D maintains data freshness but cannot renew the ownership lease.
  send("X\nR,4,200\nD,4,0,0,0,0\n");
  advance(199);
  send("D,4,0,0,0,0\n");
  assert(reverseReceiver.active);
  advance(1);
  send("K,4,1\nR,4,200\n");
  expectIdle();

  // Expiry runs before buffered input, so a K at the deadline cannot revive it.
  send("R,5,200\n");
  fakeNow += 200;
  Serial.send("K,5,1\nR,5,200\n");
  loop();
  expectIdle();

  // Congested ACKs are retried without blocking; release cancels pending ACKs.
  Serial.output.clear();
  Serial.writeCapacity = 0;
  send("R,6,1500\nK,6,1\n");
  assert(reverseReceiver.pendingAckToken == 6 && Serial.output.empty());
  assert(reverseReceiver.pendingAckRequestId == 1);
  Serial.writeCapacity = 5;
  loop();
  assert(Serial.output.empty());
  Serial.writeCapacity = 6;
  loop();
  assert(Serial.output == "A,6,1\n" && !reverseReceiver.pendingAckToken);
  Serial.writeCapacity = 0;
  send("K,6,2\nX\n");
  assert(!reverseReceiver.pendingAckToken && !reverseReceiver.pendingAckRequestId);
  Serial.writeCapacity = 64;
  loop();
  assert(Serial.output == "A,6,1\n");
  expectIdle();

  // A new R replaces pending ACK/data atomically; expired ACKs are cancelled.
  Serial.output.clear();
  Serial.writeCapacity = 0;
  send("R,7,200\nD,7,0,0,0,0\nR,8,200\n");
  assert(reverseReceiver.token == 8 && !reverseReceiver.havePacket);
  assert(reverseReceiver.pendingAckToken == 8);
  advance(200);
  Serial.writeCapacity = 64;
  loop();
  assert(Serial.output.empty());
  expectIdle();

  // Unsigned lease and data age calculations remain correct across millis wrap.
  fakeNow = UINT32_MAX - 50;
  send("R,4294967295,1000\nD,4294967295,-1,0,5000,30000\n");
  assert(Serial.output == "A,4294967295,0\n");
  advance(100);
  expectFields("-.-", "0.0", ">10", ">10");
  send("K,4294967295,4294967295\n");
  assert(Serial.output == "A,4294967295,0\nA,4294967295,4294967295\n");
  advance(999);
  assert(reverseReceiver.active);
  advance(1);
  expectIdle();

  // UART ownership releases even with an absent OLED; reconnection paints idle.
  send("R,9,1500\nD,9,305,610,914,1219\n");
  advance(100);
  Wire.connected = false;
  advance(100);
  assert(!oledReady);
  send("X\n");
  assert(!reverseReceiver.active && !reverseReceiver.havePacket);
  Wire.connected = true;
  advance(1100);
  expectIdle();

  // A rapid release/reacquisition repaints identical values under a new token.
  send("R,10,1500\nD,10,305,610,914,1219\n");
  advance(100);
  const unsigned priorSessionTransfers = oled.transfers;
  send("X\nR,11,1500\nD,11,305,610,914,1219\n");
  advance(100);
  assert(oled.transfers == priorSessionTransfers + 1);
  assert(paintedToken == 11);
  expectFields("1.0", "2.0", "3.0", "4.0");

  // A command started before expiry but completed after it cannot renew.
  send("X\nR,12,200\n");
  Serial.output.clear();
  fakeNow += 196;
  Serial.readAdvanceMs = 1;
  send("K,12,1\n");
  Serial.readAdvanceMs = 0;
  assert(!reverseReceiver.active && Serial.output.empty());
  expectIdle();

  // A pending ACK is cancelled if capacity checking crosses the deadline.
  Serial.writeCapacity = 0;
  send("R,13,200\n");
  fakeNow += 199;
  Serial.writeCapacity = 64;
  Serial.capacityCheckAdvanceMs = 1;
  sendReverseAcknowledgement();
  Serial.capacityCheckAdvanceMs = 0;
  assert(!reverseReceiver.active && Serial.output.empty());
  expectIdle();

  // Probe latency is included before selecting the current display owner.
  send("R,14,200\nD,14,305,610,914,1219\n");
  advance(100);
  fakeNow += 99;
  lastRefreshMs = fakeNow - Config::kRefreshIntervalMs;
  Wire.probeAdvanceMs = 1;
  refreshOled();
  Wire.probeAdvanceMs = 0;
  assert(!reverseReceiver.active && oled.drawing.empty());
  expectIdle();

  // The same current-time check applies to data freshness with a live lease.
  send("R,15,10000\nD,15,305,610,914,1219\n");
  advance(100);
  fakeNow += 1899;
  Wire.probeAdvanceMs = 1;
  refreshOled();
  Wire.probeAdvanceMs = 0;
  assert(reverseReceiver.active);
  expectFields("-.-", "-.-", "-.-", "-.-");

  // Fresh data restores mixed widths within the same lease after stale values.
  send("D,15,3032,3033,0,-1\n");
  advance(100);
  expectFields("9.9", ">10", "0.0", "-.-");
  send("D,15,30000,-1,3033,3032\n");
  advance(100);
  expectFields(">10", "-.-", ">10", "9.9");
  assert(reverseReceiver.distances[0] == 30000);

  // Post-transfer probing also releases ownership; the next refresh clears.
  send("X\nR,16,200\nD,16,305,610,914,1219\n");
  fakeNow += 198;
  Wire.probeAdvanceMs = 1;
  refreshOled();
  Wire.probeAdvanceMs = 0;
  assert(!reverseReceiver.active && !reverseReceiver.havePacket);
  expectIdle();

  // Renewal identifiers are strictly increasing. Malformed, old, duplicate,
  // and legacy requests neither renew the lease nor generate a fresh ACK.
  Serial.output.clear();
  send("R,17,500\n");
  assert(Serial.output == "A,17,0\n");
  advance(100);
  send("K,17,3\n");
  assert(Serial.output == "A,17,0\nA,17,3\n");
  advance(100);
  send("R,17,10000\n");
  assert(Serial.output == "A,17,0\nA,17,3\nA,17,3\n");
  Serial.output.clear();
  send("K,17\nK,17,0\nK,17,2\nK,17,3\nK,17,\nK,17,4,x\n"
       "K,17,-1\nK,17,+4\nK,17, 4\nK,17,4294967296\nK,18,4\n");
  assert(Serial.output.empty());
  advance(399);
  assert(reverseReceiver.active);
  send("K,17,3\n");
  advance(1);
  expectIdle();
  assert(Serial.output.empty());

  // A blocked writer retains the newest accepted request, and rejecting a
  // duplicate cannot erase that pending reply or replace its identifier.
  Serial.writeCapacity = 0;
  send("R,18,1000\nK,18,1\nK,18,2\nK,18,1\nK,18,2\n");
  assert(reverseReceiver.pendingAckToken == 18 &&
         reverseReceiver.pendingAckRequestId == 2);
  Serial.writeCapacity = 64;
  loop();
  assert(Serial.output == "A,18,2\n");
  send("X\n");
  expectIdle();

  // A fresh snapshot can become stale during drawing, even when the previous
  // displayed view already consists of missing markers. Do not send old data.
  send("R,19,10000\n");
  advance(100);
  expectFields("-.-", "-.-", "-.-", "-.-");
  send("D,19,3032,3033,0,-1\n");
  fakeNow += Config::kLinkTimeoutMs - 1;
  lastRefreshMs = fakeNow - Config::kRefreshIntervalMs;
  oled.nextDrawAdvanceMs = 1;
  const auto staleTransfers = oled.transfers;
  refreshOled();
  assert(reverseReceiver.active);
  assert(oled.transfers == staleTransfers + 1);
  expectFields("-.-", "-.-", "-.-", "-.-");
  assert(oled.transferredPixels == oled.pixels);

  // Lease expiry while drawing takes priority over any distance frame.
  send("X\nR,20,200\nD,20,3033,3033,3033,3033\n");
  fakeNow += 199;
  lastRefreshMs = fakeNow - Config::kRefreshIntervalMs;
  oled.nextDrawAdvanceMs = 1;
  refreshOled();
  assert(!reverseReceiver.active);
  for (const auto pixel : oled.transferredPixels) assert(pixel == 0);
  expectIdle();

  std::cout << "Reverse OLED ownership, stale data, lease, ACK and recovery checks passed\n";
}
