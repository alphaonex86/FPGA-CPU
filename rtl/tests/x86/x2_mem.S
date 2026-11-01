# M2 test: stack (PUSH/POP/CALL/RET), memory RMW, store-to-load forwarding,
# ADC/SBB carry chains, nested loops.
        .code32
        .globl _start
_start: mov     $0x9000, %edi
        movl    $5, (%edi)
        addl    $7, (%edi)          # RMW
        mov     (%edi), %eax        # forwarded from the RMW store
        incl    4(%edi)
        decl    8(%edi)
        mov     4(%edi), %ebx
        add     8(%edi), %ebx       # load operand
        push    %eax
        push    %ebx
        pushl   $0x55
        pushl   (%edi)
        pop     %ecx
        pop     %edx
        pop     %esi
        pop     %ebp
        mov     $-1, %eax
        mov     $0, %edx
        add     $1, %eax
        adc     $0, %edx            # 64-bit increment
        sub     $1, %eax
        sbb     $0, %edx
        mov     $3, %ecx
outer:  mov     $4, %esi
inner:  call    acc
        dec     %esi
        jnz     inner
        dec     %ecx
        jnz     outer
        xor     %ebx, (%edi)
        test    $0x80, %ebx
        mov     (%edi), %ebp
        jmp     *%ebx
        hlt
acc:    add     %esi, %eax
        sbb     %ecx, %edx
        lea     after, %ebx
        ret
after:  cmp     4(%edi), %eax
        test    %eax, (%edi)
        hlt
