// Java-like profile (x86_bench.sh objects): objects of three classes from a bump-allocated heap,
// virtual calls through their class tables, field updates, and a garbage collector's mark phase
// over the reference graph. One call: allocate, four passes of virtual calls, mark, free all.
typedef unsigned u32;
#define OBJS 4096
#define HEAP (OBJS * 48)

typedef struct shape shape;
typedef struct { u32 (*area)(shape *); void (*grow)(shape *, u32); } cls;
struct shape { const cls *k; shape *next, *ref; u32 mark, w, h; };
typedef struct { shape s; u32 depth, color; } box3;   // a subclass with more fields

static u32 rect_area(shape *s) { return s->w * s->h; }
static u32 tri_area(shape *s) { return s->w * s->h / 2; }
static u32 box_area(shape *s) { box3 *b = (box3 *)s; return 2 * (s->w * s->h + s->w * b->depth + s->h * b->depth); }
static void rect_grow(shape *s, u32 d) { s->w += d; s->h += d & 3; }
static void tri_grow(shape *s, u32 d) { s->h += d; }
static void box_grow(shape *s, u32 d) { ((box3 *)s)->depth += d; s->w ^= d; }
static const cls classes[3] = { {rect_area, rect_grow}, {tri_area, tri_grow}, {box_area, box_grow} };

static unsigned char heap[HEAP] __attribute__((aligned(16)));
static u32 seed = 12345;

static u32 rnd(void) { return seed = seed * 1103515245u + 12345u; }

u32 main(void)
{
    u32 top = 0, sum = 0;
    shape *all[OBJS], *head = 0;
    for (int i = 0; i < OBJS; i++) {
        u32 c = (rnd() >> 16) % 3, size = c == 2 ? sizeof(box3) : sizeof(shape);
        shape *s = (shape *)(heap + top);
        top += (size + 15) & ~15u;
        s->k = &classes[c];
        s->w = rnd() >> 24;
        s->h = rnd() >> 24;
        s->mark = 0;
        s->ref = i ? all[(rnd() >> 8) % i] : 0;
        if (c == 2) ((box3 *)s)->depth = i & 31;
        s->next = head;
        head = s;
        all[i] = s;
    }
    for (int pass = 0; pass < 4; pass++)
        for (shape *s = head; s; s = s->next) {
            sum += s->k->area(s);
            s->k->grow(s, pass + 1);
        }
    for (int i = 0; i < OBJS; i += 64)                     // roots: every 64th object
        for (shape *s = all[i]; s && !s->mark; s = s->ref) {
            s->mark = 1;
            sum++;
        }
    return sum;
}
