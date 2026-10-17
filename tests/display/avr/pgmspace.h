#pragma once
#include <cstdint>
// Host memory substitutes only for AVR flash reads; production uses avr-libc.
#define PROGMEM
inline uint16_t pgm_read_word(const uint16_t *address) { return *address; }
