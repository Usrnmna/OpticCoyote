#pragma once

// Check the actual sketch framebuffer against each requested field, including
// cleared margins. This catches slot swaps and residual pixels after changes.
inline void expectFields(const char *a, const char *b, const char *c, const char *d) {
  const char *expected[] = {a, b, c, d};
  assert(oled.drawing.size() == 5);
  for (int sensor = 0; sensor < 4; ++sensor) {
    const auto &label = oled.drawing[sensor];
    assert(label.text == std::to_string(sensor + 1));
    assert(label.x == sensor * 32 + 13 && label.y == 0);
    assert(std::string(paintedValues[sensor]) == expected[sensor]);
    char field[5] = {};
    assert(std::string(expected[sensor]).size() == 3);
    memcpy(field, expected[sensor], 3);
    Adafruit_SSD1306 isolated(128, 32, &Wire, -1);
    DistanceGlyphs::drawValue(isolated, sensor * 32, field);
    for (int row = 7; row <= 24; ++row)
      for (int col = sensor * 32; col < (sensor + 1) * 32; ++col)
        assert(oled.pixelAt(col, row) == isolated.pixelAt(col, row));
  }
  assert(oled.drawing.back().text == "ft");
  assert(oled.drawing.back().x == 58 && oled.drawing.back().y == 25);
}

// Every decimal and special field must fit every sensor column, with at least
// one clear pixel on each side and clear separator rows above/below the values.
inline void checkAllGlyphBounds() {
  for (int value = 0; value < 102; ++value) {
    char field[5] = {};
    const int32_t mm = value == 100 ? 3033 : value == 101 ? -1 :
        (value * 3048 + 50) / 100;
    DisplayProtocol::formatFeet(mm, field);
    if (value < 100) {
      assert(field[0] == '0' + value / 10 && field[1] == '.' &&
             field[2] == '0' + value % 10);
    }
    const int width = value == 100 ? 29 : 23;
    assert(DistanceGlyphs::valueWidth(field) == width);
    for (int sensor = 0; sensor < 4; ++sensor) {
      for (uint8_t rotation = 0; rotation <= 2; rotation += 2) {
        Adafruit_SSD1306 frame(128, 32, &Wire, -1);
        frame.setRotation(rotation);
        DistanceGlyphs::drawValue(frame, sensor * 32, field);
        int minimumX = 128, maximumX = -1, minimumY = 32, maximumY = -1;
        for (int row = 0; row < 32; ++row) {
          for (int col = 0; col < 128; ++col) {
            if (!frame.pixelAt(col, row)) continue;
            assert(row >= 8 && row <= 23);
            assert(col > sensor * 32 && col < (sensor + 1) * 32 - 1);
            if (col < minimumX) minimumX = col;
            if (col > maximumX) maximumX = col;
            if (row < minimumY) minimumY = row;
            if (row > maximumY) maximumY = row;
          }
        }
        assert(minimumX == sensor * 32 + (32 - width) / 2);
        assert(maximumX == minimumX + width - 1);
        assert(minimumY == (value == 101 ? 15 : 8) && maximumY == 23);
        if (value == 100) {
          // Explicitly require the equality bar, its separation, and chevron tip.
          for (int col = minimumX; col < minimumX + 9; ++col) {
            assert(frame.pixelAt(col, 20) && frame.pixelAt(col, 21));
            assert(!frame.pixelAt(col, 18) && !frame.pixelAt(col, 19));
          }
          assert(frame.pixelAt(minimumX + 8, 12));
          assert(!frame.pixelAt(minimumX, 12));
        }
      }
    }
  }
}

// Check every accepted integer measurement against successive exact half-tenth
// boundaries in micrometres, independently of the production division formula.
inline void checkAllMillimetres() {
  unsigned tenths = 0;
  int64_t nextBoundaryUm = 15240;
  for (int32_t mm = 0; mm <= 30000; ++mm) {
    while (static_cast<int64_t>(mm) * 1000 >= nextBoundaryUm) {
      ++tenths;
      nextBoundaryUm += 30480;
    }
    char field[5];
    memset(field, 'x', sizeof(field));
    DisplayProtocol::formatFeet(mm, field);
    if (tenths >= 100) {
      assert(std::string(field) == ">10");
    } else {
      const std::string expected = std::to_string(tenths / 10) + "." +
          std::to_string(tenths % 10);
      assert(std::string(field) == expected);
    }
    assert(field[3] == '\0' && field[4] == '\0');
  }
}

// The complete scene, including labels/footer, must rotate as one framebuffer.
// Logical sensor order is unchanged when the physical module is mounted upside down.
inline void checkSceneRotation() {
  const auto original = oled.pixels;
  oled.setRotation(2);
  paintedMode = DisplayMode::Unpainted;
  lastRefreshMs = fakeNow - Config::kRefreshIntervalMs;
  refreshOled();
  for (int row = 0; row < 32; ++row)
    for (int col = 0; col < 128; ++col)
      assert(oled.pixels[(31 - row) * 128 + 127 - col] == original[row * 128 + col]);
  expectFields("0.0", "9.9", ">10", "-.-");
  oled.setRotation(0);
  paintedMode = DisplayMode::Unpainted;
  lastRefreshMs = fakeNow - Config::kRefreshIntervalMs;
  refreshOled();
  assert(oled.pixels == original);
}
