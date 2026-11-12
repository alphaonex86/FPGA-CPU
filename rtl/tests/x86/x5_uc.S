# M5 test: uncached memory (the VGA window A0000-BFFFF, x86_uc): stores and loads of 1 / 2 / 4
# bytes, aligned and across a dword, RMW, a load right after a store to it (no forwarding), string
# operations, interleaved with cached memory. core_top stops the run on a line access there.
        .code32
        .globl _start
_start: mov     $0xb8000, %edi
        mov     $0x9000, %esi
        movl    $0x11223344, (%edi)
        movw    $0x5566, 4(%edi)
        movb    $0x77, 6(%edi)
        movl    $0xa1b2c3d4, 9(%edi)       # across a dword
        movw    $0xe5f6, 15(%edi)          # across a dword
        mov     (%edi), %eax
        mov     2(%edi), %ebx              # across a dword
        movzwl  5(%edi), %ecx
        movsbl  6(%edi), %edx
        mov     9(%edi), %ebp
        add     %eax, (%esi)               # cached
        addl    $0x01010101, (%edi)        # uncached RMW
        mov     (%edi), %eax
        incb    15(%edi)
        movzwl  15(%edi), %ebx
        mov     (%esi), %ecx
        xchg    %ecx, 20(%edi)
        mov     20(%edi), %edx
        # string operations
        lea     0x100(%edi), %edi
        mov     $0x0741, %eax
        mov     $37, %ecx
        cld
        rep stosw
        mov     $0xb8100, %esi
        mov     $0x9100, %edi
        mov     $25, %ecx
        rep movsl                          # uncached -> cached
        mov     $0x9100, %esi
        mov     $0xa0003, %edi
        mov     $41, %ecx
        rep movsb                          # cached -> uncached
        mov     $0xa0003, %esi
        lodsl
        mov     %eax, %ebx
        lodsw
        mov     0xa0010, %ecx
        mov     0xb8148, %edx
        mov     0x9150, %ebp
        hlt
