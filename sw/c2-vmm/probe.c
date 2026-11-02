// c2-probe: latency and throughput of the C2 bridge, for the card bring-up
// with the loopback bitstream (rtl/c2/xilinx/build.tcl with a ROM) or the
// sim devices; it uses their scratch RAM at 0xd0000 and FIFO at 0x1f0.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "bus.h"

enum { SCRATCH = 0xd0000, FIFO_PORT = 0x1f0, REP_BYTES = 4096 };

static double now_us(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec * 1e6 + (double)t.tv_nsec / 1e3;
}

static void check(const char *what, uint32_t got, uint32_t want)
{
    if (got == want) return;
    fprintf(stderr, "c2-probe: %s: %08x, expected %08x\n", what, got, want);
    exit(1);
}

int main(int argc, char **argv)
{
    int count = argc == 4 ? atoi(argv[3]) : 10000;
    struct bus *b = argc < 3 || argc > 4 ? NULL
                  : !strcmp(argv[1], "sim") ? bus_sim_open(argv[2])
                  : !strcmp(argv[1], "fpga") ? bus_fpga_open(argv[2]) : NULL;
    if (!b || count < 100) {
        fprintf(stderr, "usage: c2-probe sim <rom> | fpga /sys/bus/pci/devices/<bdf>/resource0 [count >= 100]\n");
        return 1;
    }

    double t = now_us();
    for (int i = 0; i < count; i++) b->intr(b);
    printf("STATUS read (PCIe round trip): %.2f us\n", (now_us() - t) / count);

    t = now_us();
    for (int i = 0; i < count; i++) b->write(b, BUS_MEM, SCRATCH, 4, (uint32_t)i);
    b->intr(b);   // after the posted writes; reports their errors
    printf("memory write cycle (posted):   %.2f us\n", (now_us() - t) / count);

    t = now_us();
    for (int i = 0; i < count; i++) check("scratch read", b->read(b, BUS_MEM, SCRATCH, 4), (uint32_t)count - 1);
    printf("memory read cycle:             %.2f us\n", (now_us() - t) / count);

    static uint8_t out[REP_BYTES], in[REP_BYTES];
    int reps = count / 100;
    t = now_us();
    for (int r = 0; r < reps; r++) {
        for (int i = 0; i < REP_BYTES; i++) out[i] = (uint8_t)(i * 7 + r);
        b->io_rep(b, FIFO_PORT, 2, REP_BYTES / 2, out, 1);
        b->io_rep(b, FIFO_PORT, 2, REP_BYTES / 2, in, 0);
        if (memcmp(out, in, REP_BYTES)) check("FIFO round trip, first differing byte", 1, 0);
    }
    printf("REP 16-bit 4 KB out + in:      %.1f MB/s\n", 2.0 * REP_BYTES * reps / (now_us() - t));
    return 0;
}
