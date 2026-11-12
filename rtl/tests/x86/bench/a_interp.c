// Python-like profile (x86_bench.sh interp): a stack bytecode interpreter as CPython runs code: a
// dispatch loop (an indirect jump per opcode), boxed integers with reference counts from a free
// list, a dict (open hashing) and a growing list. One call runs the program once:
//   i = 0; s = 0
//   while i < N: d[i & 63] = d.get(i & 63, 0) + i; s = s + i * 3; lst.append(s); i = i + 1
//   return s
typedef unsigned u32;
enum { PUSH, LOAD, STORE, ADD, MUL, LT, JMPF, JMP, DGET, DSET, APPEND, END };
#define N 2000
#define POOL 256
#define DICT 128

typedef struct obj { u32 refs, val; struct obj *next; } obj;
static obj pool[POOL], *free_list;
static u32 dict_key[DICT], dict_val[DICT], dict_used[DICT], dict_gen;
static u32 list[N], list_len;

static const u32 code[][2] = {
    {PUSH, 0}, {STORE, 0}, {PUSH, 0}, {STORE, 1},
    {LOAD, 0}, {PUSH, N}, {LT, 0}, {JMPF, 27},                                  // 4: while i < N
    {LOAD, 0}, {DGET, 0}, {LOAD, 0}, {ADD, 0}, {LOAD, 0}, {DSET, 0},            // 8: d[i & 63] += i
    {LOAD, 1}, {LOAD, 0}, {PUSH, 3}, {MUL, 0}, {ADD, 0}, {STORE, 1},            // 14: s += i * 3
    {LOAD, 1}, {APPEND, 0},                                                     // 20: lst.append(s)
    {LOAD, 0}, {PUSH, 1}, {ADD, 0}, {STORE, 0}, {JMP, 4},                       // 22: i += 1
    {LOAD, 1}, {END, 0},                                                        // 27
};

static obj *box(u32 v)
{
    obj *o = free_list;
    free_list = o->next;
    o->refs = 1;
    o->val = v;
    return o;
}

static void decref(obj *o)
{
    if (--o->refs == 0) {
        o->next = free_list;
        free_list = o;
    }
}

static u32 *dict_slot(u32 key)
{
    u32 h = (key * 0x9e3779b1u) >> 25;
    while (dict_used[h] == dict_gen && dict_key[h] != key) h = (h + 1) & (DICT - 1);
    if (dict_used[h] != dict_gen) {
        dict_used[h] = dict_gen;
        dict_key[h] = key;
        dict_val[h] = 0;
    }
    return &dict_val[h];
}

u32 main(void)
{
    obj *stack[16], *vars[2] = {0, 0};
    int sp = 0;
    u32 pc = 0, r;
    free_list = 0;
    for (int k = 0; k < POOL; k++) {
        pool[k].next = free_list;
        free_list = &pool[k];
    }
    dict_gen++;
    list_len = 0;
    for (;;) {
        u32 op = code[pc][0], arg = code[pc][1];
        pc++;
        switch (op) {
        case PUSH: stack[sp++] = box(arg); break;
        case LOAD: stack[sp++] = vars[arg]; vars[arg]->refs++; break;
        case STORE: if (vars[arg]) decref(vars[arg]); vars[arg] = stack[--sp]; break;
        case ADD: case MUL: case LT: {
            obj *b = stack[--sp], *a = stack[--sp];
            stack[sp++] = box(op == ADD ? a->val + b->val : op == MUL ? a->val * b->val : a->val < b->val);
            decref(a);
            decref(b);
            break;
        }
        case JMPF: { obj *c = stack[--sp]; if (!c->val) pc = arg; decref(c); break; }
        case JMP: pc = arg; break;
        case DGET: { obj *k = stack[--sp]; stack[sp++] = box(*dict_slot(k->val & 63)); decref(k); break; }
        case DSET: {
            obj *k = stack[--sp], *v = stack[--sp];
            *dict_slot(k->val & 63) = v->val;
            decref(k);
            decref(v);
            break;
        }
        case APPEND: { obj *v = stack[--sp]; list[list_len++] = v->val; decref(v); break; }
        default:
            r = stack[--sp]->val + list[list_len / 2];
            return r;
        }
    }
}
