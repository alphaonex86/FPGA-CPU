#include "coremark.h"

volatile ee_s32 seed1_volatile = 0x0;   // performance run (2K)
volatile ee_s32 seed2_volatile = 0x0;
volatile ee_s32 seed3_volatile = 0x66;
volatile ee_s32 seed4_volatile = ITERATIONS;
volatile ee_s32 seed5_volatile = 0;
ee_u32 default_num_contexts = 1;

void start_time(void) {}
void stop_time(void) {}
CORE_TICKS get_time(void) { return 0; }
secs_ret time_in_secs(CORE_TICKS ticks) { return ticks; }

void portable_init(core_portable *p, int *argc, char *argv[])
{
    (void)argc;
    (void)argv;
    p->portable_id = 1;
}

void portable_fini(core_portable *p) { p->portable_id = 0; }

#ifndef COREMARK_HOSTED
#include <stdarg.h>
volatile ee_u32 ee_sink;

int ee_printf(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    for (const char *c = fmt; *c; c++) {
        if (*c != '%') continue;
        while (*++c == 'l' || (*c >= '0' && *c <= '9')) {}
        if (*c == 's') for (const char *s = va_arg(ap, const char *); *s; s++) ee_sink += *s;
        else if (*c && *c != '%') ee_sink += va_arg(ap, ee_u32);
        if (!*c) break;
    }
    va_end(ap);
    return 0;
}

void *memset(void *d, int v, ee_u32 n)
{
    ee_u8 *p = d;
    while (n--) *p++ = v;
    return d;
}

void *memcpy(void *d, const void *s, ee_u32 n)
{
    ee_u8 *p = d;
    const ee_u8 *q = s;
    while (n--) *p++ = *q++;
    return d;
}
#endif
