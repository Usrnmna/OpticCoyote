// Exercise the actual display sketch with fake USB/I2C/time. No hardware claims.
#include "Wire.h"
#include <iostream>
#define OPTIC_COYOTE_STANDALONE 1
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

int main(int argc, char **argv) {
  checkAllGlyphBounds();
  checkAllMillimetres();
  // Decimal rounding boundaries, unavailable marker, and the widest field.
  char value[5];
  const int32_t mm[] = {INT32_MIN, -2, -1, 0, 15, 16, 305, 610, 914, 1219,
                       3017, 3018, 3032, 3033, 3048, 5000, 30000, 30001, INT32_MAX};
  const char *feet[] = {"-.-", "-.-", "-.-", "0.0", "0.0", "0.1", "1.0", "2.0", "3.0", "4.0",
                        "9.9", "9.9", "9.9", ">10", ">10", ">10", ">10", "-.-", "-.-"};
  for (unsigned i = 0; i < sizeof(mm) / sizeof(mm[0]); ++i) {
    memset(value, 'x', sizeof(value));
    DisplayProtocol::formatFeet(mm[i], value);
    assert(std::string(value) == feet[i]);
    assert(value[3] == '\0' && value[4] == '\0');
  }
  setup();
  advance(100);
  expectFields("-.-", "-.-", "-.-", "-.-");
  send("D,305,610,");
  advance(100);
  assert(!havePacket);
  send("914,1219\r\n");
  advance(100);
  expectFields("1.0", "2.0", "3.0", "4.0");

  const auto lastGood = lastPacketMs;
  const std::string bad[] = {"D,1,2,3,4,5\n", "D,1,,3,4\n", "D,1,2,3,-2\n",
      "D,1,2,3,30001\n", "D,1,2,3,9999999999\n", "D,1,2,3,4x\n",
      "D,1,2,3,1.5\n", "D,1,2,3,+1\n", "D,1,2,3, 1\n",
      std::string("D,1,2,3,\0\n", 10), std::string(1000, 'X') + "D,1,2,3,4\n"};
  for (const auto &packet : bad) send(packet);
  assert(lastPacketMs == lastGood);
  assert(receiver.distances[0] == 305 && receiver.distances[3] == 1219);
  advance(2000);
  expectFields("-.-", "-.-", "-.-", "-.-");
  send("D,-1,0,5000,30000\n");
  advance(100);
  expectFields("-.-", "0.0", ">10", ">10");

  // A repeated heartbeat refreshes freshness without unnecessary OLED writes.
  const auto before = oled.transfers;
  for (int i = 0; i < 30; ++i) { send("D,-1,0,5000,30000\n"); advance(100); }
  assert(oled.transfers == before);

  // Different raw readings in the same capped category update freshness and
  // stored measurements without repainting an identical visible field.
  const auto previousPacket = lastPacketMs;
  send("D,-1,0,5001,29999\n");
  advance(100);
  assert(lastPacketMs > previousPacket);
  assert(receiver.distances[2] == 5001 && receiver.distances[3] == 29999);
  assert(oled.transfers == before);
  expectFields("-.-", "0.0", ">10", ">10");

  // Disconnection, allocation failure and a transfer timeout recover later.
  Wire.connected = false;
  advance(100);
  assert(!oledReady);
  send("D,1219,914,610,305\n");
  Wire.connected = true;
  oled.allocationWorks = false;
  advance(1000);
  assert(!oledReady);
  oled.allocationWorks = true;
  send("D,1219,914,610,305\n");
  advance(1100);
  expectFields("4.0", "3.0", "2.0", "1.0");
  oled.failTransfer = true;
  send("D,0,0,0,0\n");
  advance(100);
  assert(!oledReady);
  oled.failTransfer = false;
  advance(1100);
  assert(oledReady);
  expectFields("0.0", "0.0", "0.0", "0.0");

  // Unsigned elapsed arithmetic must preserve freshness across millis wrap.
  fakeNow = UINT32_MAX - 500;
  send("D,305,610,914,1219\n");
  advance(1000);
  expectFields("1.0", "2.0", "3.0", "4.0");
  advance(1100);
  expectFields("-.-", "-.-", "-.-", "-.-");
  // Width changes in both directions must clear pixels and preserve raw mm.
  send("D,3033,3032,-1,0\n");
  advance(100);
  expectFields(">10", "9.9", "-.-", "0.0");
  send("D,3032,-1,3033,30000\n");
  advance(100);
  expectFields("9.9", "-.-", ">10", ">10");
  assert(receiver.distances[3] == 30000);
  send("D,0,3032,3033,-1\n");
  advance(100);
  expectFields("0.0", "9.9", ">10", "-.-");
  checkSceneRotation();
  if (argc == 2) oled.savePbm(argv[1]);
  // Rendering across the stale deadline also replaces standalone data before
  // transfer. Exercise unsigned time wrap with a fresh previously-capped field.
  fakeNow = UINT32_MAX - 1000;
  lastRefreshMs = fakeNow;
  send("D,30000,30000,30000,30000\n");
  fakeNow += Config::kLinkTimeoutMs - 1;
  oled.nextDrawAdvanceMs = 1;
  refreshOled();
  expectFields("-.-", "-.-", "-.-", "-.-");
  assert(oled.transferredPixels == oled.pixels);
  std::cout << "OLED protocol, layout, timeout and recovery checks passed\n";
}
