/* C3 lock-step reference (plan/cpu_core.md X1): replays a flat 32-bit x86
 * image in Unicorn one instruction at a time and compares every line of a
 * retire trace written by the RTL simulation.
 *
 * Usage: x86_trace_check <image.bin> <load_addr_hex> <trace.txt>
 *        x86_trace_check --gen <image.bin> <load_addr_hex> <count>  (reference trace)
 * Trace line, after each retired instruction (hex):
 *        eip eax ecx edx ebx esp ebp esi edi eflags
 * Start state: all GPRs 0, ESP = top of the 1 MB RAM, EFLAGS 0x2, EIP = load
 * address; the run ends at the first HLT. Exit 0 = match, 1 = mismatch or error.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unicorn/unicorn.h>

#define RAM_SIZE 0x100000u
#define FLAGS_MASK 0x8D5u /* OF SF ZF AF PF CF */

static const int regs[9] = {UC_X86_REG_EIP, UC_X86_REG_EAX, UC_X86_REG_ECX,
                            UC_X86_REG_EDX, UC_X86_REG_EBX, UC_X86_REG_ESP,
                            UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EDI};
static const char *names[10] = {"eip", "eax", "ecx", "edx", "ebx",
                                "esp", "ebp", "esi", "edi", "eflags"};

static void die_uc(const char *what, uc_err e) {
    fprintf(stderr, "%s: %s\n", what, uc_strerror(e));
    exit(1);
}

static uc_engine *load(const char *path, uint32_t base) {
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); exit(1); }
    static unsigned char img[RAM_SIZE];
    size_t n = fread(img, 1, sizeof img, f);
    if (ferror(f) || !feof(f) || base + n > RAM_SIZE) {
        fprintf(stderr, "%s: read error or image beyond %#x\n", path, RAM_SIZE);
        exit(1);
    }
    fclose(f);
    uc_engine *uc;
    uc_err e;
    if ((e = uc_open(UC_ARCH_X86, UC_MODE_32, &uc))) die_uc("uc_open", e);
    if ((e = uc_mem_map(uc, 0, RAM_SIZE, UC_PROT_ALL))) die_uc("uc_mem_map", e);
    if ((e = uc_mem_write(uc, base, img, n))) die_uc("uc_mem_write", e);
    uint32_t esp = RAM_SIZE, eflags = 0x2;
    if ((e = uc_reg_write(uc, UC_X86_REG_ESP, &esp)) ||
        (e = uc_reg_write(uc, UC_X86_REG_EFLAGS, &eflags)))
        die_uc("uc_reg_write", e);
    return uc;
}

/* executes one instruction; returns 0 after HLT (state left at the HLT) */
static int step(uc_engine *uc, uint32_t s[10]) {
    uint32_t eip;
    uint8_t op;
    uc_err e;
    if ((e = uc_reg_read(uc, UC_X86_REG_EIP, &eip))) die_uc("uc_reg_read", e);
    if ((e = uc_mem_read(uc, eip, &op, 1))) die_uc("uc_mem_read", e);
    if (op == 0xF4) return 0;
    if ((e = uc_emu_start(uc, eip, RAM_SIZE, 0, 1))) die_uc("uc_emu_start", e);
    for (int i = 0; i < 9; i++)
        if ((e = uc_reg_read(uc, regs[i], &s[i]))) die_uc("uc_reg_read", e);
    if ((e = uc_reg_read(uc, UC_X86_REG_EFLAGS, &s[9]))) die_uc("uc_reg_read", e);
    return 1;
}

int main(int argc, char **argv) {
    int gen = argc == 5 && !strcmp(argv[1], "--gen");
    if (argc != 4 && !gen) {
        fprintf(stderr, "usage: %s <image.bin> <load_addr_hex> <trace.txt>\n"
                        "       %s --gen <image.bin> <load_addr_hex> <count>\n",
                argv[0], argv[0]);
        return 1;
    }
    char **a = argv + gen;
    uint32_t base = strtoul(a[2], NULL, 16);
    uc_engine *uc = load(a[1], base);
    uint32_t e = base;
    uc_err err;
    if ((err = uc_reg_write(uc, UC_X86_REG_EIP, &e))) die_uc("uc_reg_write", err);
    uint32_t want[10];

    if (gen) {
        long count = strtol(a[3], NULL, 0);
        for (long n = 0; n < count && step(uc, want); n++)
            for (int i = 0; i < 10; i++) printf(i < 9 ? "%08x " : "%08x\n", want[i]);
        uc_close(uc);
        return 0;
    }

    FILE *t = fopen(a[3], "r");
    if (!t) { perror(a[3]); return 1; }
    long line = 0;
    uint32_t got[10];
    for (;;) {
        int k = fscanf(t, "%x %x %x %x %x %x %x %x %x %x", &got[0], &got[1], &got[2],
                       &got[3], &got[4], &got[5], &got[6], &got[7], &got[8], &got[9]);
        if (k == EOF) break;
        line++;
        if (k != 10) { fprintf(stderr, "%s:%ld: malformed line\n", a[3], line); return 1; }
        if (!step(uc, want)) {
            fprintf(stderr, "line %ld: trace continues after the reference HLT\n", line);
            return 1;
        }
        for (int i = 0; i < 10; i++) {
            uint32_t m = i == 9 ? FLAGS_MASK : 0xFFFFFFFFu;
            if ((got[i] ^ want[i]) & m) {
                fprintf(stderr, "line %ld: %s rtl %08x ref %08x (eip after %08x)\n",
                        line, names[i], got[i], want[i], want[0]);
                return 1;
            }
        }
    }
    if (ferror(t)) { perror(a[3]); return 1; }
    fclose(t);
    if (step(uc, want)) {
        fprintf(stderr, "trace ends after %ld instructions before the reference HLT\n", line);
        return 1;
    }
    uc_close(uc);
    printf("PASS %ld instructions\n", line);
    return 0;
}
