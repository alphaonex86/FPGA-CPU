// Memory benchmark (rtl/tools/x86_bench.sh: b_l1, b_l2, b_ram set SIZE from the cache sizes):
// SIZE bytes at 1 MB (above the stack, past the no-KEN 64 KB at 0x80000 of core_top). A list of one
// node per 32-byte line visited in a fixed large stride (a single cycle no next-line prefetch
// follows: load-to-use latency), then a sequential sum of every dword (bandwidth). The list is built
// on the first call only.
typedef unsigned u32;
#define LINES (SIZE / 32)
static int built;

static u32 gcd(u32 a, u32 b)
{
    while (b) {
        u32 t = a % b;
        a = b;
        b = t;
    }
    return a;
}

u32 main(void)
{
    volatile u32 *m = (volatile u32 *)0x100000;
    u32 p = 0, s = 0;
    if (!built) {
        u32 stride = (LINES * 5 / 8) | 1;
        while (gcd(stride, LINES) != 1) stride += 2;   // coprime: one cycle through every line
        for (u32 i = 0; i < LINES; i++) m[i * 8] = (i + stride) % LINES;
        built = 1;
    }
    for (u32 n = 0; n < LINES; n++) p = m[p * 8];
    for (u32 i = 0; i < SIZE / 4; i += 4) s += m[i] + m[i + 1] + m[i + 2] + m[i + 3];
    return p + s;
}
