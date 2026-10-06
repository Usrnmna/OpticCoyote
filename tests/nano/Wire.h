// Host-only Arduino/Wire substitutes for exercising the actual sketch.
#pragma once
#include <cassert>
#include <cstdint>
#include <deque>
#include <sstream>
#include <string>
#include <algorithm>

#define F(value) value
constexpr uint8_t HIGH = 1, LOW = 0, OUTPUT = 1, LED_BUILTIN = 13;
extern uint32_t fakeNow;
inline uint32_t millis() { return fakeNow; }
inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t, uint8_t) {}

struct FakeSerial {
  std::deque<char> input;
  std::string output;
  int writable = 512;
  size_t maxWrite = 512;
  int availableForWrite() { return writable; }
  size_t write(const uint8_t *data, size_t count) {
    assert(count <= static_cast<size_t>(writable));
    count = std::min(count, maxWrite);
    output.append(reinterpret_cast<const char *>(data), count);
    return count;
  }
  void begin(uint32_t) {}
  int available() { return static_cast<int>(input.size()); }
  int read() { char c = input.front(); input.pop_front(); return c; }
  template <typename T> void print(T value) {
    std::ostringstream stream;
    stream << value;
    output += stream.str();
  }
  template <typename T> void println(T value) { print(value); output += "\r\n"; }
  void send(const std::string &text) { input.insert(input.end(), text.begin(), text.end()); }
};
extern FakeSerial Serial;

struct FakeWire {
  uint8_t address = 0, value = 0;
  int selected = -1;
  uint32_t triggered[4] = {};
  unsigned generations[4] = {};
  uint16_t distances[4] = {};
  uint8_t failMask = 0;
  uint8_t readFailMask = 0, invalidMask = 0, shortMask = 0;
  uint32_t readDelayMs = 0;
  uint32_t lastReadFinished[4] = {};
  unsigned successfulReads = 0;
  bool hasRead[4] = {};
  bool constantDistances = false;
  std::deque<uint8_t> response;
  void begin() {}
  void setClock(uint32_t) {}
  void beginTransmission(uint8_t target) { address = target; }
  void write(uint8_t byte) { value = byte; }
  uint8_t endTransmission() {
    if (address == 0x70) {
      selected = -1;
      for (int i = 0; i < 4; ++i) if (value == (1U << i)) selected = i;
    } else {
      assert(address == 0x57 && selected >= 0 && value == 1);
      if (hasRead[selected]) assert(static_cast<uint32_t>(fakeNow - lastReadFinished[selected]) >= 10);
      if (failMask & (1U << selected)) return 2;
      triggered[selected] = fakeNow;
      ++generations[selected];
      distances[selected] = static_cast<uint16_t>(1000 + selected * 100 +
          (constantDistances ? 0 : generations[selected] * 10));
    }
    return 0;
  }
  uint8_t requestFrom(uint8_t target, uint8_t count) {
    assert(target == 0x57 && count == 3 && selected >= 0);
    assert(static_cast<uint32_t>(fakeNow - triggered[selected]) >= 100);
    fakeNow += readDelayMs;
    lastReadFinished[selected] = fakeNow;
    hasRead[selected] = true;
    response.clear();
    if ((failMask | readFailMask) & (1U << selected)) return 0;
    if (shortMask & (1U << selected)) { response = {0, 1}; return 2; }
    const uint32_t raw = (invalidMask & (1U << selected)) ? 0 : distances[selected] * 1000UL;
    response = {static_cast<uint8_t>(raw >> 16), static_cast<uint8_t>(raw >> 8), static_cast<uint8_t>(raw)};
    if (!(invalidMask & (1U << selected))) ++successfulReads;
    return 3;
  }
  int available() { return static_cast<int>(response.size()); }
  int read() { uint8_t byte = response.front(); response.pop_front(); return byte; }
};
extern FakeWire Wire;
