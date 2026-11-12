// Memory benchmarks (rtl/tools/x86_bench.sh lat_*, bw_*, copy_*): SIZE bytes at 1 MB (above the stack,
// past the no-KEN 64 KB at 0x80000 of core_top). The first call (the warm-up, outside the measured
// window) builds the data; each call runs one pass of
//   LAT  a list chase, one node per 32-byte line in a large coprime stride: load-to-use latency (no
//        next-line prefetch helps);
//   BW   a sequential sum of every dword: read bandwidth;
//   COPY the first half copied onto the second: read + write (write-allocate, write-back traffic).
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
    u32 s = 0;
    if (!built) {
        u32 stride = (LINES * 5 / 8) | 1;
        while (gcd(stride, LINES) != 1) stride += 2;   // coprime: one cycle through every line
        for (u32 i = 0; i < LINES; i++) m[i * 8] = (i + stride) % LINES;
        built = 1;
    }
#if defined(LAT)
    for (u32 n = 0; n < LINES; n++) s = m[s * 8];
#elif defined(BW)
    for (u32 i = 0; i < SIZE / 4; i += 4) s += m[i] + m[i + 1] + m[i + 2] + m[i + 3];
#elif defined(COPY)
    for (u32 i = 0; i < SIZE / 8; i += 4) {
        m[SIZE / 8 + i] = m[i];
        m[SIZE / 8 + i + 1] = m[i + 1];
        m[SIZE / 8 + i + 2] = m[i + 2];
        m[SIZE / 8 + i + 3] = m[i + 3];
    }
#else
#error "LAT, BW or COPY"
#endif
    return s;
}
