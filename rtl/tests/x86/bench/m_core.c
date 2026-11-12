// Core micro-benchmarks (x86_bench.sh ilp, chain, branch, call), one per -D:
//   ILP     8 independent add / xor / rotate chains: issue width, ports, renaming;
//   CHAIN   one dependent chain of the same operations: ALU latency and bypass;
//   BRANCH  stores chosen by random bits (not if-convertible): branch misprediction cost;
//   CALL    recursive calls and returns (fib): call / return prediction, stack traffic.
typedef unsigned u32;
static volatile u32 seed = 0x2545f491;
static u32 sink[64] __attribute__((unused));

__attribute__((unused)) static u32 rol(u32 x, int n) { return x << n | x >> (32 - n); }

#if defined(CALL)
__attribute__((noinline)) static u32 fib(u32 n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
#endif

u32 main(void)
{
    u32 s = seed;
#if defined(ILP)
    u32 a = s, b = s + 1, c = s + 2, d = s + 3, e = s + 4, f = s + 5, g = s + 6, h = s + 7;
    for (u32 i = 0; i < 20000; i++) {
        a = rol(a + i, 3); b = rol(b ^ i, 5); c = rol(c + 7, 7); d = rol(d ^ 9, 9);
        e = rol(e + i, 11); f = rol(f ^ 13, 13); g = rol(g + 15, 15); h = rol(h ^ i, 17);
    }
    return a ^ b ^ c ^ d ^ e ^ f ^ g ^ h;
#elif defined(CHAIN)
    for (u32 i = 0; i < 20000; i++) {
        s = rol(s + i, 3); s = rol(s ^ i, 5); s = rol(s + 7, 7); s = rol(s ^ 9, 9);
        s = rol(s + i, 11); s = rol(s ^ 13, 13); s = rol(s + 15, 15); s = rol(s ^ i, 17);
    }
    return s;
#elif defined(BRANCH)
    for (u32 i = 0; i < 20000; i++) {
        s = s * 1664525u + 1013904223u;
        if (s & 0x10000) sink[i & 31]++;
        else sink[32 + (i & 31)] += 3;
        if (s & 0x20000) sink[(i >> 5) & 31] ^= i;
    }
    return sink[0] + sink[33];
#elif defined(CALL)
    return fib(18 + (s & 1));
#else
#error "ILP, CHAIN, BRANCH or CALL"
#endif
}
