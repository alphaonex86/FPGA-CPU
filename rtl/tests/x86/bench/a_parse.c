// Compiler / scripting front-end profile (x86_bench.sh parse): 8 KB of generated source
// ("x = (12 + y * 7) ^ z;" lines) scanned into tokens and evaluated by a recursive-descent parser:
// byte classification, short unpredictable branches, recursion.
typedef unsigned u32;
#define LEN 8192

static char src[LEN];
static const char *pos;
static u32 vars[26];

static u32 expr(void);

static void skip(void) { while (*pos == ' ') pos++; }

static u32 primary(void)
{
    u32 v = 0;
    skip();
    if (*pos == '(') {
        pos++;
        v = expr();
        skip();
        pos++;                               // ')'
    } else if (*pos >= 'a' && *pos <= 'z') v = vars[*pos++ - 'a'];
    else while (*pos >= '0' && *pos <= '9') v = v * 10 + (u32)(*pos++ - '0');
    return v;
}

static u32 term(void)
{
    u32 v = primary();
    for (skip(); *pos == '*'; skip()) { pos++; v *= primary(); }
    return v;
}

static u32 expr(void)
{
    u32 v = term();
    for (skip(); *pos == '+' || *pos == '-' || *pos == '^'; skip()) {
        char op = *pos++;
        u32 t = term();
        v = op == '+' ? v + t : op == '-' ? v - t : v ^ t;
    }
    return v;
}

static u32 n, seed = 3;
static u32 rnd(u32 m) { seed = seed * 1103515245u + 12345u; return (seed >> 16) % m; }
static void put(char c) { src[n++] = c; }

static void gen(int depth)                   // a random expression
{
    for (int k = rnd(3) + 1; k; k--) {
        u32 r = rnd(depth ? 4 : 2);
        if (r == 0) put((char)('a' + rnd(26)));
        else if (r == 1) for (u32 v = rnd(1000) + 1; v; v /= 10) put((char)('0' + v % 10));
        else { put('('); gen(depth - 1); put(')'); }
        if (k > 1) { put(' '); put("+-^*"[rnd(4)]); put(' '); }
    }
}

u32 main(void)
{
    u32 sum = 0;
    n = 0;
    while (n < LEN - 200) {
        put((char)('a' + rnd(26)));
        put(' '); put('='); put(' ');
        gen(3);
        put(';');
        put(' ');
    }
    src[n] = 0;
    for (pos = src; *pos;) {
        u32 *dst = &vars[*pos - 'a'];
        pos += 4;                             // "x = "
        *dst = expr();
        sum += *dst;
        pos += 2;                             // "; "
    }
    return sum;
}
