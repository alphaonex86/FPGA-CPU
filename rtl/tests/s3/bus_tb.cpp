// Driver of bus_tb.sv: clocks it until done. Usage: bus_tb [+seed=<n>] [+ops=<n>] ...
#include <cstdio>
#include "Vbus_tb.h"
#include "verilated.h"

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    Vbus_tb top;
    long c = 0;
    for (; c < 200000000 && !top.done && !Verilated::gotFinish(); c++) {
        top.clk = 0; top.eval();
        top.clk = 1; top.eval();
    }
    top.final();
    if (!top.done) { fprintf(stderr, "FAIL not done after %ld clocks\n", c); return 1; }
    return top.failed ? 1 : 0;
}
