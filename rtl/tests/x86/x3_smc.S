# M3 test: stores to code. A routine copied (BIOS shadowing) and called;
# an executed instruction's immediate patched, reached again by branches
# (Unicorn retraces a store patching its own translation block: no
# next-instruction case).
        .code32
        .globl _start
_start: mov     $fn, %esi
        mov     $0x20000, %edi
        mov     $(fn_end - fn), %ecx
        rep movsb
        mov     $0x20000, %eax
        call    *%eax
        mov     %eax, %esi
        xor     %edx, %edx
        mov     $4, %ebp
loop:
patch:  mov     $1, %ebx
        add     %ebx, %edx
        incl    patch + 1
        jmp     1f
1:      dec     %ebp
        jnz     loop
        hlt
fn:     mov     $0x1234, %eax
        add     $5, %eax
        ret
fn_end:
