# X1 subset smoke test (plan/cpu_core.md X1): ALU, flags, Jcc, load/store.
        .code32
        .globl _start
_start: mov     $0x1234, %eax
        mov     $-1, %ecx
        add     %ecx, %eax          # CF=1
        sub     $0x10, %eax
        xor     %edx, %edx          # ZF=1
        mov     $10, %ebx
loop:   inc     %edx
        lea     3(%edx,%edx,2), %esi
        cmp     %ebx, %edx
        jne     loop
        mov     $0x8000, %edi
        mov     %esi, (%edi)
        mov     %eax, 4(%edi,%edx,4)
        mov     44(%edi), %ebp
        and     $0xff, %ebp
        or      (%edi), %ebp
        test    %ebp, %ebp
        jz      bad
        dec     %ecx
        jmp     done
bad:    mov     $0xdead, %eax
done:   hlt
