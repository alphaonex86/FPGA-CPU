// M1 check (plan/x86_core.md): x86_len_decode against objdump's instruction
// starts and lengths. Usage: len_decode_tb <stream.bin> <ref.txt> <d32 0|1>
// ref.txt lines: "<offset> <length> <bad 0|1>" (decimal), from x86_len_test.sh.
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "Vx86_len_decode.h"

int main(int argc, char **argv) {
    if (argc != 4) { fprintf(stderr, "usage: %s <stream.bin> <ref.txt> <d32>\n", argv[0]); return 1; }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 1; }
    std::vector<unsigned char> mem;
    for (int c; (c = fgetc(f)) != EOF;) mem.push_back(c);
    if (ferror(f)) { perror(argv[1]); return 1; }
    fclose(f);
    FILE *r = fopen(argv[2], "r");
    if (!r) { perror(argv[2]); return 1; }

    Vx86_len_decode dut;
    dut.d32 = atoi(argv[3]);
    long off, len, bad, checked = 0, skipped = 0, fails = 0;
    while (fscanf(r, "%ld %ld %ld", &off, &len, &bad) == 3) {
        for (int i = 0; i < 15; i++) {
            unsigned v = off + i < (long)mem.size() ? mem[off + i] : 0;
            dut.win[i / 4] = (dut.win[i / 4] & ~(0xFFu << 8 * (i % 4))) | v << 8 * (i % 4);
        }
        dut.eval();
        if (bad || dut.unsup || dut.too_long || off + 15 > (long)mem.size()) { skipped++; continue; }
        checked++;
        if (dut.len != len) {
            if (++fails <= 20) {
                printf("offset %ld: rtl %d objdump %ld:", off, dut.len, len);
                for (int i = 0; i < len && i < 15; i++) printf(" %02x", mem[off + i]);
                printf("\n");
            }
        }
    }
    if (ferror(r)) { perror(argv[2]); return 1; }
    printf("%s d32=%s: %ld checked, %ld skipped, %ld mismatches\n",
           fails ? "FAIL" : "PASS", argv[3], checked, skipped, fails);
    return fails != 0;
}
