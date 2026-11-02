# M3 benchmark: load misses that do not stream, one load per 4 KB + 32
# bytes (a new page each time; the L2 prefetch must stay off).
        .code32
        .globl _start
_start: xor     %eax, %eax
        mov     $0x40000, %esi
        mov     $8192, %ecx
1:      add     (%esi), %eax
        add     $0x1020, %esi
        and     $0xfffff, %esi
        dec     %ecx
        jnz     1b
        hlt
