// M2 driver: clocks core_top until HLT (or an unsupported instruction, or
// the cycle limit). Usage: core_tb +image=<hex> +trace=<file> [+max=<cycles>]
// +ticks=<cycles> [+mark=<hex EIP>]: a benchmark (rtl/tools/x86_bench.sh) runs exactly that many cycles
// from the second retirement into the mark EIP (after its warm-up), no HLT; the IPC of that window.
// A model built with --trace: +vcd=<file> [+vcd_cycles=<n>, default 10000] [+vcd_ns=<clock period,
// default 30>]: every signal over the first n cycles of the window (activity for quartus_pow).
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "Vcore_top.h"
#include "verilated.h"
#if VM_TRACE
#include "verilated_vcd_c.h"
#endif

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    long max = 1000000, ticks = 0, warm = 20000000, vcd_n = 10000, vcd_ps = 30000;
    const char *vcd = nullptr;
    for (int i = 1; i < argc; i++) {
        if (!strncmp(argv[i], "+max=", 5)) max = atol(argv[i] + 5);
        if (!strncmp(argv[i], "+ticks=", 7)) ticks = atol(argv[i] + 7);
        if (!strncmp(argv[i], "+vcd=", 5)) vcd = argv[i] + 5;
        if (!strncmp(argv[i], "+vcd_cycles=", 12)) vcd_n = atol(argv[i] + 12);
        if (!strncmp(argv[i], "+vcd_ns=", 8)) vcd_ps = (long)(atof(argv[i] + 8) * 1000);
    }
    Vcore_top top;
#if VM_TRACE
    VerilatedVcdC *tf = nullptr;
    if (vcd) {
        if (!ticks) { fprintf(stderr, "FAIL +vcd needs +ticks\n"); return 1; }
        Verilated::traceEverOn(true);
        tf = new VerilatedVcdC;
        top.trace(tf, 99);
        tf->set_time_unit("1ps");
        tf->set_time_resolution("1ps");
        tf->open(vcd);
        if (!tf->isOpen()) { fprintf(stderr, "FAIL cannot write %s\n", vcd); return 1; }
    }
#else
    if (vcd) { fprintf(stderr, "FAIL +vcd needs a model built with --trace\n"); return 1; }
#endif
    top.rst = 1;
    for (int i = 0; i < 4; i++) { top.clk = 0; top.eval(); top.clk = 1; top.eval(); }
    top.rst = 0;
    long c = 0, c0 = -1;                 // c0: the clock the tick window opened (top.marked)
    unsigned i0 = 0;
    for (; !top.halted && !Verilated::gotFinish(); c++) {
        if (ticks && c0 < 0 && top.marked) { c0 = c; i0 = top.insns; }
        if (ticks ? (c0 >= 0 ? c - c0 == ticks : c == warm) : c == max) break;
        top.clk = 0; top.eval();
#if VM_TRACE
        bool dump = tf && c0 >= 0 && c - c0 < vcd_n;
        if (dump) tf->dump((uint64_t)(c - c0) * vcd_ps + vcd_ps / 2);
#endif
        top.clk = 1; top.eval();
#if VM_TRACE
        if (dump) tf->dump((uint64_t)(c - c0 + 1) * vcd_ps);
#endif
    }
    top.final();
#if VM_TRACE
    if (tf) { tf->close(); delete tf; }
#endif
    if (top.illegal) { fprintf(stderr, "FAIL unsupported instruction (see the trace end)\n"); return 1; }
    if (ticks && c0 < 0) { fprintf(stderr, "FAIL the +mark EIP not reached twice in %ld cycles\n", warm); return 1; }
    if (ticks && top.halted) { fprintf(stderr, "FAIL HLT before %ld cycles\n", ticks); return 1; }
    if (ticks) {                       // the window only: warm-up (the first run of the program) left out
        printf("%u instructions in %ld cycles, IPC %.3f\n", top.insns - i0, ticks, (double)(top.insns - i0) / ticks);
        return 0;
    }
    if (!top.halted) { fprintf(stderr, "FAIL no HLT after %ld cycles\n", c); return 1; }
    printf("%u instructions in %u cycles, IPC %.3f\n", top.insns, top.cycles,
           top.cycles ? (double)top.insns / top.cycles : 0.0);
    return 0;
}
