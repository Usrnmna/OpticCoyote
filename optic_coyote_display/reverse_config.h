#pragma once

#include <stdint.h>

// Reverse ownership is the default. Defining OPTIC_COYOTE_STANDALONE=1 restores
// the independent D,mm1,mm2,mm3,mm4 receiver for an ungated installation.
#ifndef OPTIC_COYOTE_STANDALONE
#define OPTIC_COYOTE_STANDALONE 0
#endif

namespace ReverseConfig {
constexpr bool kEnabled = OPTIC_COYOTE_STANDALONE != 1;
constexpr uint32_t kMinimumLeaseMs = 200;
constexpr uint32_t kMaximumLeaseMs = 10000;
constexpr uint8_t kMaximumFrameBytes = 80;
constexpr uint8_t kReceiveBudgetBytes = 64;
}  // namespace ReverseConfig

static_assert(ReverseConfig::kMinimumLeaseMs > 0 &&
              ReverseConfig::kMinimumLeaseMs <= ReverseConfig::kMaximumLeaseMs &&
              ReverseConfig::kMaximumLeaseMs < 0x80000000UL,
              "Lease bounds must fit unsigned millis arithmetic");
static_assert(ReverseConfig::kMaximumFrameBytes >= 52 &&
              ReverseConfig::kMaximumFrameBytes < 255,
              "Receive storage must fit a complete distance command");
