// cflags: -Os
// gcc-emitted string ops: variable memcpy (REP MOVSB), struct copies and
// array clears (REP MOVSL / STOSL). Result in EAX at HLT.
typedef unsigned u32;
struct blob { u32 w[24]; };
static struct blob a, b;
static unsigned char src[200], dst[200];

static void copy(unsigned char *d, const unsigned char *s, unsigned n)
{
    __builtin_memcpy(d, s, n);
}

static u32 sum(const unsigned char *p, unsigned n)
{
    u32 s = 0;
    for (unsigned i = 0; i < n; i++) s = s * 33 + p[i];
    return s;
}

u32 main(void)
{
    u32 r = 0;
    for (unsigned i = 0; i < sizeof src; i++) src[i] = (unsigned char)(i * 37 + 11);
    for (unsigned i = 0; i < 24; i++) a.w[i] = i * 0x01010101u;
    for (unsigned n = 0; n < 40; n += 7) {
        copy(dst + n, src + 2 * n, n * 3 + 1);
        r += sum(dst, sizeof dst);
    }
    b = a;
    b.w[5] ^= r;
    a = b;
    __builtin_memset(dst, 0, 160);
    return r + sum(dst, sizeof dst) + a.w[5] + b.w[23];
}
