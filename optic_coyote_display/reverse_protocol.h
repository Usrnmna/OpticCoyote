#pragma once

#include "display_protocol.h"
#include "reverse_config.h"

namespace ReverseDisplayProtocol {

// Ownership and distance freshness are independent. Only R opens ownership;
// only a K with an increasing request identifier renews its lease. D cannot
// reopen a released or expired session. ACKs echo the latest accepted request.
class Receiver {
 public:
  bool active = false;
  bool havePacket = false;
  uint32_t token = 0;
  uint32_t lastPacketMs = 0;
  uint32_t pendingAckToken = 0;
  uint32_t pendingAckRequestId = 0;
  int32_t distances[DisplayProtocol::kSensorCount] = {-1, -1, -1, -1};

  // Expiry precedes command handling, including a K arriving at the deadline.
  void expire(uint32_t now) {
    if (active && static_cast<uint32_t>(now - lastKeepaliveMs_) >= leaseMs_)
      release();
  }

  // Release clears ownership, cached values and any ACK not yet transmitted.
  void release() {
    if (active) retiredToken_ = token;
    active = false;
    token = 0;
    pendingAckToken = 0;
    pendingAckRequestId = 0;
    clearDistances();
  }

  // Frames end only at LF; a single terminal CR permits CRLF transport.
  // Binary, oversized and malformed frames are discarded as complete units.
  void feed(char byte, uint32_t now) {
    expire(now);
    if (byte == '\n') {
      if (!discard_) {
        if (length_ && line_[length_ - 1] == '\r') --length_;
        line_[length_] = '\0';
        parse(now);
      }
      length_ = 0;
      discard_ = false;
      return;
    }
    if (discard_) return;
    if ((byte < ' ' && byte != '\r') || byte > '~' ||
        length_ >= ReverseConfig::kMaximumFrameBytes) {
      discard_ = true;
      return;
    }
    line_[length_++] = byte;
  }

 private:
  char line_[ReverseConfig::kMaximumFrameBytes + 1] = {};
  uint8_t length_ = 0;
  bool discard_ = false;
  uint32_t retiredToken_ = 0;
  uint32_t lastKeepaliveMs_ = 0;
  uint32_t leaseMs_ = 0;
  uint32_t requestId_ = 0;

  // Coalesce pending replies to the current accepted renewal request. A reply
  // identifies the outbound request whose age the host can bound independently.
  void acknowledge() {
    pendingAckToken = token;
    pendingAckRequestId = requestId_;
  }

  void clearDistances() {
    havePacket = false;
    lastPacketMs = 0;
    for (uint8_t i = 0; i < DisplayProtocol::kSensorCount; ++i)
      distances[i] = -1;
  }

  // Bounds are checked before multiplication, including uint32 token overflow.
  static bool unsignedField(const char *&cursor, uint32_t maximum,
                            uint32_t &value) {
    if (*cursor < '0' || *cursor > '9') return false;
    value = 0;
    do {
      const uint8_t digit = static_cast<uint8_t>(*cursor++ - '0');
      if (value > maximum / 10 ||
          (value == maximum / 10 && digit > maximum % 10)) return false;
      value = value * 10 + digit;
    } while (*cursor >= '0' && *cursor <= '9');
    return true;
  }

  // Parsing commits only complete validated commands. Invalid distance fields
  // cannot partially replace a previous packet or refresh its timestamp.
  void parse(uint32_t now) {
    if (length_ == 1 && line_[0] == 'X') {
      release();
      return;
    }
    if (length_ < 3 || line_[1] != ',') return;
    const char command = line_[0];
    const char *cursor = line_ + 2;
    uint32_t candidateToken;
    if (!unsignedField(cursor, UINT32_MAX, candidateToken) || !candidateToken)
      return;
    if (command == 'R') {
      uint32_t duration;
      if (*cursor != ',') return;
      ++cursor;
      if (!unsignedField(cursor, ReverseConfig::kMaximumLeaseMs, duration) ||
          *cursor || duration < ReverseConfig::kMinimumLeaseMs) return;
      if (active && token == candidateToken) {
        acknowledge();
        return;  // Retried acquisition neither resets data nor extends the lease.
      }
      if (candidateToken == retiredToken_) return;
      if (active) retiredToken_ = token;
      clearDistances();
      token = candidateToken;
      active = true;
      leaseMs_ = duration;
      lastKeepaliveMs_ = now;
      requestId_ = 0;
      acknowledge();
      return;
    }
    if (!active || candidateToken != token) return;
    if (command == 'K') {
      uint32_t candidateRequestId;
      if (*cursor != ',') return;
      ++cursor;
      if (!unsignedField(cursor, UINT32_MAX, candidateRequestId) || *cursor ||
          !candidateRequestId || candidateRequestId <= requestId_) return;
      lastKeepaliveMs_ = now;
      requestId_ = candidateRequestId;
      acknowledge();
      return;
    }
    if (command != 'D') return;
    int32_t candidate[DisplayProtocol::kSensorCount];
    for (uint8_t sensor = 0; sensor < DisplayProtocol::kSensorCount; ++sensor) {
      if (*cursor != ',') return;
      ++cursor;
      if (cursor[0] == '-' && cursor[1] == '1') {
        candidate[sensor] = -1;
        cursor += 2;
      } else {
        uint32_t distance;
        if (!unsignedField(cursor, DisplayProtocol::kMaximumDistanceMm,
                           distance)) return;
        candidate[sensor] = static_cast<int32_t>(distance);
      }
    }
    if (*cursor) return;
    memcpy(distances, candidate, sizeof(distances));
    havePacket = true;
    lastPacketMs = now;
  }
};
}  // namespace ReverseDisplayProtocol
