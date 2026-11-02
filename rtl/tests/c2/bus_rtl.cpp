// c2-vmm "rtl" backend: each BAR0 access becomes a PCIe TLP on the
// AXI4-Stream port of the Verilator model (c2_sim_top.sv: c2_tlp + card +
// link + cartridge), completions are checked field by field; the
// cartridge's bus cycles are served by the bus_sim devices.
// Time step 2 ns: PCIe user clock 125 MHz, link and cartridge clocks
// 50 MHz, the cartridge's 6 ns after the card's.
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "Vc2_sim_top.h"
extern "C" {
#include "bus.h"
}

enum : uint32_t { BUS_LATENCY = 8, TIMEOUT = 50000000, BAR_BASE = 0xf0000000, REQUESTER = 0x0100, COMPLETER = 0x0200 };

struct beat {
    uint64_t data;
    uint8_t keep;
    bool last;
};

static Vc2_sim_top *top;
static struct bus *dev;
static uint64_t t;
static bool bus_busy;
static uint32_t bus_wait;
static bool rx_accepted;
static std::vector<beat> tx_beats;
static uint8_t tag;

[[noreturn]] static void fail(const char *what)
{
    fprintf(stderr, "c2-vmm rtl: %s\n", what);
    exit(1);
}

static uint32_t bswap(uint32_t v)
{
    return __builtin_bswap32(v);
}

#ifdef C2_P6
// the chipset's host port (rtl/ext/fpgacommon/p6_bif.v, HOSTPORT.md): one
// access per request, ready and rvalid in the same clock; byte lanes are
// natural, the access is the lowest live lane and the live lane count
static bool host_acked;
static void host_edge()
{
    top->host_ready = top->host_rvalid = 0;
    if (host_acked || !top->host_req) {
        host_acked = false;
        return;
    }
    int lane = __builtin_ctz(top->host_be), size = __builtin_popcount(top->host_be);
    uint32_t addr = (uint32_t)(top->host_addr << 3) + lane;
    int space = top->host_io ? BUS_IO : BUS_MEM;
    if (top->host_io) addr &= 0xffff;
    if (top->host_we)
        dev->write(dev, space, addr, size, (uint32_t)(top->host_wdata >> (8 * lane)));
    else
        top->host_rdata = (uint64_t)dev->read(dev, space, addr, size) << (8 * lane);
    top->host_ready = top->host_rvalid = 1;
    host_acked = true;
}
#endif

// the board: one bus cycle at a time, BUS_LATENCY cartridge clocks each
// (with C2_LOOP_TARGET the RTL target serves them: print its serial out;
// with C2_P6 the chipset's host port is served)
static void cclk_edge()
{
#ifdef C2_P6
    if (top->p6_err) {
        fprintf(stderr, "c2-vmm rtl: P6 chipset protocol error 0x%x\n", top->p6_err);
        exit(1);
    }
    host_edge();
    // the vector must stand before the chipset's INTA strobe: take it
    // when the cartridge starts the interrupt-acknowledge cycle
    if (top->bus_req && top->bus_inta && !bus_busy) {
        top->inta_vector = dev->inta(dev);
        bus_busy = true;
    } else if (!top->bus_req)
        bus_busy = false;
    top->intr = dev->intr(dev);
    return;
#endif
#ifdef C2_LOOP_TARGET
    if (top->serial_valid) {
        putchar(top->serial_byte);
        fflush(stdout);
    }
    return;
#endif
    if (top->bus_done) {
        top->bus_done = 0;
        bus_busy = false;
    } else if (bus_busy && --bus_wait == 0)
        top->bus_done = 1;
    if (!bus_busy && top->bus_req) {
        int size = 1 << top->bus_size;
        top->bus_err = 0;
        top->bus_rdata = 0;
        if (top->bus_inta)
            top->bus_rdata = dev->inta(dev);
        else if (top->bus_write)
            dev->write(dev, top->bus_space, top->bus_addr, size, top->bus_wdata);
        else
            top->bus_rdata = dev->read(dev, top->bus_space, top->bus_addr, size);
        bus_busy = true;
        bus_wait = BUS_LATENCY;
    }
    top->intr = dev->intr(dev);
}

// one 2 ns step; true when the user clock rose
static bool step()
{
    t++;
    bool u = t % 4 < 2, l = t % 10 < 5, c = (t + 7) % 10 < 5;
    bool u_rise = u && !top->uclk, c_rise = c && !top->cclk;
    if (u_rise) {
        if (top->tx_tvalid && top->tx_tready) tx_beats.push_back({top->tx_tdata, top->tx_tkeep, (bool)top->tx_tlast});
        rx_accepted = top->rx_tvalid && top->rx_tready;
    }
    top->uclk = u;
    top->lclk = l;
    top->cclk = c;
    top->eval();
    if (c_rise) {
        cclk_edge();
        top->eval();
    }
    return u_rise;
}

static void ucycle()
{
    while (!step()) {}
}

static void send_tlp(const std::vector<uint32_t> &dw)
{
    for (size_t i = 0; i < dw.size(); i += 2) {
        bool two = i + 1 < dw.size();
        top->rx_tdata = dw[i] | (two ? (uint64_t)dw[i + 1] << 32 : 0);
        top->rx_tkeep = two ? 0xff : 0x0f;
        top->rx_tlast = i + 2 >= dw.size();
        top->rx_tvalid = 1;
        top->rx_tuser = 1 << 2;   // BAR0 hit
        top->eval();
        for (uint32_t n = 0;; n++) {
            if (n == TIMEOUT) fail("timeout: TLP not accepted");
            ucycle();
            if (rx_accepted) break;
        }
    }
    top->rx_tvalid = 0;
    top->eval();
}

static uint64_t rtl_read(struct bar *, uint32_t off, int size)
{
    uint32_t len = size / 4, t_ag = tag++;
    tx_beats.clear();
    send_tlp({ len, REQUESTER << 16 | t_ag << 8 | (len == 2 ? 0xffu : 0x0fu), BAR_BASE + off });
    for (uint32_t n = 0; tx_beats.empty() || !tx_beats.back().last; n++) {
        if (n == TIMEOUT) fail("timeout: no completion");
        ucycle();
    }
    // CplD: {DW1, DW0}, {data 0, DW2}, [{-, data 1}]
    if (tx_beats.size() != (len == 2 ? 3u : 2u)) fail("completion: wrong beat count");
    uint32_t dw0 = (uint32_t)tx_beats[0].data, dw1 = (uint32_t)(tx_beats[0].data >> 32);
    uint32_t dw2 = (uint32_t)tx_beats[1].data;
    if (dw0 != (0x4a000000u | len)) fail("completion: DW0 (fmt, type, length)");
    if (dw1 != (COMPLETER << 16 | len * 4)) fail("completion: DW1 (completer, status, byte count)");
    if (dw2 != (REQUESTER << 16 | t_ag << 8 | (off & 0x7c))) fail("completion: DW2 (requester, tag, lower address)");
    if (tx_beats.back().keep != (len == 2 ? 0x0f : 0xff)) fail("completion: last beat keep");
    uint64_t v = bswap((uint32_t)(tx_beats[1].data >> 32));
    if (len == 2) v |= (uint64_t)bswap((uint32_t)tx_beats[2].data) << 32;
    return v;
}

static void rtl_write64(struct bar *, uint32_t off, uint64_t value)
{
    send_tlp({ 0x40000002u, REQUESTER << 16 | (uint32_t)tag++ << 8 | 0xffu, BAR_BASE + off,
               bswap((uint32_t)value), bswap((uint32_t)(value >> 32)) });
}

static void report()
{
    fprintf(stderr, "c2-vmm rtl: %.3f ms simulated\n", (double)t * 2e-6);
}

extern "C" struct bus *bus_rtl_open(const char *rom_path)
{
    dev = bus_sim_open(rom_path);
    if (!dev) return nullptr;
    top = new Vc2_sim_top;
    top->completer_id = COMPLETER;
    top->tx_tready = 1;
    top->serial_ready = 1;
    top->rst = 1;
    for (int i = 0; i < 100; i++) step();
    top->rst = 0;
    for (int i = 0; i < 100; i++) step();
    atexit(report);
    static struct bar bar = { rtl_read, rtl_write64, nullptr };
    return bus_bar_open(&bar);
}
