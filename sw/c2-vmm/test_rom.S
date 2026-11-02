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
        # string I/O (one batch): rep outsb to the serial port, rep insw
        # from a floating port into RAM
        push    %ds
        push    %cs
        pop     %ds
        mov     $rep_msg, %si
        mov     $(rep_end - rep_msg), %cx
        mov     $0x3f8, %dx
        cld
        rep outsb
        pop     %ds
        xor     %ax, %ax
        mov     %ax, %es
        mov     $0x2000, %di
        movl    $0, 0x2000
        movl    $0, 0x2004
        mov     $4, %cx
        mov     $0x1f0, %dx
        rep insw
        cmpl    $0xffffffff, 0x2000
        mov     $10, %bl
        jne     fail
        cmpl    $0xffffffff, 0x2004
        jne     fail
        # 440BX shadow: 0xc0000 on the bus while PAM1 = 0 (sim: floats high)
        mov     $0xc000, %ax
        mov     %ax, %es
        cmpb    $0xff, %es:0
        mov     $6, %bl
        jne     fail
        # copy the BIOS segment onto itself (PAM0 write-only), running from it
        mov     $0x80000058, %eax       # config 0:0:0, dword 0x58 (PAM0 = byte 0x59)
        mov     $0xcf8, %dx
        out     %eax, %dx
        mov     $0x20, %al
        mov     $0xcfd, %dx
        out     %al, %dx
        push    %ds
        mov     $0xf000, %ax
        mov     %ax, %ds
        mov     %ax, %es
        xor     %si, %si
        xor     %di, %di
        mov     $0x8000, %cx
        cld
        rep movsw
        pop     %ds
        # read-only: a write goes to the bus, the shadow keeps the copy
        mov     $0x10, %al
        out     %al, %dx
        movb    $0x55, %es:0xfffe
        cmpb    $0, %es:0xfffe
        mov     $7, %bl
        jne     fail
        # read/write: the shadow RAM takes it
        mov     $0x30, %al
        out     %al, %dx
        movb    $0x55, %es:0xfffe
        cmpb    $0x55, %es:0xfffe
        mov     $8, %bl
        jne     fail
        # 0xc0000 read/write (PAM1[3:0] = 3, byte 0x5a)
        mov     $0x03, %al
        mov     $0xcfe, %dx
        out     %al, %dx
        mov     $0xc000, %ax
        mov     %ax, %es
        movl    $0x600dc0de, %es:0x10
        cmpl    $0x600dc0de, %es:0x10
        mov     $9, %bl
        jne     fail
        xor     %bl, %bl
fail:   mov     %bl, %al
        out     %al, $0xf4
        jmp     .

isr:    movb    $1, 0x500
        iret

msg:    .asciz  "c2-vmm: serial ok\n"
rep_msg: .ascii "c2-vmm: string I/O ok\n"
rep_end:

        .org    0xfff0
        ljmp    $0xf000, $start
        .org    0x10000
