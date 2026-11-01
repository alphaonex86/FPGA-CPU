// M1 check (plan/x86_core.md): x86_predecode == x86_len_decode at every start
// (predecode_check.sv). Usage: predecode_tb <blocks> <seed>
// Bytes are random, with prefix bytes and 0F escapes made frequent so long
// prefix runs and the 0F / 0F38 / 0F3A maps are covered.
#include <cstdio>
#include <cstdlib>
#include <random>
#include "Vpredecode_check.h"

int main(int argc, char **argv) {
    if (argc != 3) { fprintf(stderr, "usage: %s <blocks> <seed>\n", argv[0]); return 1; }
    long blocks = atol(argv[1]);
    std::mt19937_64 rng(strtoull(argv[2], nullptr, 0));
    static const unsigned char special[] = {0x26, 0x2E, 0x36, 0x3E, 0x64, 0x65, 0x66, 0x67,
                                            0xF0, 0xF2, 0xF3, 0x0F, 0x38, 0x3A};
    const int nbytes = 16 + 14, nwords = (nbytes * 8 + 31) / 32;
    Vpredecode_check dut;
    long fails = 0;
    for (long n = 0; n < blocks; n++) {
        int bias = rng() % 4;   // 0: uniform .. 3: mostly prefixes / escapes
        for (int w = 0; w < nwords; w++) dut.bytes[w] = 0;
        for (int i = 0; i < nbytes; i++) {
            unsigned v = (int)(rng() % 4) < bias ? special[rng() % sizeof special] : rng() & 0xFF;
            dut.bytes[i / 4] |= v << 8 * (i % 4);
        }
        dut.d32 = rng() & 1;
        dut.clk = 0; dut.eval();
        dut.clk = 1; dut.eval();   // both sides now hold this block
        if (dut.bad && ++fails <= 10)
            printf("block %ld (d32=%d): bad starts %04x\n", n, dut.d32, dut.bad);
    }
    printf("%s: %ld blocks x 16 starts, %ld blocks differ\n", fails ? "FAIL" : "PASS", blocks, fails);
    return fails != 0;
}
