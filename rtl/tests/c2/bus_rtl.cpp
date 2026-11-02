// c2-vmm "rtl" backend: BAR0 accesses drive the Verilator model of the
// bridge (c2_sim_top.sv: card + link + cartridge); the cartridge's bus
// cycles are served by the bus_sim devices, BUS_LATENCY clocks each.
#include <cstdio>
#include <cstdlib>
#include "Vc2_sim_top.h"
extern "C" {
#include "bus.h"
}

enum { BUS_LATENCY = 8, TIMEOUT = 10000000 };

static Vc2_sim_top *top;
static struct bus *dev;
static int bus_wait;    // clocks left in the current bus cycle; -1 none
static uint64_t clocks;

static void tick()
{
    top->clk = 0;
    top->eval();
    top->intr = dev->intr(dev);
    top->bus_done = 0;
    if (top->bus_req && bus_wait < 0) {
        int size = 1 << top->bus_size;
        top->bus_err = 0;
        top->bus_rdata = 0;
        if (top->bus_inta)
            top->bus_rdata = dev->inta(dev);
        else if (top->bus_write)
            dev->write(dev, top->bus_space, top->bus_addr, size, top->bus_wdata);
        else
            top->bus_rdata = dev->read(dev, top->bus_space, top->bus_addr, size);
        bus_wait = BUS_LATENCY;
    }
    if (bus_wait == 0) top->bus_done = 1;
    if (bus_wait >= 0) bus_wait--;
    top->eval();
    top->clk = 1;
    top->eval();
    clocks++;
}

static void wait_for(bool (*cond)(), const char *what)
{
    for (int i = 0; !cond(); i++) {
        if (i == TIMEOUT) {
            fprintf(stderr, "c2-vmm rtl: timeout waiting for %s\n", what);
            exit(1);
        }
        tick();
    }
}

static void request(bool write, uint32_t off, uint64_t value)
{
    top->req_valid = 1;
    top->req_write = write;
    top->req_addr = off;
    top->req_wdata = value;
    top->eval();
    wait_for([] { return (bool)top->req_ready; }, "req_ready");
    tick();
    top->req_valid = 0;
}

static uint64_t rtl_read(struct bar *, uint32_t off, int size)
{
    request(false, off, 0);
    wait_for([] { return (bool)top->rsp_valid; }, "rsp_valid");
    uint64_t v = top->rsp_data;
    tick();
    return size == 8 ? v : (uint32_t)v;
}

static void rtl_write64(struct bar *, uint32_t off, uint64_t value)
{
    request(true, off, value);
}

static void report()
{
    fprintf(stderr, "c2-vmm rtl: %llu bridge clocks\n", (unsigned long long)clocks);
}

extern "C" struct bus *bus_rtl_open(const char *rom_path)
{
    dev = bus_sim_open(rom_path);
    if (!dev) return nullptr;
    top = new Vc2_sim_top;
    bus_wait = -1;
    top->rst = 1;
    for (int i = 0; i < 4; i++) tick();
    top->rst = 0;
    tick();
    atexit(report);
    static struct bar bar = { rtl_read, rtl_write64, nullptr };
    return bus_bar_open(&bar);
}
