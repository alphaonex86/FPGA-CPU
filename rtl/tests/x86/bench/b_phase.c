// Phases (rtl/tools/x86_bench.sh phase): a working set that changes over time, for caches that adapt
// (resizing, power gating, replacement, prefetch): per call 32 passes over a hot 4 KB, then one pass
// over a cold 512 KB, then 32 hot passes over another 4 KB (past the cold one). Sums, at 1 MB.
typedef unsigned u32;

static u32 sum(volatile u32 *m, u32 bytes)
{
    u32 s = 0;
    for (u32 i = 0; i < bytes / 4; i += 4) s += m[i] + m[i + 1] + m[i + 2] + m[i + 3];
    return s;
}

u32 main(void)
{
    volatile u32 *m = (volatile u32 *)0x100000;
    u32 s = 0;
    for (int r = 0; r < 32; r++) s += sum(m, 4096);
    s += sum(m + 1024, 512 * 1024);
    for (int r = 0; r < 32; r++) s += sum(m + 160 * 1024, 4096);
    return s;
}
