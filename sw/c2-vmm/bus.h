// Slot 1 C2 (plan/slot1_c2.md): the board bus as seen by the VMM. Every
// guest access outside its RAM becomes one bus cycle on the board.
#pragma once
#include <stdint.h>

enum { BUS_MEM = 0, BUS_IO = 1 };

struct bus {
    // size 1, 2 or 4 bytes, naturally aligned (the VMM splits the rest)
    uint32_t (*read)(struct bus *b, int space, uint32_t addr, int size);
    void (*write)(struct bus *b, int space, uint32_t addr, int size, uint32_t value);
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
enum {
    C2B_ID = 0x000, C2B_STATUS = 0x008, C2B_RDATA = 0x010, C2B_INTA = 0x018, C2B_CYCLE = 0x100,
    C2B_ID_VALUE = 0x43324231,
};

struct bus *bus_sim_open(const char *rom_path);
struct bus *bus_fpga_open(const char *bar_path);
