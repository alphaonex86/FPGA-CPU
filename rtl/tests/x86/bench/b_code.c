// Code footprint (rtl/tools/x86_bench.sh code_*, codedata_*): 2^NFB functions of ~85 bytes, each
// called once per pass, in falling address order (the instruction-fetch working set: no fall-through,
// no next-line prefetch, no tiny loop); with DL each one also reads DL data lines of its own (a data
// working set beside the code: split against unified first-level caches).
typedef unsigned u32;
#ifndef DL
#define DL 0
#endif
#define NF (1 << NFB)
static volatile u32 dat[NF * (DL ? DL : 1) * 8];

#define F(n, i) __attribute__((noinline)) static u32 f##n(u32 x) \
{                                                            \
    x = x * (2 * n + 3) + (n ^ 0x5a5a);                      \
    x ^= x >> 7;                                             \
    x = x * 0x9e37u + n;                                     \
    x ^= x << 3;                                             \
    x += (x >> 11) ^ (n * 77u);                              \
    x = x * 0x2545u + (x >> 13);                             \
    x ^= (x << 5) + n;                                       \
    for (int d = 0; d < DL; d++) x += dat[((i) * DL + d) * 8]; \
    return x;                                                \
}
// n: a binary numeral of NFB digits (an octal literal of 0 / 1 digits: unique, the same in F and C);
// i: the same number in binary, the index of the function's data lines
#define F1(n, i) F(n##0, (i) * 2) F(n##1, (i) * 2 + 1)
#define F2(n, i) F1(n##0, (i) * 2) F1(n##1, (i) * 2 + 1)
#define F3(n, i) F2(n##0, (i) * 2) F2(n##1, (i) * 2 + 1)
#define F4(n, i) F3(n##0, (i) * 2) F3(n##1, (i) * 2 + 1)
#define F5(n, i) F4(n##0, (i) * 2) F4(n##1, (i) * 2 + 1)
#define F6(n, i) F5(n##0, (i) * 2) F5(n##1, (i) * 2 + 1)
#define F7(n, i) F6(n##0, (i) * 2) F6(n##1, (i) * 2 + 1)
#define F8(n, i) F7(n##0, (i) * 2) F7(n##1, (i) * 2 + 1)
#define F9(n, i) F8(n##0, (i) * 2) F8(n##1, (i) * 2 + 1)
#define F10(n, i) F9(n##0, (i) * 2) F9(n##1, (i) * 2 + 1)
#define C(n) x = f##n(x);
#define C1(n) C(n##1) C(n##0)
#define C2(n) C1(n##1) C1(n##0)
#define C3(n) C2(n##1) C2(n##0)
#define C4(n) C3(n##1) C3(n##0)
#define C5(n) C4(n##1) C4(n##0)
#define C6(n) C5(n##1) C5(n##0)
#define C7(n) C6(n##1) C6(n##0)
#define C8(n) C7(n##1) C7(n##0)
#define C9(n) C8(n##1) C8(n##0)
#define C10(n) C9(n##1) C9(n##0)
#define CAT(a, b) a##b
#define XF(k) CAT(F, k)(0, 0)
#define XC(k) CAT(C, k)(0)

XF(NFB)

u32 main(void)
{
    u32 x = 1;
    XC(NFB)
    return x;
}
