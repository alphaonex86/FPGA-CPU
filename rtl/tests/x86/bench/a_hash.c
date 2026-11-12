// Database profile (x86_bench.sh hash): a hash join as a database runs it: 12K rows inserted into an
// open-addressing table of 32K slots (384 KB: past the L1, in the L2), then 24K probes, half of them
// misses. Random access to a large table, a short probe loop.
typedef unsigned u32;
#define SLOTS 32768
#define ROWS 12288

typedef struct { u32 gen, key, val; } slot;
static slot table[SLOTS];
static u32 gen;

static u32 mix(u32 k) { k ^= k >> 16; k *= 0x7feb352du; k ^= k >> 15; return k; }

u32 main(void)
{
    u32 seed = 1, sum = 0, found = 0;
    gen++;                                    // a new generation empties the table
    for (u32 i = 0; i < ROWS; i++) {
        u32 key = seed = seed * 1664525u + 1013904223u, h = mix(key) & (SLOTS - 1);
        while (table[h].gen == gen && table[h].key != key) h = (h + 1) & (SLOTS - 1);
        table[h] = (slot){gen, key, i};
    }
    seed = 1;
    for (u32 i = 0; i < 2 * ROWS; i++) {
        u32 key = i & 1 ? i * 0x9e3779b1u : (seed = seed * 1664525u + 1013904223u), h = mix(key) & (SLOTS - 1);
        while (table[h].gen == gen) {
            if (table[h].key == key) {
                sum += table[h].val;
                found++;
                break;
            }
            h = (h + 1) & (SLOTS - 1);
        }
    }
    return found * 100000 + sum % 100000;
}
