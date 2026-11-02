// Slot 1 C2 (plan/slot1_c2.md): the board bus as seen by the VMM. Every
// guest access outside its RAM becomes one bus cycle on the board.
#pragma once
#include <stdint.h>

enum { BUS_MEM = 0, BUS_IO = 1 };
// status(): INTR asserted; board reset (RESET# asserted, or a reset since
// the last call: bus cycles meanwhile are lost); A6# strap of the last reset
// (reset vector 000FFFF0h); A20M#, STPCLK# asserted; an NMI, INIT# or SMI#
// assertion since the last call
enum {
    BUS_INTR = 1, BUS_RESET = 2, BUS_LOW_VECTOR = 4, BUS_A20M = 8, BUS_STPCLK = 16,
    BUS_NMI = 32, BUS_INIT = 64, BUS_SMI = 128,
};
// Special Transaction sub-codes [PPRO1] 5.2.3.6
enum { BUS_SHUTDOWN = 1, BUS_HALT = 3, BUS_STOP_GRANT = 6 };

struct bus {
    // size 1, 2 or 4 bytes, naturally aligned (the VMM splits the rest)
    uint32_t (*read)(struct bus *b, int space, uint32_t addr, int size);
    void (*write)(struct bus *b, int space, uint32_t addr, int size, uint32_t value);
    // count I/O cycles of one size at one port (string I/O), data in buf
    void (*io_rep)(struct bus *b, uint16_t port, int size, uint32_t count, uint8_t *buf, int write);
    unsigned (*status)(struct bus *b);   // BUS_* flags above
    void (*special)(struct bus *b, int code);   // a Special Transaction
    uint8_t (*inta)(struct bus *b);   // interrupt-acknowledge cycle: the vector
    void *priv;
};

// FPGA bridge register block (BAR0, little endian), rtl/c2 implements it:
//   0x000 R   ID: 0x43324231 ("C2B1")
//   0x008 R   STATUS: bit 0 INTR asserted, bit 1 bus error, bit 2 protocol
//             error (bad BAR0 access or link byte), bit 3 board reset
//             (RESET# asserted or since the last read), bit 4 the A6# strap,
//             bits 5-6 A20M# / STPCLK# asserted, bits 7-9 an NMI / INIT# /
//             SMI# assertion; bits 1-3 and 7-9 sticky, read clears
//   0x010 R   RDATA: data of the last read cycle; the completion waits for it
//   0x018 R   INTA: runs an interrupt-acknowledge cycle, returns the vector
//   0x020 W   SPECIAL: a Special Transaction, the sub-code in bits 2:0
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
    C2B_ID = 0x000, C2B_STATUS = 0x008, C2B_RDATA = 0x010, C2B_INTA = 0x018, C2B_SPECIAL = 0x020,
    C2B_CYCLE = 0x100, C2B_REP = 0x180, C2B_WINDOW = 0x1000, C2B_WINDOW_SIZE = 0x1000,
    C2B_ID_VALUE = 0x43324231,
    C2B_ST_INTR = 1, C2B_ST_BUS_ERR = 2, C2B_ST_PROTO_ERR = 4, C2B_ST_RESET = 8, C2B_ST_LOW_VECTOR = 16,
    C2B_ST_A20M = 32, C2B_ST_STPCLK = 64, C2B_ST_NMI = 128, C2B_ST_INIT = 256, C2B_ST_SMI = 512,
};

// BAR0 accesses: the mapped PCI resource, or the bridge RTL model (bus_rtl.cpp)
struct bar {
    uint64_t (*read)(struct bar *bar, uint32_t off, int size);   // size 4 or 8
    void (*write64)(struct bar *bar, uint32_t off, uint64_t value);
    volatile uint8_t *base;
};

struct bus *bus_sim_open(const char *rom_path);
struct bus *bus_fpga_open(const char *bar_path);
struct bus *bus_bar_open(struct bar *bar);   // the bridge protocol on any BAR0
#ifdef C2_RTL
struct bus *bus_rtl_open(const char *rom_path);   // RTL model + bus_sim devices
#endif
