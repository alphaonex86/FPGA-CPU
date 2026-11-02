// CoreMark port for the flat 32-bit test image (tests/x86/c5_coremark.c):
// no timer (the testbench counts cycles), no printf: ee_printf folds its
// arguments into ee_sink so the results stay live. COREMARK_HOSTED builds
// the same code natively with printf, to validate the CRCs.
#ifndef CORE_PORTME_H
#define CORE_PORTME_H

#define HAS_FLOAT        0
#define HAS_TIME_H       0
#define USE_CLOCK        0
#define MAIN_HAS_NOARGC  1
#define SEED_METHOD      SEED_VOLATILE
#define MEM_METHOD       MEM_STACK
#define MEM_LOCATION     "STACK"
#define MULTITHREAD      1
#define COMPILER_VERSION "GCC" __VERSION__
#define COMPILER_FLAGS   "-O2 -march=i686"
#ifdef COREMARK_HOSTED
#define HAS_STDIO  1
#define HAS_PRINTF 1
#else
#define HAS_STDIO  0
#define HAS_PRINTF 0
int ee_printf(const char *fmt, ...);
#endif

typedef signed short   ee_s16;
typedef unsigned short ee_u16;
typedef signed int     ee_s32;
typedef unsigned char  ee_u8;
typedef unsigned int   ee_u32;
typedef ee_u32         ee_ptr_int;
typedef ee_u32         ee_size_t;
#ifndef NULL
#define NULL ((void *)0)
#endif
#define align_mem(x) (void *)(4 + (((ee_ptr_int)(x)-1) & ~3))
#define CORETIMETYPE ee_u32
typedef ee_u32 CORE_TICKS;

extern ee_u32 default_num_contexts;
typedef struct CORE_PORTABLE_S {
    ee_u8 portable_id;
} core_portable;
void portable_init(core_portable *p, int *argc, char *argv[]);
void portable_fini(core_portable *p);

#endif
