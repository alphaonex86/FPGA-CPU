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

static volatile uint8_t *bar_of(struct bus *b)
{
    return b->priv;
}

static uint32_t rd32(struct bus *b, uint32_t off)
{
    return *(volatile uint32_t *)(bar_of(b) + off);
}

static void cycle(struct bus *b, int space, int write, uint32_t addr, int size, uint32_t data)
{
    int log2_size = size == 4 ? 2 : size == 2 ? 1 : 0;
    uint32_t off = C2B_CYCLE + 8 * (space << 3 | write << 2 | log2_size);
    *(volatile uint64_t *)(bar_of(b) + off) = (uint64_t)data << 32 | addr;
}

static void check_error(struct bus *b, int space, uint32_t addr)
{
    if (rd32(b, C2B_STATUS) & 2) {
        fprintf(stderr, "c2-vmm: bus error at %s %08x\n", space == BUS_IO ? "io" : "mem", addr);
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
    while (count) {
        uint32_t n = count < C2B_WINDOW_SIZE / (uint32_t)size ? count : C2B_WINDOW_SIZE / (uint32_t)size;
        uint32_t bytes = n * (uint32_t)size;
        volatile uint64_t *win = (volatile uint64_t *)(bar_of(b) + C2B_WINDOW);
        int log2_size = size == 4 ? 2 : size == 2 ? 1 : 0;
        uint32_t off = C2B_REP + 8 * (uint32_t)(write << 2 | log2_size);
        if (write) {
            for (uint32_t i = 0; i < bytes; i += 8) {
                uint64_t v = 0;
                memcpy(&v, buf + i, bytes - i < 8 ? bytes - i : 8);
                win[i / 8] = v;
            }
            *(volatile uint64_t *)(bar_of(b) + off) = (uint64_t)n << 32 | port;
        } else {
            *(volatile uint64_t *)(bar_of(b) + off) = (uint64_t)n << 32 | port;
            (void)rd32(b, C2B_REP_DONE);
            for (uint32_t i = 0; i < bytes; i += 8) {
                uint64_t v = win[i / 8];
                memcpy(buf + i, &v, bytes - i < 8 ? bytes - i : 8);
            }
            check_error(b, BUS_IO, port);
        }
        buf += bytes;
        count -= n;
    }
}

// polled every exit: also reports a bus error of a posted write cycle
static int fpga_intr(struct bus *b)
{
    uint32_t status = rd32(b, C2B_STATUS);
    if (status & 2) {
        fprintf(stderr, "c2-vmm: bus error (a write cycle)\n");
        exit(1);
    }
    return status & 1;
}

static uint8_t fpga_inta(struct bus *b)
{
    return (uint8_t)rd32(b, C2B_INTA);
}

struct bus *bus_fpga_open(const char *bar_path)
{
    int fd = open(bar_path, O_RDWR | O_SYNC | O_CLOEXEC);
    if (fd < 0) {
        fprintf(stderr, "c2-vmm: %s: %s\n", bar_path, strerror(errno));
        return NULL;
    }
    void *bar = mmap(NULL, BAR_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (bar == MAP_FAILED) {
        fprintf(stderr, "c2-vmm: mmap %s: %s\n", bar_path, strerror(errno));
        return NULL;
    }
    struct bus *b = calloc(1, sizeof(*b));
    if (!b) return NULL;
    *b = (struct bus){ fpga_read, fpga_write, fpga_io_rep, fpga_intr, fpga_inta, bar };
    uint32_t id = rd32(b, C2B_ID);
    if (id != C2B_ID_VALUE) {
        fprintf(stderr, "c2-vmm: %s: ID %08x, not the C2 bridge (%08x)\n", bar_path, id, C2B_ID_VALUE);
        return NULL;
    }
    return b;
}
