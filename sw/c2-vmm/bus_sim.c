// Test bus without the board: the ROM file at the top of 4 GB, a serial
// transmitter at 0x3f8 (stdout), POST codes at 0x80 (stderr), an exit port at
// 0xf4 (the written byte is the exit code), 256 bytes of MMIO scratch at
// 0xd0000 and at 0xa0000, an interrupt source at 0xf5 (writing N asserts
// INTR, acknowledged with vector 0x20 + N) and at 0xf7 (writing N asserts
// INTR N ms later, vector 0x28), a 4 KB byte FIFO at 0x1f0 (writes push,
// reads pop; empty pops 0xff), a board reset when 0xcf9 is written with
// bits 2:1 set (the 440BX hard reset), the PIIX4 port 0x92 (bit 1 FAST_A20:
// A20M# = !bit 1, bit 0 0 -> 1: INIT#), the CPU pin test port 0xf8 (write
// bit 0: an NMI, bit 1: STPCLK# until a Stop Grant Acknowledge; read: Halt
// count << 8 | Stop Grant count) and Special Transactions (Shutdown ->
// INIT#, as the PIIX4 does). Anything else floats high.
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "bus.h"

struct sim {
    struct bus bus;
    uint8_t *rom;
    uint32_t rom_base;
    uint8_t scratch[2][256];
    int intr_on, reset, stpclk, nmi, init;
    uint8_t port92, halts, stop_grants;
    uint8_t vector;
    double intr_at;                  // 0xf7: when INTR rises (0: none)
    uint8_t fifo[4096];
    uint32_t fifo_head, fifo_tail;   // free-running byte counts
};

static double now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + 1e-9 * (double)t.tv_nsec;
}

static uint8_t *scratch_at(struct sim *s, int space, uint32_t addr)
{
    if (space != BUS_MEM) return NULL;
    if (addr >= 0xd0000 && addr < 0xd0100) return s->scratch[0] + (addr - 0xd0000);
    if (addr >= 0xa0000 && addr < 0xa0100) return s->scratch[1] + (addr - 0xa0000);
    return NULL;
}

static uint32_t sim_read(struct bus *b, int space, uint32_t addr, int size)
{
    struct sim *s = b->priv;
    uint32_t v = 0;
    if (space == BUS_MEM && addr >= s->rom_base) {
        memcpy(&v, s->rom + (addr - s->rom_base), size);
        return v;
    }
    uint8_t *scratch = scratch_at(s, space, addr);
    if (scratch) {
        memcpy(&v, scratch, size);
        return v;
    }
    if (space == BUS_IO && addr == 0x3fd) return 0x60;   // LSR: transmitter empty
    if (space == BUS_IO && addr == 0x92) return s->port92;
    if (space == BUS_IO && addr == 0xf8) return ((uint32_t)s->halts << 8 | s->stop_grants) & ((1u << 8 * size) - 1);
    if (space == BUS_IO && addr == 0x1f0) {
        for (int i = 0; i < size; i++)
            v |= (uint32_t)(s->fifo_tail != s->fifo_head ? s->fifo[s->fifo_tail++ % sizeof(s->fifo)] : 0xff) << 8 * i;
        return v;
    }
    return size == 4 ? 0xffffffffu : (1u << 8 * size) - 1;
}

static void sim_write(struct bus *b, int space, uint32_t addr, int size, uint32_t value)
{
    struct sim *s = b->priv;
    uint8_t *scratch = scratch_at(s, space, addr);
    if (scratch) {
        memcpy(scratch, &value, size);
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
    else if (addr == 0xf7)
        s->intr_at = now() + 1e-3 * (value & 0xff);
    else if (addr == 0xcf9 && (value & 6) == 6)
        s->reset = 1;
    else if (addr == 0x92) {
        if (value & 1 && !(s->port92 & 1)) s->init = 1;
        s->port92 = (uint8_t)value;
    } else if (addr == 0xf8) {
        if (value & 1) s->nmi = 1;
        if (value & 2) s->stpclk = 1;
    }
    else if (addr == 0x1f0) {
        for (int i = 0; i < size; i++) {
            if (s->fifo_head - s->fifo_tail == sizeof(s->fifo)) {
                fprintf(stderr, "c2-vmm sim: FIFO at 0x1f0 full\n");
                exit(1);
            }
            s->fifo[s->fifo_head++ % sizeof(s->fifo)] = (uint8_t)(value >> 8 * i);
        }
    } else if (addr == 0xf5) {
        s->intr_on = 1;
        s->vector = (uint8_t)(0x20 + (value & 0xff));
    }
}

static void sim_io_rep(struct bus *b, uint16_t port, int size, uint32_t count, uint8_t *buf, int write)
{
    for (uint32_t i = 0; i < count; i++, buf += size) {
        uint32_t v = 0;
        if (write) {
            memcpy(&v, buf, (size_t)size);
            sim_write(b, BUS_IO, port, size, v);
        } else {
            v = sim_read(b, BUS_IO, port, size);
            memcpy(buf, &v, (size_t)size);
        }
    }
}

static unsigned sim_status(struct bus *b)
{
    struct sim *s = b->priv;
    unsigned st = 0;
    if (s->reset) {   // the devices' state at a board reset
        s->reset = s->intr_on = s->stpclk = s->nmi = s->init = 0;
        s->intr_at = 0;
        s->port92 = 0;
        st = BUS_RESET;
    }
    if (s->intr_at && now() >= s->intr_at) {
        s->intr_at = 0;
        s->intr_on = 1;
        s->vector = 0x28;
    }
    st |= (s->intr_on ? BUS_INTR : 0u) | (s->port92 & 2 ? 0u : BUS_A20M) | (s->stpclk ? BUS_STPCLK : 0u)
        | (s->nmi ? BUS_NMI : 0u) | (s->init ? BUS_INIT : 0u);
    s->nmi = s->init = 0;
    return st;
}

static void sim_special(struct bus *b, int code)
{
    struct sim *s = b->priv;
    if (code == BUS_SHUTDOWN) s->init = 1;
    else if (code == BUS_HALT) s->halts++;
    else if (code == BUS_STOP_GRANT) {
        s->stpclk = 0;
        s->stop_grants++;
    } else {
        fprintf(stderr, "c2-vmm sim: unexpected Special Transaction %d\n", code);
        exit(1);
    }
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
    s->bus = (struct bus){ sim_read, sim_write, sim_io_rep, sim_status, sim_special, sim_inta, s };
    return &s->bus;
}
