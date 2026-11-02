// Slot 1 C2 (plan/slot1_c2.md): the board bus as seen by the VMM. Every
// guest access outside its RAM becomes one bus cycle on the board.
#pragma once
#include <stdint.h>

enum { BUS_MEM = 0, BUS_IO = 1 };

struct bus {
    // size 1, 2 or 4 bytes, naturally aligned (the VMM splits the rest)
    uint32_t (*read)(struct bus *b, int space, uint32_t addr, int size);
    void (*write)(struct bus *b, int space, uint32_t addr, int size, uint32_t value);
    // count I/O cycles of one size at one port (string I/O), data in buf
    void (*io_rep)(struct bus *b, uint16_t port, int size, uint32_t count, uint8_t *buf, int write);
    int (*intr)(struct bus *b);       // INTR is asserted
    uint8_t (*inta)(struct bus *b);   // interrupt-acknowledge cycle: the vector
    void *priv;
};

// FPGA bridge register block (BAR0, little endian), rtl/c2 implements it:
//   0x000 R   ID: 0x43324231 ("C2B1")
//   0x008 R   STATUS: bit 0 INTR asserted, bit 1 bus error (sticky, read clears)
//   0x010 R   RDATA: data of the last read cycle; the completion waits for it
//   0x018 R   INTA: runs an interrupt-acknowledge cycle, returns the vector
//   0x100 W   cycle: one 64-bit write {data[63:32], addr[31:0]} at
//             0x100 + 8 * (space << 3 | write << 2 | log2 size)
//             (a write cycle is posted; a read cycle is followed by RDATA)
//   0x180 W   REP: one 64-bit write {count[63:32], port[15:0]} at
//             0x180 + 8 * (write << 2 | log2 size): count I/O cycles at
//             the port, data in WINDOW (count * size <= 4096; a write
//             fills WINDOW first, a read is followed by WINDOW reads)
//   0x1000    WINDOW: 4 KB
// The bridge consumes BAR0 requests strictly in order, one at a time: a
// cycle or REP command holds back every later request (PCIe flow control)
// until its bus cycles end, so WINDOW is never refilled under a running
// REP. Longest hold: a 4 KB REP of 8-bit ISA cycles, ~4 ms, inside the
// host's PCIe completion timeout (range A, 50 us-10 ms: set it to >= 10 ms).
enum {
    C2B_ID = 0x000, C2B_STATUS = 0x008, C2B_RDATA = 0x010, C2B_INTA = 0x018,
    C2B_CYCLE = 0x100, C2B_REP = 0x180, C2B_WINDOW = 0x1000, C2B_WINDOW_SIZE = 0x1000,
    C2B_ID_VALUE = 0x43324231,
};

struct bus *bus_sim_open(const char *rom_path);
struct bus *bus_fpga_open(const char *bar_path);
