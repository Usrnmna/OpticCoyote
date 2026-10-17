#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "display_protocol.h"
#include "distance_glyphs.h"
#include "reverse_protocol.h"

/*
  Display-only ELEGOO Nano / ATmega328P, connected to the Pi by USB.
  The sensor Nano keeps optic_coyote_ultrasonic.ino. This second Nano receives
  leased reverse commands and shows rear-bumper sensors 1..4 left to right.
  The default idle view is blank; the OLED remains available for other content.
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
ReverseDisplayProtocol::Receiver reverseReceiver;
bool havePacket = false;
bool oledReady = false;
uint32_t lastPacketMs = 0;
uint32_t lastRefreshMs = 0;
uint32_t lastOledAttemptMs = 0;
char paintedValues[4][5] = {};
enum class DisplayMode : uint8_t { Unpainted, Idle, ReverseDistance };
DisplayMode paintedMode = DisplayMode::Unpainted;
uint32_t paintedToken = 0;

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
  paintedMode = DisplayMode::Unpainted;
  paintedToken = 0;
  oledReady = true;
}

// Consume at most one UART buffer per loop. No String allocation, blocking
// readStringUntil, or per-byte screen transfer; partial lines survive loops.
// Each byte uses its consumption time, so a command completed at an expired
// deadline cannot renew ownership using an earlier loop-entry timestamp.
void receiveDistances() {
  uint8_t budget = ReverseConfig::kReceiveBudgetBytes;
  while (budget-- && Serial.available() > 0) {
    const char byte = static_cast<char>(Serial.read());
    const uint32_t now = millis();
    if (ReverseConfig::kEnabled) {
      reverseReceiver.feed(byte, now);
    } else if (receiver.feed(byte)) {
      havePacket = true;
      lastPacketMs = now;
    }
  }
}

// ACK writes are short and nonblocking. A congested UART retains only the
// latest active token/request pair; release or expiry cancels a pending ACK.
void sendReverseAcknowledgement() {
  reverseReceiver.expire(millis());
  if (!ReverseConfig::kEnabled || !reverseReceiver.pendingAckToken) return;
  char acknowledgement[25];  // A,UINT32_MAX,UINT32_MAX plus LF and NUL.
  const int length = snprintf(acknowledgement, sizeof(acknowledgement),
      "A,%lu,%lu\n", static_cast<unsigned long>(reverseReceiver.pendingAckToken),
      static_cast<unsigned long>(reverseReceiver.pendingAckRequestId));
  const int availableBytes = Serial.availableForWrite();
  reverseReceiver.expire(millis());
  if (availableBytes < length || !reverseReceiver.pendingAckToken) return;
  Serial.write(reinterpret_cast<const uint8_t *>(acknowledgement), length);
  reverseReceiver.pendingAckToken = 0;
  reverseReceiver.pendingAckRequestId = 0;
}

// Idle owns the powered OLED outside reverse. Future content can draw here and
// return true when its buffer changed; returning false avoids redundant I2C
// transfers. The current implementation clears the previous view once.
bool renderIdle(uint32_t now) {
  (void)now;
  if (paintedMode == DisplayMode::Idle) return false;
  oled.clearDisplay();
  return true;
}

// Use the same freshness deadline when drawing and immediately before transfer.
// Unsigned elapsed arithmetic preserves the deadline across millis rollover.
bool distancePacketFresh(uint32_t now) {
  const bool packetAvailable = ReverseConfig::kEnabled
      ? reverseReceiver.havePacket : havePacket;
  const uint32_t packetMs = ReverseConfig::kEnabled
      ? reverseReceiver.lastPacketMs : lastPacketMs;
  return packetAvailable &&
      static_cast<uint32_t>(now - packetMs) < Config::kLinkTimeoutMs;
}

// Four fixed 32-pixel columns preserve bumper order. Custom 9x16 digits and
// the cap symbol fit between the small labels and shared footer; a narrow dot
// keeps decimal and unavailable fields compact. Missing/stale data uses -.-.
bool renderReverseDistance(uint32_t now, char (&values)[4][5]) {
  const int32_t *distances = ReverseConfig::kEnabled
      ? reverseReceiver.distances : receiver.distances;
  const bool fresh = distancePacketFresh(now);
  for (uint8_t sensor = 0; sensor < 4; ++sensor)
    DisplayProtocol::formatFeet(fresh ? distances[sensor] : -1,
                                values[sensor]);
  const bool sameSession = !ReverseConfig::kEnabled ||
      paintedToken == reverseReceiver.token;
  if (sameSession && paintedMode == DisplayMode::ReverseDistance &&
      memcmp(values, paintedValues, sizeof(values)) == 0) return false;

  oled.clearDisplay();
  for (uint8_t sensor = 0; sensor < 4; ++sensor) {
    const uint8_t left = sensor * 32;
    oled.setTextSize(1);
    oled.setCursor(left + 13, 0);
    oled.print(sensor + 1);
    DistanceGlyphs::drawValue(oled, left, values[sensor]);
  }
  oled.setTextSize(1);
  oled.setCursor(58, 25);
  // Values occupy y=8..23; row 24 separates them from the unit at y=25..31.
  oled.print(F("ft"));
  return true;
}

// Ownership chooses one renderer. Initialization, failed transfers and mode
// changes invalidate the cached view, including when distance values repeat.
void refreshOled() {
  uint32_t now = millis();
  reverseReceiver.expire(now);
  if (!oledReady) {
    if (static_cast<uint32_t>(now - lastOledAttemptMs) >= Config::kOledRetryMs)
      initializeOled(now);
    reverseReceiver.expire(millis());
    return;
  }
  if (static_cast<uint32_t>(now - lastRefreshMs) < Config::kRefreshIntervalMs)
    return;
  lastRefreshMs = now;
  const bool responds = oledResponds();
  now = millis();
  reverseReceiver.expire(now);
  if (!responds) {
    oledReady = false;
    lastOledAttemptMs = now;
    return;
  }
  DisplayMode mode = !ReverseConfig::kEnabled || reverseReceiver.active
      ? DisplayMode::ReverseDistance : DisplayMode::Idle;
  const bool freshAtRender = distancePacketFresh(now);
  char values[4][5];
  const bool changed = mode == DisplayMode::Idle ? renderIdle(now)
      : renderReverseDistance(now, values);
  if (!changed) return;
  now = millis();
  if (mode == DisplayMode::ReverseDistance && freshAtRender &&
      !distancePacketFresh(now)) {
    // Replace data that expired during drawing before it reaches the OLED.
    // Invalidate the cache even if the previous screen already showed -.-;
    // the current framebuffer contains the numeric view drawn above.
    paintedMode = DisplayMode::Unpainted;
    renderReverseDistance(now, values);
    now = millis();
  }
  reverseReceiver.expire(now);
  if (mode == DisplayMode::ReverseDistance && ReverseConfig::kEnabled &&
      !reverseReceiver.active) {
    // Discard a distance buffer whose ownership expired while it was drawn.
    paintedMode = DisplayMode::Unpainted;
    renderIdle(now);
    mode = DisplayMode::Idle;
  }
  const uint32_t renderedToken = reverseReceiver.token;
  Wire.clearWireTimeoutFlag();
  oled.display();
  const bool failed = Wire.getWireTimeoutFlag() || !oledResponds();
  now = millis();
  reverseReceiver.expire(now);
  if (failed) {
    oledReady = false;
    lastOledAttemptMs = now;
    return;
  }
  if (mode == DisplayMode::ReverseDistance)
    memcpy(paintedValues, values, sizeof(values));
  paintedMode = mode;
  paintedToken = mode == DisplayMode::ReverseDistance && ReverseConfig::kEnabled
      ? renderedToken : 0;
  // An I2C transfer already underway cannot be recalled. Expiry during that
  // transfer releases ownership here; the next scheduled refresh paints idle.
}

void setup() {
  Serial.begin(Config::kSerialBaud);
  Wire.begin();
  Wire.setWireTimeout(Config::kI2cTimeoutUs, true);
  initializeOled(millis());
}

void loop() {
  reverseReceiver.expire(millis());
  receiveDistances();
  sendReverseAcknowledgement();
  refreshOled();
}
