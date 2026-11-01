// Integer mix in the spirit of Dhrystone: records, string copy/compare,
// insertion sort, CRC-32, recursion, division. Result in EAX at HLT.
typedef unsigned u32;
struct rec { struct rec *next; int kind; int val; char str[31]; };
static struct rec pool[8];
static char buf[64];

static int str_cmp(const char *a, const char *b)
{
    while (*a && *a == *b) { a++; b++; }
    return *a - *b;
}

static void str_cpy(char *d, const char *s)
{
    while ((*d++ = *s++));
}

static u32 crc32(const unsigned char *p, int n)
{
    u32 c = ~0u;
    for (int i = 0; i < n; i++) {
        c ^= p[i];
        for (int k = 0; k < 8; k++) c = c >> 1 ^ (0xEDB88320u & -(c & 1));
    }
    return ~c;
}

static int fib(int n)
{
    return n < 2 ? n : fib(n - 1) + fib(n - 2);
}

static void sort(int *a, int n)
{
    for (int i = 1; i < n; i++) {
        int v = a[i], j = i - 1;
        while (j >= 0 && a[j] > v) { a[j + 1] = a[j]; j--; }
        a[j + 1] = v;
    }
}

u32 main(void)
{
    int arr[16];
    for (int i = 0; i < 16; i++) arr[i] = (i * 7919) % 31 - 15;
    sort(arr, 16);
    for (int i = 0; i < 8; i++) {
        pool[i].next = &pool[(i + 1) & 7];
        pool[i].kind = i % 3;
        pool[i].val = arr[i] * arr[15 - i] / 3;
        str_cpy(pool[i].str, "DHRYSTONE PROGRAM, SOME STRING");
    }
    struct rec *r = pool;
    u32 s = 0;
    for (int i = 0; i < 20; i++) {
        s += r->val % 7 + str_cmp(r->str, "DHRYSTONE PROGRAM, 2'ND STRING");
        r = r->next;
    }
    for (int i = 0; i < 64; i++) buf[i] = (char)(s + i);
    return s + crc32((unsigned char *)buf, 64) + fib(15);
}
