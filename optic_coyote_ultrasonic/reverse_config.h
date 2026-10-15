#pragma once

// Reverse acquisition settings. Rebuild/upload after editing this header.
// Standalone builds retain continuous ranging and the legacy START/STOP CSV
// transport. Reverse builds require a renewable, session-tagged acquisition lease.
#ifndef OPTIC_COYOTE_STANDALONE
#define OPTIC_COYOTE_STANDALONE 0
#endif
namespace ReverseConfig {
#if defined(OPTIC_COYOTE_STANDALONE) && OPTIC_COYOTE_STANDALONE
constexpr bool kEnabled = false;
#else
constexpr bool kEnabled = true;
#endif
constexpr uint32_t kReportIntervalMs = 100;
constexpr uint32_t kStaleMs = 1500;
constexpr uint32_t kMinimumLeaseMs = 200;
constexpr uint32_t kMaximumLeaseMs = 10000;
// Wire implementations exposing WIRE_HAS_TIMEOUT bound each bus operation.
constexpr uint32_t kI2cTimeoutUs = 25000;
}  // namespace ReverseConfig

static_assert(ReverseConfig::kReportIntervalMs > 0 &&
                  ReverseConfig::kReportIntervalMs < 0x80000000UL &&
                  ReverseConfig::kStaleMs > 0 &&
                  ReverseConfig::kStaleMs < 0x80000000UL,
              "Report and freshness intervals must fit wrap-safe arithmetic");
static_assert(ReverseConfig::kMinimumLeaseMs >= 200 &&
                  ReverseConfig::kMinimumLeaseMs <= ReverseConfig::kMaximumLeaseMs &&
                  ReverseConfig::kMaximumLeaseMs <= 10000,
              "Acquisition lease range must remain within 200..10000 ms");
static_assert(ReverseConfig::kI2cTimeoutUs > 0,
              "Wire timeout must be positive");
