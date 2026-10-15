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
  std::string output;
  int writeCapacity = 64;
  uint32_t readAdvanceMs = 0;
  uint32_t capacityCheckAdvanceMs = 0;
  void begin(uint32_t baud) { assert(baud == 115200); }
  int available() { return static_cast<int>(input.size()); }
  int read() {
    const char byte = input.front();
    input.pop_front();
    fakeNow += readAdvanceMs;
    return byte;
  }
  int availableForWrite() {
    fakeNow += capacityCheckAdvanceMs;
    return writeCapacity;
  }
  size_t write(const uint8_t *bytes, size_t length) {
    assert(length <= static_cast<size_t>(writeCapacity));
    output.append(reinterpret_cast<const char *>(bytes), length);
    return length;
  }
  void send(const std::string &text) { input.insert(input.end(), text.begin(), text.end()); }
};
extern FakeSerial Serial;

struct FakeWire {
  bool connected = true;
  bool timedOut = false;
  uint32_t probeAdvanceMs = 0;
  void begin() {}
  void beginTransmission(uint8_t address) { assert(address == 0x3C); }
  uint8_t endTransmission() {
    fakeNow += probeAdvanceMs;
    return connected ? 0 : 2;
  }
  void setWireTimeout(uint32_t, bool) {}
  void clearWireTimeoutFlag() { timedOut = false; }
  bool getWireTimeoutFlag() { return timedOut; }
};
extern FakeWire Wire;
