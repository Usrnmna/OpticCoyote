#pragma once

#include <stdint.h>
#include <stdio.h>
#include <string.h>

// The Pi sends millimetres so rounding happens once, at the display. Keep the
// limit in sync with rpi-oled-bridge/bridge.py. 30000 mm fits in four characters
// as 98.4 feet. -1 is unavailable; zero is a real numeric value, never a fault.
namespace DisplayProtocol {
constexpr uint8_t kSensorCount = 4;
constexpr int32_t kMaximumDistanceMm = 30000;
constexpr uint8_t kLineCapacity = 32;

// Format a four-character field (plus NUL) without AVR floating-point printf.
// One foot is exactly 304.8 mm; adding half the divisor rounds to 0.1 foot.
inline void formatFeet(int32_t millimetres, char (&text)[5]) {
  if (millimetres < 0 || millimetres > kMaximumDistanceMm) {
    memcpy(text, "--.-", 5);
    return;
  }
  const uint16_t tenths = (millimetres * 100L + 1524L) / 3048L;
  snprintf(text, sizeof(text), "%2u.%u", static_cast<unsigned>(tenths / 10),
           static_cast<unsigned>(tenths % 10));
}

// Bounded, allocation-free receiver. Only a complete D,a,b,c,d line commits
// all four fields. Damaged/oversized lines are discarded through the delimiter;
// a valid-looking suffix cannot become a new packet. CR, LF and CRLF work.
class Receiver {
 public:
  int32_t distances[kSensorCount] = {-1, -1, -1, -1};

  bool feed(char byte) {
    if (byte == '\n' || byte == '\r') {
      line_[length_] = '\0';
      const bool accepted = !discard_ && parse();
      length_ = 0;
      discard_ = false;
      return accepted;
    }
    if (discard_) return false;
    if (byte < ' ' || byte > '~' || length_ >= kLineCapacity - 1) {
      discard_ = true;
      return false;
    }
    line_[length_++] = byte;
    return false;
  }

 private:
  char line_[kLineCapacity] = {};
  uint8_t length_ = 0;
  bool discard_ = false;

  // Strict integers only: -1 or 0..30000, exactly four fields, no trailing text.
  // The temporary array keeps a bad fourth field from changing the first three.
  bool parse() {
    if (length_ < 2 || line_[0] != 'D' || line_[1] != ',') return false;
    const char *cursor = line_ + 2;
    int32_t candidate[kSensorCount];
    for (uint8_t sensor = 0; sensor < kSensorCount; ++sensor) {
      int32_t value = 0;
      if (cursor[0] == '-' && cursor[1] == '1') {
        value = -1;
        cursor += 2;
      } else {
        if (*cursor < '0' || *cursor > '9') return false;
        do {
          value = value * 10 + (*cursor++ - '0');
          if (value > kMaximumDistanceMm) return false;
        } while (*cursor >= '0' && *cursor <= '9');
      }
      candidate[sensor] = value;
      if (sensor + 1 < kSensorCount) {
        if (*cursor++ != ',') return false;
      } else if (*cursor != '\0') {
        return false;
      }
    }
    memcpy(distances, candidate, sizeof(distances));
    return true;
  }
};
}  // namespace DisplayProtocol
