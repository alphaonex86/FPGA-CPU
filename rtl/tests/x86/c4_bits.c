// Bit manipulation as hashing / allocator code uses it: count trailing /
// leading zeros, byte swap, bit test and set, rotates. Result in EAX at HLT.
typedef unsigned u32;

static u32 bitmap[8];

static int alloc_bit(void)
{
    for (int i = 0; i < 8; i++)
        if (~bitmap[i]) {
            int b = __builtin_ctz(~bitmap[i]);
            bitmap[i] |= 1u << b;
            return i * 32 + b;
        }
    return -1;
}

static u32 hash(u32 x)
{
    x ^= x >> 16;
    x *= 0x7feb352du;
    x = x << 13 | x >> 19;
    x ^= __builtin_bswap32(x);
    return x;
}

u32 main(void)
{
    u32 r = 0;
    for (int i = 0; i < 70; i++) r += (u32)alloc_bit() * 3;
    for (u32 i = 1; i < 300; i += 7) {
        u32 h = hash(i * 0x9e3779b9u);
        r += (u32)__builtin_clz(h | 1) + (u32)__builtin_ctz(h | 0x80000000u);
        if (bitmap[h & 7] & (1u << (h >> 27))) r ^= h;
        bitmap[h & 7] ^= 1u << (h >> 27);
    }
    return r;
}
