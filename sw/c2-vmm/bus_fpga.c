// The board bus through the C2 FPGA bridge: its BAR0 register block (bus.h),
// mapped from a sysfs PCI resource file (/sys/bus/pci/devices/<bdf>/resource0).
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include "bus.h"

enum { BAR_SIZE = C2B_WINDOW + C2B_WINDOW_SIZE };

struct fpga {
    struct bus bus;
    struct bar *bar;
    int reset_seen;   // a board reset not yet reported by status()
};

static struct bar *bar_of(struct bus *b)
{
    return ((struct fpga *)b->priv)->bar;
}

static uint32_t rd32(struct bus *b, uint32_t off)
{
    return (uint32_t)bar_of(b)->read(bar_of(b), off, 4);
}

static void wr64(struct bus *b, uint32_t off, uint64_t v)
{
    bar_of(b)->write64(bar_of(b), off, v);
}

static void cycle(struct bus *b, int space, int write, uint32_t addr, int size, uint32_t data)
{
    int log2_size = size == 4 ? 2 : size == 2 ? 1 : 0;
    wr64(b, C2B_CYCLE + 8 * (uint32_t)(space << 3 | write << 2 | log2_size), (uint64_t)data << 32 | addr);
}

// STATUS keeps a board reset for status(); the bus cycles it cut are
// expected to fail
static uint32_t read_status(struct bus *b)
{
    struct fpga *f = b->priv;
    uint32_t status = rd32(b, C2B_STATUS);
    if (status & C2B_ST_RESET) f->reset_seen = 1;
    if (f->reset_seen) status &= ~(uint32_t)C2B_ST_BUS_ERR;
    return status;
}

static void check_error(struct bus *b, int space, uint32_t addr)
{
    uint32_t status = read_status(b);
    if (status & (C2B_ST_BUS_ERR | C2B_ST_PROTO_ERR)) {
        fprintf(stderr, "c2-vmm: %s error at %s %08x\n", status & C2B_ST_BUS_ERR ? "bus" : "bridge protocol",
                space == BUS_IO ? "io" : "mem", addr);
        exit(1);
    }
}

static uint32_t fpga_read(struct bus *b, int space, uint32_t addr, int size)
{
    cycle(b, space, 0, addr, size, 0);
    uint32_t v = rd32(b, C2B_RDATA);
    check_error(b, space, addr);
    return v;
}

static void fpga_write(struct bus *b, int space, uint32_t addr, int size, uint32_t value)
{
    cycle(b, space, 1, addr, size, value);
}

// window copies in 8-byte accesses (the BAR is uncached: one TLP each)
static void fpga_io_rep(struct bus *b, uint16_t port, int size, uint32_t count, uint8_t *buf, int write)
{
    int log2_size = size == 4 ? 2 : size == 2 ? 1 : 0;
    uint32_t off = C2B_REP + 8 * (uint32_t)(write << 2 | log2_size);
    while (count) {
        uint32_t n = count < C2B_WINDOW_SIZE / (uint32_t)size ? count : C2B_WINDOW_SIZE / (uint32_t)size;
        uint32_t bytes = n * (uint32_t)size;
        if (write) {
            for (uint32_t i = 0; i < bytes; i += 8) {
                uint64_t v = 0;
                memcpy(&v, buf + i, bytes - i < 8 ? bytes - i : 8);
                wr64(b, C2B_WINDOW + i, v);
            }
            wr64(b, off, (uint64_t)n << 32 | port);
        } else {
            wr64(b, off, (uint64_t)n << 32 | port);
            for (uint32_t i = 0; i < bytes; i += 8) {
                uint64_t v = bar_of(b)->read(bar_of(b), C2B_WINDOW + i, 8);
                memcpy(buf + i, &v, bytes - i < 8 ? bytes - i : 8);
            }
            check_error(b, BUS_IO, port);
        }
        buf += bytes;
        count -= n;
    }
}

// polled every exit: also reports a bus error of a posted write cycle
static unsigned fpga_status(struct bus *b)
{
    struct fpga *f = b->priv;
    uint32_t status = read_status(b);
    if (status & (C2B_ST_BUS_ERR | C2B_ST_PROTO_ERR)) {
        fprintf(stderr, "c2-vmm: %s error (a write cycle)\n", status & C2B_ST_BUS_ERR ? "bus" : "bridge protocol");
        exit(1);
    }
    unsigned r = (status & C2B_ST_INTR ? BUS_INTR : 0u) | (f->reset_seen ? BUS_RESET : 0u)
               | (status & C2B_ST_LOW_VECTOR ? BUS_LOW_VECTOR : 0u);
    f->reset_seen = 0;
    return r;
}

static uint8_t fpga_inta(struct bus *b)
{
    return (uint8_t)rd32(b, C2B_INTA);
}

struct bus *bus_bar_open(struct bar *bar)
{
    struct fpga *f = calloc(1, sizeof(*f));
    if (!f) return NULL;
    f->bus = (struct bus){ fpga_read, fpga_write, fpga_io_rep, fpga_status, fpga_inta, f };
    f->bar = bar;
    uint32_t id = rd32(&f->bus, C2B_ID);
    if (id != C2B_ID_VALUE) {
        fprintf(stderr, "c2-vmm: BAR0 ID %08x, not the C2 bridge (%08x)\n", id, C2B_ID_VALUE);
        free(f);
        return NULL;
    }
    return &f->bus;
}

static uint64_t mmio_read(struct bar *bar, uint32_t off, int size)
{
    return size == 8 ? *(volatile uint64_t *)(bar->base + off) : *(volatile uint32_t *)(bar->base + off);
}

static void mmio_write64(struct bar *bar, uint32_t off, uint64_t value)
{
    *(volatile uint64_t *)(bar->base + off) = value;
}

struct bus *bus_fpga_open(const char *bar_path)
{
    int fd = open(bar_path, O_RDWR | O_SYNC | O_CLOEXEC);
    if (fd < 0) {
        fprintf(stderr, "c2-vmm: %s: %s\n", bar_path, strerror(errno));
        return NULL;
    }
    void *base = mmap(NULL, BAR_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (base == MAP_FAILED) {
        fprintf(stderr, "c2-vmm: mmap %s: %s\n", bar_path, strerror(errno));
        return NULL;
    }
    struct bar *bar = calloc(1, sizeof(*bar));
    if (!bar) return NULL;
    *bar = (struct bar){ mmio_read, mmio_write64, base };
    return bus_bar_open(bar);
}
