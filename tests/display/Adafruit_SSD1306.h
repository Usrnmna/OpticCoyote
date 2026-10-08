#pragma once
#include "Wire.h"
#include <vector>

constexpr uint8_t SSD1306_SWITCHCAPVCC = 2, SSD1306_WHITE = 1;
struct DrawnText { int x, y; std::string text; };

struct Adafruit_SSD1306 {
  std::vector<DrawnText> drawing;
  int x = 0, y = 0;
  unsigned transfers = 0, initializations = 0;
  bool allocationWorks = true;
  bool failTransfer = false;
  Adafruit_SSD1306(int width, int height, FakeWire *, int reset) {
    assert(width == 128 && height == 32 && reset == -1);
  }
  bool begin(uint8_t, uint8_t, bool, bool) { ++initializations; return allocationWorks; }
  void setRotation(uint8_t) {}
  void setTextWrap(bool) {}
  void setTextColor(uint8_t) {}
  void setTextSize(uint8_t, uint8_t = 1) {}
  void setCursor(int left, int top) { x = left; y = top; }
  void clearDisplay() { drawing.clear(); }
  void print(const char *text) { drawing.push_back({x, y, text}); }
  void print(int number) { drawing.push_back({x, y, std::to_string(number)}); }
  void display() { ++transfers; Wire.timedOut = failTransfer; }
};
