#pragma once
#include "Wire.h"
#include <vector>
#include <array>
#include <fstream>

constexpr uint8_t SSD1306_SWITCHCAPVCC = 2, SSD1306_WHITE = 1;
struct DrawnText { int x, y; std::string text; };

struct Adafruit_SSD1306 {
  std::vector<DrawnText> drawing;
  std::array<uint8_t, 128 * 32> pixels = {};
  std::array<uint8_t, 128 * 32> transferredPixels = {};
  uint32_t nextDrawAdvanceMs = 0;
  uint8_t rotation = 0;
  int x = 0, y = 0;
  unsigned transfers = 0, initializations = 0;
  bool allocationWorks = true;
  bool failTransfer = false;
  Adafruit_SSD1306(int width, int height, FakeWire *, int reset) {
    assert(width == 128 && height == 32 && reset == -1);
  }
  bool begin(uint8_t, uint8_t, bool, bool) { ++initializations; return allocationWorks; }
  void setRotation(uint8_t value) { assert(value == 0 || value == 2); rotation = value; }
  void setTextWrap(bool) {}
  void setTextColor(uint8_t) {}
  void setTextSize(uint8_t horizontal, uint8_t vertical = 1) {
    assert(horizontal == 1 && vertical == 1);
  }
  void setCursor(int left, int top) { x = left; y = top; }
  void clearDisplay() { drawing.clear(); pixels.fill(0); }
  // Reject out-of-screen writes instead of silently clipping like the device.
  void drawPixel(int left, int top, uint16_t color) {
    fakeNow += nextDrawAdvanceMs;
    nextDrawAdvanceMs = 0;
    assert(left >= 0 && left < 128 && top >= 0 && top < 32);
    if (rotation == 2) { left = 127 - left; top = 31 - top; }
    pixels[top * 128 + left] = color != 0;
  }
  uint8_t pixelAt(int left, int top) const {
    if (rotation == 2) { left = 127 - left; top = 31 - top; }
    return pixels[top * 128 + left];
  }
  void print(const char *text) {
    drawing.push_back({x, y, text});
    // The six unchanged label/unit glyphs from the classic GFX 5x7 font.
    const uint8_t font[][5] = {
      {0x00, 0x42, 0x7F, 0x40, 0x00}, {0x72, 0x49, 0x49, 0x49, 0x46},
      {0x21, 0x41, 0x49, 0x4D, 0x33}, {0x18, 0x14, 0x12, 0x7F, 0x10},
      {0x00, 0x08, 0x7E, 0x09, 0x02}, {0x04, 0x04, 0x3F, 0x44, 0x24}
    };
    for (const char *cursor = text; *cursor; ++cursor) {
      assert((*cursor >= '1' && *cursor <= '4') || *cursor == 'f' || *cursor == 't');
      const unsigned index = *cursor == 'f' ? 4 : *cursor == 't' ? 5 : *cursor - '1';
      assert(x >= 0 && x + 6 <= 128 && y >= 0 && y + 7 <= 32);
      for (int col = 0; col < 5; ++col)
        for (int row = 0; row < 7; ++row)
          if (font[index][col] & (1U << row)) drawPixel(x + col, y + row, 1);
      x += 6;
    }
  }
  void print(int number) { print(std::to_string(number).c_str()); }
  // Optional host-rendered evidence; PBM pixels are never sent to hardware.
  void savePbm(const char *path) const {
    std::ofstream output(path);
    assert(output.good());
    output << "P1\n128 32\n";
    for (int row = 0; row < 32; ++row) {
      for (int col = 0; col < 128; ++col) output << (pixels[row * 128 + col] ? "0 " : "1 ");
      output << '\n';
    }
    assert(output.good());
  }
  void display() {
    ++transfers;
    Wire.timedOut = failTransfer;
    if (!failTransfer) transferredPixels = pixels;
  }
};
