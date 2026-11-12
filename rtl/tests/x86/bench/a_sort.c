// Sorting profile (x86_bench.sh sort): 16K random integers (64 KB) sorted by a recursive quicksort
// (median of three, insertion sort below 16), then checked: data-dependent branches, swaps, recursion.
typedef unsigned u32;
#define N 16384

static u32 a[N];

static void isort(u32 *v, int n)
{
    for (int i = 1; i < n; i++) {
        u32 x = v[i];
        int j = i;
        for (; j > 0 && v[j - 1] > x; j--) v[j] = v[j - 1];
        v[j] = x;
    }
}

static void qsort_u32(u32 *v, int n)
{
    while (n > 16) {
        u32 x = v[0], y = v[n / 2], z = v[n - 1];
        u32 p = x < y ? (y < z ? y : x < z ? z : x) : (x < z ? x : y < z ? z : y);
        int i = 0, j = n - 1;
        for (;;) {
            while (v[i] < p) i++;
            while (v[j] > p) j--;
            if (i >= j) break;
            u32 t = v[i]; v[i] = v[j]; v[j] = t;
            i++;
            j--;
        }
        if (j + 1 < n - j - 1) {              // recurse on the smaller part
            qsort_u32(v, j + 1);
            v += j + 1;
            n -= j + 1;
        } else {
            qsort_u32(v + j + 1, n - j - 1);
            n = j + 1;
        }
    }
    isort(v, n);
}

u32 main(void)
{
    u32 seed = 99, bad = 0;
    for (int i = 0; i < N; i++) a[i] = seed = seed * 1664525u + 1013904223u;
    qsort_u32(a, N);
    for (int i = 1; i < N; i++) bad += a[i - 1] > a[i];
    return bad * 1000000 + a[N / 2] % 1000000;
}
