// Compression profile (x86_bench.sh compress): LZ77 as deflate / gzip find matches (a hash of three
// bytes, a chain of earlier positions, byte compares) over 16 KB of generated text, then the
// decompression of the result, checked against the input. Bytes, unaligned access, branches.
typedef unsigned u32;
typedef unsigned char u8;
#define LEN 16384
#define HBITS 12
#define CHAIN 8

static u8 text[LEN], out[LEN * 2], back[LEN];
static unsigned short head[1 << HBITS], prev[LEN];
static const char *const words[16] = { "the ", "cache ", "line ", "of ", "a ", "bus ", "cycle ", "and ",
                                       "write-back ", "memory ", "to ", "is ", "snoop ", "in ", "data ", "\n" };

u32 main(void)
{
    u32 seed = 7, n = 0, o = 0, b = 0, sum = 0;
    while (n < LEN - 16) {
        seed = seed * 1103515245u + 12345u;
        for (const char *w = words[(seed >> 16) & 15]; *w; w++) text[n++] = (u8)*w;
    }
    while (n < LEN) text[n++] = ' ';
    for (int i = 0; i < 1 << HBITS; i++) head[i] = 0xffff;
    for (u32 i = 0; i < LEN;) {
        u32 best = 0, dist = 0;
        if (i + 3 <= LEN) {
            u32 h = ((text[i] << 8 ^ text[i + 1] << 4 ^ text[i + 2]) * 2654435761u) >> (32 - HBITS);
            u32 p = head[h];
            for (int c = 0; c < CHAIN && p != 0xffff && i - p < 4096; c++, p = prev[p]) {
                u32 l = 0;
                while (l < 255 && i + l < LEN && text[p + l] == text[i + l]) l++;
                if (l > best) { best = l; dist = i - p; }
            }
            prev[i] = (unsigned short)head[h];
            head[h] = (unsigned short)i;
        }
        if (best >= 3) {                      // match: 0, length, distance (2 bytes)
            out[o++] = 0;
            out[o++] = (u8)best;
            out[o++] = (u8)dist;
            out[o++] = (u8)(dist >> 8);
            i += best;                        // the skipped positions are not hashed (fast mode)
        } else {                              // literal: 1, byte
            out[o++] = 1;
            out[o++] = text[i++];
        }
    }
    for (u32 i = 0; i < o;) {
        if (out[i] == 1) {
            back[b++] = out[i + 1];
            i += 2;
        } else {
            u32 l = out[i + 1], d = out[i + 2] | out[i + 3] << 8;
            for (u32 k = 0; k < l; k++, b++) back[b] = back[b - d];
            i += 4;
        }
    }
    for (u32 i = 0; i < LEN; i++) sum += back[i] != text[i];
    return sum * 1000000 + o;                 // 0 mismatches: the compressed size
}
