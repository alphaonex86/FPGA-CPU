# M5 test: WBINVD / INVD (0F 09 / 0F 08; INVD writes back too). The flush starts when the
# instruction is the ROB head with its older stores drained, then the next instruction is fetched
# again: 48 KB written (dirty lines in the L1D and the L2) must read back after it, a store right
# before it and a load right after it, and a loop around it.
        .code32
        .globl _start
_start: mov     $0x20000, %edi
        mov     $0x3000, %ecx              # 48 KB: more than the L1D
        mov     $0x12345678, %eax
1:      mov     %eax, (%edi)
        rol     $3, %eax
        add     $4, %edi
        dec     %ecx
        jnz     1b
        wbinvd
        mov     $0x20000, %edi
        mov     $0x3000, %ecx
        xor     %ebx, %ebx
2:      add     (%edi), %ebx
        add     $4, %edi
        dec     %ecx
        jnz     2b
        mov     %ebx, 0x9000
        invd
        mov     0x9000, %edx
        mov     $5, %ecx
3:      add     %ecx, %edx
        mov     %edx, 0x9004(,%ecx,4)
        wbinvd
        mov     0x9004(,%ecx,4), %esi
        add     %esi, %ebx
        invd
        dec     %ecx
        jnz     3b
        hlt
