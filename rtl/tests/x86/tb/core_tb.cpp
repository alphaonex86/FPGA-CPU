// M2 driver: clocks core_top until HLT (or an unsupported instruction, or
// the cycle limit). Usage: core_tb +image=<hex> +trace=<file> [+max=<cycles>]
// +ticks=<cycles>: a benchmark (rtl/tools/x86_bench.sh) runs exactly that many cycles, no HLT.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "Vcore_top.h"
#include "verilated.h"

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    long max = 1000000, ticks = 0;
    for (int i = 1; i < argc; i++) {
        if (!strncmp(argv[i], "+max=", 5)) max = atol(argv[i] + 5);
        if (!strncmp(argv[i], "+ticks=", 7)) max = ticks = atol(argv[i] + 7);
    }
    Vcore_top top;
    top.rst = 1;
    for (int i = 0; i < 4; i++) { top.clk = 0; top.eval(); top.clk = 1; top.eval(); }
    top.rst = 0;
    long c = 0;
    for (; c < max && !top.halted && !Verilated::gotFinish(); c++) {
        top.clk = 0; top.eval();
        top.clk = 1; top.eval();
    }
    top.final();
    if (top.illegal) { fprintf(stderr, "FAIL unsupported instruction (see the trace end)\n"); return 1; }
    if (ticks && top.halted) { fprintf(stderr, "FAIL HLT before %ld cycles\n", ticks); return 1; }
    if (!ticks && !top.halted) { fprintf(stderr, "FAIL no HLT after %ld cycles\n", c); return 1; }
    printf("%u instructions in %u cycles, IPC %.3f\n", top.insns, top.cycles,
           top.cycles ? (double)top.insns / top.cycles : 0.0);
    return 0;
}
