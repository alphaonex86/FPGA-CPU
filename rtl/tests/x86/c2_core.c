// CoreMark-like kernels: linked list, matrix multiply, state machine (switch
// jump table), 64-bit arithmetic, local array zeroing. Result in EAX at HLT.
typedef unsigned u32;
typedef unsigned long long u64;

struct node { struct node *next; short idx; short val; };
static struct node nodes[32];

static u32 list_work(void)
{
    for (int i = 0; i < 32; i++) {
        nodes[i].next = &nodes[(i * 13 + 5) & 31];
        nodes[i].idx = (short)i;
        nodes[i].val = (short)(i * 0x1234 ^ 0x5a5a);
    }
    u32 s = 0;
    struct node *n = nodes;
    for (int i = 0; i < 100; i++) {
        s += (u32)(n->val * n->idx) ^ (s << 3);
        n = n->next;
    }
    return s;
}

static u32 matrix_work(void)
{
    int a[8][8], b[8][8], c[8][8] = {{0}};
    for (int i = 0; i < 8; i++)
        for (int j = 0; j < 8; j++) {
            a[i][j] = i * 3 - j;
            b[i][j] = (i ^ j) - 4;
        }
    for (int i = 0; i < 8; i++)
        for (int j = 0; j < 8; j++)
            for (int k = 0; k < 8; k++) c[i][j] += a[i][k] * b[k][j];
    u32 s = 0;
    for (int i = 0; i < 8; i++)
        for (int j = 0; j < 8; j++) s = s * 31 + (u32)c[i][j];
    return s;
}

static int classify(const char *p)
{
    int state = 0, count = 0;
    for (; *p; p++) {
        char ch = *p;
        switch (state) {
        case 0: state = ch >= '0' && ch <= '9' ? 1 : ch == '-' || ch == '+' ? 2 : 5; break;
        case 1: state = ch >= '0' && ch <= '9' ? 1 : ch == '.' ? 3 : ch == ',' ? 0 : 5; break;
        case 2: state = ch >= '0' && ch <= '9' ? 1 : 5; break;
        case 3: state = ch >= '0' && ch <= '9' ? 4 : 5; break;
        case 4: state = ch >= '0' && ch <= '9' ? 4 : ch == 'e' ? 2 : ch == ',' ? 0 : 5; break;
        case 5: state = ch == ',' ? 0 : 5; count++; break;
        default: break;
        }
        count += state;
    }
    return count;
}

static u64 wide_work(u64 x)
{
    u64 s = 0;
    for (int i = 0; i < 40; i++) {
        x = x * 6364136223846793005ull + 1442695040888963407ull;
        s += x >> (i & 31);
        s ^= x << (i & 15);
    }
    return s;
}

u32 main(void)
{
    u64 w = wide_work(0x123456789abcdefull);
    return list_work() + matrix_work()
           + (u32)classify("12,-3.5,7.25e+3,abc,+9,1.e5,42") + (u32)w + (u32)(w >> 32);
}
