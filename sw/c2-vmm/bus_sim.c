// Test bus without the board: the ROM file at the top of 4 GB, a serial
// transmitter at 0x3f8 (stdout), POST codes at 0x80 (stderr), an exit port at
// 0xf4 (the written byte is the exit code), 256 bytes of MMIO scratch at
// 0xd0000, and an interrupt source at 0xf5: writing N asserts INTR,
// acknowledged with vector 0x20 + N. Anything else floats high.
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bus.h"

struct sim {
    struct bus bus;
    uint8_t *rom;
    uint32_t rom_base;
    uint8_t scratch[256];
    int intr_on;
    uint8_t vector;
};

static uint32_t sim_read(struct bus *b, int space, uint32_t addr, int size)
{
    struct sim *s = b->priv;
    uint32_t v = 0;
    if (space == BUS_MEM && addr >= s->rom_base) {
        memcpy(&v, s->rom + (addr - s->rom_base), size);
        return v;
    }
    if (space == BUS_MEM && addr >= 0xd0000 && addr < 0xd0100) {
        memcpy(&v, s->scratch + (addr - 0xd0000), size);
        return v;
    }
    if (space == BUS_IO && addr == 0x3fd) return 0x60;   // LSR: transmitter empty
    return size == 4 ? 0xffffffffu : (1u << 8 * size) - 1;
}

static void sim_write(struct bus *b, int space, uint32_t addr, int size, uint32_t value)
{
    struct sim *s = b->priv;
    if (space == BUS_MEM && addr >= 0xd0000 && addr < 0xd0100) {
        memcpy(s->scratch + (addr - 0xd0000), &value, size);
        return;
    }
    if (space != BUS_IO) return;
    if (addr == 0x3f8) {
        putchar((int)(value & 0xff));
        fflush(stdout);
    } else if (addr == 0x80)
        fprintf(stderr, "POST %02x\n", value & 0xff);
    else if (addr == 0xf4)
        exit((int)(value & 0xff));
    else if (addr == 0xf5) {
        s->intr_on = 1;
        s->vector = (uint8_t)(0x20 + (value & 0xff));
    }
}

static int sim_intr(struct bus *b)
{
    return ((struct sim *)b->priv)->intr_on;
}

static uint8_t sim_inta(struct bus *b)
{
    struct sim *s = b->priv;
    s->intr_on = 0;
    return s->vector;
}

struct bus *bus_sim_open(const char *rom_path)
{
    FILE *f = fopen(rom_path, "rb");
    if (!f) {
        fprintf(stderr, "c2-vmm: %s: %s\n", rom_path, strerror(errno));
        return NULL;
    }
    struct sim *s = calloc(1, sizeof(*s));
    if (!s) {
        fclose(f);
        return NULL;
    }
    long n = fseek(f, 0, SEEK_END) ? -1 : ftell(f);
    if (n <= 0 || n > 0x100000 || fseek(f, 0, SEEK_SET) || !(s->rom = malloc((size_t)n))
        || fread(s->rom, 1, (size_t)n, f) != (size_t)n) {
        fprintf(stderr, "c2-vmm: %s: unreadable, empty or above 1 MB\n", rom_path);
        fclose(f);
        free(s->rom);
        free(s);
        return NULL;
    }
    s->rom_base = (uint32_t)(0x100000000ull - (uint64_t)n);
    fclose(f);
    s->bus = (struct bus){ sim_read, sim_write, sim_intr, sim_inta, s };
    return &s->bus;
}
