// Exercise the actual display sketch with fake USB/I2C/time. No hardware claims.
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

void expectFields(const char *a, const char *b, const char *c, const char *d) {
  const char *expected[] = {a, b, c, d};
  assert(oled.drawing.size() == 9);
  for (int sensor = 0; sensor < 4; ++sensor) {
    const auto &label = oled.drawing[sensor * 2];
    const auto &value = oled.drawing[sensor * 2 + 1];
    assert(label.text == std::to_string(sensor + 1));
    assert(value.x == sensor * 32 + 4 && value.y == 11);
    assert(value.text == expected[sensor]);
    assert(value.x + static_cast<int>(value.text.size()) * 6 <= (sensor + 1) * 32);
  }
  assert(oled.drawing.back().text == "ft");
}

int main() {
  // Decimal rounding boundaries, unavailable marker, and the widest field.
  char value[5];
  const int32_t mm[] = {-1, 0, 15, 16, 305, 610, 914, 1219, 3032, 3033, 5000, 30000, 30001};
  const char *feet[] = {"--.-", " 0.0", " 0.0", " 0.1", " 1.0", " 2.0", " 3.0", " 4.0",
                        " 9.9", "10.0", "16.4", "98.4", "--.-"};
  for (unsigned i = 0; i < sizeof(mm) / sizeof(mm[0]); ++i) {
    DisplayProtocol::formatFeet(mm[i], value);
    assert(std::string(value) == feet[i]);
  }
  setup();
  advance(100);
  expectFields("--.-", "--.-", "--.-", "--.-");
  send("D,305,610,");
  advance(100);
  assert(!havePacket);
  send("914,1219\r\n");
  advance(100);
  expectFields(" 1.0", " 2.0", " 3.0", " 4.0");

  const auto lastGood = lastPacketMs;
  const std::string bad[] = {"D,1,2,3,4,5\n", "D,1,,3,4\n", "D,1,2,3,-2\n",
      "D,1,2,3,30001\n", "D,1,2,3,9999999999\n", "D,1,2,3,4x\n",
      "D,1,2,3,1.5\n", "D,1,2,3,+1\n", "D,1,2,3, 1\n",
      std::string("D,1,2,3,\0\n", 10), std::string(1000, 'X') + "D,1,2,3,4\n"};
  for (const auto &packet : bad) send(packet);
  assert(lastPacketMs == lastGood);
  assert(receiver.distances[0] == 305 && receiver.distances[3] == 1219);
  advance(2000);
  expectFields("--.-", "--.-", "--.-", "--.-");
  send("D,-1,0,5000,30000\n");
  advance(100);
  expectFields("--.-", " 0.0", "16.4", "98.4");

  // A repeated heartbeat refreshes freshness without unnecessary OLED writes.
  const auto before = oled.transfers;
  for (int i = 0; i < 30; ++i) { send("D,-1,0,5000,30000\n"); advance(100); }
  assert(oled.transfers == before);

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
  expectFields(" 4.0", " 3.0", " 2.0", " 1.0");
  oled.failTransfer = true;
  send("D,0,0,0,0\n");
  advance(100);
  assert(!oledReady);
  oled.failTransfer = false;
  advance(1100);
  assert(oledReady);
  expectFields(" 0.0", " 0.0", " 0.0", " 0.0");

  // Unsigned elapsed arithmetic must preserve freshness across millis wrap.
  fakeNow = UINT32_MAX - 500;
  send("D,305,610,914,1219\n");
  advance(1000);
  expectFields(" 1.0", " 2.0", " 3.0", " 4.0");
  advance(1100);
  expectFields("--.-", "--.-", "--.-", "--.-");
  std::cout << "OLED protocol, layout, timeout and recovery checks passed\n";
}
