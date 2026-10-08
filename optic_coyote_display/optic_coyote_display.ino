#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "display_protocol.h"

/*
  Display-only ELEGOO Nano / ATmega328P, connected to the Pi by USB.
  The sensor Nano keeps optic_coyote_ultrasonic.ino. This second Nano receives
  D,mm1,mm2,mm3,mm4 and shows rear-bumper sensors 1..4 from left to right.
  OLED: SSD1306, 128x32, I2C SDA=A4, SCL=A5. See docs/oled-display.md for power.
  Libraries: Adafruit SSD1306, Adafruit GFX Library, Adafruit BusIO.
*/

// INSTALLATION SETTINGS: edit here, then rebuild/upload the display Nano.
namespace Config {
constexpr uint32_t kSerialBaud = 115200;
constexpr uint8_t kOledAddress = 0x3C;  // Change to 0x3D only if the module uses it.
constexpr int8_t kOledResetPin = -1;   // Four-pin modules have no reset pin.
constexpr uint8_t kRotation = 0;      // 2 rotates 180 degrees; order stays 1..4.
constexpr uint32_t kLinkTimeoutMs = 2000;
constexpr uint32_t kRefreshIntervalMs = 100;
constexpr uint32_t kOledRetryMs = 1000;
constexpr uint32_t kI2cTimeoutUs = 25000;
}  // namespace Config

static_assert(Config::kRotation == 0 || Config::kRotation == 2,
              "Use landscape rotation 0 or 2 for four columns");
static_assert(Config::kLinkTimeoutMs > 0 && Config::kLinkTimeoutMs < 0x80000000UL,
              "Link timeout must fit millis arithmetic");
static_assert(Config::kRefreshIntervalMs >= 100,
              "Limit full-buffer OLED transfers to 10 per second");

Adafruit_SSD1306 oled(128, 32, &Wire, Config::kOledResetPin);
DisplayProtocol::Receiver receiver;
bool havePacket = false;
bool oledReady = false;
uint32_t lastPacketMs = 0;
uint32_t lastRefreshMs = 0;
uint32_t lastOledAttemptMs = 0;
char paintedValues[4][5] = {};

// Check the address separately: Adafruit begin() reports allocation success,
// which alone does not establish that a display answered on the I2C bus.
bool oledResponds() {
  Wire.beginTransmission(Config::kOledAddress);
  return Wire.endTransmission() == 0;
}

// Attempt initialization at boot or after an I2C disconnection. Wire timeout
// bounds a stuck bus; the main loop keeps draining serial while OLED is absent.
void initializeOled(uint32_t now) {
  lastOledAttemptMs = now;
  if (!oledResponds()) return;
  if (!oled.begin(SSD1306_SWITCHCAPVCC, Config::kOledAddress, true, false)) return;
  oled.setRotation(Config::kRotation);
  oled.setTextWrap(false);
  oled.setTextColor(SSD1306_WHITE);
  memset(paintedValues, 0, sizeof(paintedValues));
  oledReady = true;
}

// Consume at most one UART buffer per loop. No String allocation, blocking
// readStringUntil, or per-byte screen transfer; partial lines survive loops.
void receiveDistances(uint32_t now) {
  uint8_t budget = 64;
  while (budget-- && Serial.available() > 0) {
    if (receiver.feed(static_cast<char>(Serial.read()))) {
      havePacket = true;
      lastPacketMs = now;
    }
  }
}

// Four fixed 32-pixel columns. The default font is 6 pixels wide; even "98.4"
// fits with margins. Doubling height makes values 16 pixels tall without
// reducing the four-value layout. Missing/stale input is visibly unavailable.
void refreshOled(uint32_t now) {
  if (!oledReady) {
    if (static_cast<uint32_t>(now - lastOledAttemptMs) >= Config::kOledRetryMs)
      initializeOled(now);
    return;
  }
  if (static_cast<uint32_t>(now - lastRefreshMs) < Config::kRefreshIntervalMs)
    return;
  lastRefreshMs = now;
  if (!oledResponds()) {
    oledReady = false;
    lastOledAttemptMs = now;
    return;
  }
  const bool fresh = havePacket &&
      static_cast<uint32_t>(now - lastPacketMs) < Config::kLinkTimeoutMs;
  char values[4][5];
  for (uint8_t sensor = 0; sensor < 4; ++sensor)
    DisplayProtocol::formatFeet(fresh ? receiver.distances[sensor] : -1,
                                values[sensor]);
  if (memcmp(values, paintedValues, sizeof(values)) == 0) return;

  oled.clearDisplay();
  for (uint8_t sensor = 0; sensor < 4; ++sensor) {
    const uint8_t left = sensor * 32;
    oled.setTextSize(1);
    oled.setCursor(left + 13, 0);
    oled.print(sensor + 1);
    oled.setTextSize(1, 2);
    oled.setCursor(left + 4, 11);
    oled.print(values[sensor]);
  }
  oled.setTextSize(1);
  oled.setCursor(58, 25);
  // Values occupy y=11..24 (seven glyph rows doubled); unit fits y=25..31.
  oled.print(F("ft"));
  Wire.clearWireTimeoutFlag();
  oled.display();
  if (Wire.getWireTimeoutFlag() || !oledResponds()) {
    oledReady = false;
    lastOledAttemptMs = now;
    return;
  }
  memcpy(paintedValues, values, sizeof(values));
}

void setup() {
  Serial.begin(Config::kSerialBaud);
  Wire.begin();
  Wire.setWireTimeout(Config::kI2cTimeoutUs, true);
  initializeOled(millis());
}

void loop() {
  const uint32_t now = millis();
  receiveDistances(now);
  refreshOled(now);
}
