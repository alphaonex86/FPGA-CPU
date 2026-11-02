# c2-vmm test ROM (sim backend, 64 KB at 0xf0000): serial, POST code, MMIO
# round trip, RAM, an injected interrupt; exit port 0xf4: 0 pass, else the
# failed step.
        .code16
        .text
start:  cli
        xor     %ax, %ax
        mov     %ax, %ss
        mov     %ax, %ds
        mov     $0x7000, %sp
        mov     $0x11, %al
        out     %al, $0x80
        # serial
        mov     $msg, %si
1:      mov     %cs:(%si), %al
        test    %al, %al
        jz      2f
        mov     $0x3f8, %dx
        out     %al, %dx
        inc     %si
        jmp     1b
        # MMIO scratch at 0xd0000: dword, word, unaligned dword
2:      mov     $0xd000, %ax
        mov     %ax, %es
        movl    $0x12345678, %es:0
        cmpl    $0x12345678, %es:0
        mov     $1, %bl
        jne     fail
        movw    $0xbeef, %es:6
        movl    $0xcafe55aa, %es:9
        cmpw    $0xbeef, %es:6
        mov     $2, %bl
        jne     fail
        cmpl    $0xcafe55aa, %es:9
        mov     $3, %bl
        jne     fail
        # RAM below and above the ROM window
        movl    $0xa5a55a5a, 0x1000
        cmpl    $0xa5a55a5a, 0x1000
        mov     $4, %bl
        jne     fail
        # interrupt: vector 0x23 (0xf5 <- 3) while halted
        movw    $isr, 0x23 * 4
        movw    %cs, 0x23 * 4 + 2
        movb    $0, 0x500
        mov     $3, %al
        out     %al, $0xf5
        sti
        hlt
        cli
        cmpb    $1, 0x500
        mov     $5, %bl
        jne     fail
        xor     %bl, %bl
fail:   mov     %bl, %al
        out     %al, $0xf4
        jmp     .

isr:    movb    $1, 0x500
        iret

msg:    .asciz  "c2-vmm: serial ok\n"

        .org    0xfff0
        ljmp    $0xf000, $start
        .org    0x10000
