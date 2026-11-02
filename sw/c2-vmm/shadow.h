// 440BX shadow RAM (PAM) of 0xc0000-0xfffff as KVM memslots (shadow.c)
#pragma once
#include <linux/kvm.h>
#include <stdint.h>
#include <sys/ioctl.h>

void shadow_init(uint8_t *ram, uint8_t *rom, uint64_t rom_size);
// a new VM: its memslots for the current map
void shadow_bind(int vm);
// a board reset: PAM0-PAM6 back to 0 (every segment to PCI / the ROM)
void shadow_reset(void);
// every guest I/O write (also forwarded to the bus): tracks PAM writes
void shadow_io_write(uint16_t port, int size, uint32_t value);
// a guest MMIO write: 1 if it went to the shadow RAM, 0 if it goes to the bus
int shadow_mmio_write(uint32_t addr, const uint8_t *data, int len);
