# M3 benchmark: load misses, one independent load per 32-byte line. Two
# passes over 64 KB (L1D misses; L2 hits on the second), then 512 KB (L2
# misses).
        .code32
        .globl _start
_start: xor     %eax, %eax
        mov     $2, %ebp
pass:   mov     $0x40000, %esi
        mov     $(0x10000 / 32), %ecx
1:      add     (%esi), %eax
        add     $32, %esi
        dec     %ecx
        jnz     1b
        dec     %ebp
        jnz     pass
        mov     $0x80000, %esi
        mov     $(0x80000 / 32), %ecx
2:      add     (%esi), %eax
        add     $32, %esi
        dec     %ecx
        jnz     2b
        hlt
