# M5 test: KEN# (x86_uc learns the region): without S3_BUS core_top answers the 64 KB at 0x80000
# without KEN#. The first access there is a line read the caches must not keep; then loads and
# stores go uncached. Code copied there runs from the L1I's uncached line buffer.
        .code32
        .globl _start
_start: mov     $0x80000, %edi
        mov     (%edi), %eax               # learns the region
        movl    $0x01020304, 4(%edi)
        movl    $0x0a0b0c0d, 7(%edi)       # across a dword
        mov     4(%edi), %ebx
        mov     6(%edi), %ecx
        addl    $0x11111111, 8(%edi)
        mov     8(%edi), %edx
        mov     $0x83ffc, %esi             # another 4 KB page of the region
        movl    $0x5a5a5a5a, (%esi)
        mov     (%esi), %ebp
        # copy fn into the region and run it there
        mov     $fn, %esi
        mov     $0x80100, %edi
        mov     $(fn_end - fn), %ecx
        cld
        rep movsb
        mov     $0x80100, %edx
        mov     $7, %eax
        mov     $5, %ebx
        call    *%edx
        call    *%edx
        mov     %eax, 0x80200
        mov     0x80200, %ecx
        # a cached region next to it still caches
        mov     $0x90000, %edi
        movl    $0x13572468, (%edi)
        mov     (%edi), %esi
        hlt
fn:     add     %ebx, %eax
        lea     3(%eax,%ebx,2), %eax
        mov     $4, %ecx
1:      add     %ecx, %eax
        dec     %ecx
        jnz     1b
        ret
fn_end:
