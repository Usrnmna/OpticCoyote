#pragma once
#include <cassert>
#include <cstdint>
#include <deque>
#include <string>

#define F(text) text
extern uint32_t fakeNow;
inline uint32_t millis() { return fakeNow; }

struct FakeSerial {
  std::deque<char> input;
  void begin(uint32_t baud) { assert(baud == 115200); }
  int available() { return static_cast<int>(input.size()); }
  int read() { const char byte = input.front(); input.pop_front(); return byte; }
  void send(const std::string &text) { input.insert(input.end(), text.begin(), text.end()); }
};
extern FakeSerial Serial;

struct FakeWire {
  bool connected = true;
  bool timedOut = false;
  void begin() {}
  void beginTransmission(uint8_t address) { assert(address == 0x3C); }
  uint8_t endTransmission() { return connected ? 0 : 2; }
  void setWireTimeout(uint32_t, bool) {}
  void clearWireTimeoutFlag() { timedOut = false; }
  bool getWireTimeoutFlag() { return timedOut; }
};
extern FakeWire Wire;
