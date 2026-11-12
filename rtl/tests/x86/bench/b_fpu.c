// cflags: -O2 -fno-math-errno
// x87 double precision: a dot product, a bounded recurrence, a square root, the conversion back
// to an integer. n/a in plan/bench_history.md until the core has x87 (M6).
typedef unsigned u32;
static double a[256], b[256];

u32 main(void)
{
    double s = 0, x = 0.5;
    for (int i = 0; i < 256; i++) {
        a[i] = i * 0.25 + 1.0;
        b[i] = 1.0 / (i + 1);
    }
    for (int i = 0; i < 256; i++) s += a[i] * b[i];
    for (int i = 0; i < 256; i++) x = x * 0.75 + a[i] * 0.001;
    s += __builtin_sqrt(s);
    return (u32)(s * 1000.0) ^ (u32)(x * 1e6);
}
