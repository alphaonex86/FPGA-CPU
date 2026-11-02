# c2-vmm test ROM (sim / rtl backends, 64 KB at 0xf0000): serial, POST
# code, MMIO round trip, RAM, an injected interrupt, string I/O, shadow RAM,
# NMI, STPCLK#, Halt, A20M#, INIT#, shutdown, a board reset (0xcf9); exit
# port 0xf4: 0 pass, else the failed step.
# Expects the default signature 0x683 (c2-vmm -s) in EDX at reset.
        .code16
        .text
start:  mov     %edx, %ebp
        cli
        xor     %ax, %ax
        mov     %ax, %ss
        mov     %ax, %ds
        mov     $0x7000, %sp
        mov     $0x11, %al
        out     %al, $0x80
        cmp     $0x683, %ebp
        mov     $14, %bl
        jne     fail
        # the phase in RAM (INIT# and resets keep it): 0 power-on, 1 after
        # INIT#, 2 after the shutdown's INIT#, 3 after the board reset
        mov     $0xc000, %ax
        mov     %ax, %es
        cmpb    $1, 0x600
        je      after_init
        cmpb    $2, 0x600
        je      after_shutdown
        cmpb    $3, 0x600
        je      after_reset
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
        mov     $0x170, %dx
        rep insw
        cmpl    $0xffffffff, 0x2000
        mov     $10, %bl
        jne     fail
        cmpl    $0xffffffff, 0x2004
        jne     fail
        # string I/O both ways through the FIFO port 0x1f0 (coalesced
        # writes): ROM bytes out as words and dwords, back into RAM, compared
        push    %ds
        push    %cs
        pop     %ds
        xor     %si, %si
        mov     $0x1f0, %dx
        mov     $256, %cx
        rep outsw
        mov     $64, %cx
        rep outsl
        pop     %ds
        mov     $0x3000, %di
        mov     $256, %cx
        rep insw
        mov     $64, %cx
        rep insl
        push    %ds
        push    %cs
        pop     %ds
        xor     %si, %si
        mov     $0x3000, %di
        mov     $384, %cx
        repe cmpsw
        pop     %ds
        mov     $11, %bl
        jne     fail
        # INTR rising while the guest loops in RAM without exits (vector
        # 0x28, 5 ms after the write to 0xf7)
        movw    $isr, 0x28 * 4
        movw    %cs, 0x28 * 4 + 2
        movb    $0, 0x500
        mov     $5, %al
        out     %al, $0xf7
        mov     $0xffffffff, %ecx
        sti
1:      cmpb    $1, 0x500
        je      2f
        dec     %ecx
        jnz     1b
2:      cli
        mov     $12, %bl
        test    %ecx, %ecx
        jz      fail
        # coalesced MMIO (the VGA window, sim scratch at 0xa0000): writes
        # without exits, read back in order
        mov     $0xa000, %ax
        mov     %ax, %es
        movl    $0x11223344, %es:0
        movw    $0x5566, %es:6
        movb    $0x77, %es:9
        movl    $0x8899aabb, %es:0x0d
        cmpl    $0x11223344, %es:0
        mov     $13, %bl
        jne     fail
        cmpw    $0x5566, %es:6
        jne     fail
        cmpb    $0x77, %es:9
        jne     fail
        cmpl    $0x8899aabb, %es:0x0d
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
        # NMI (0xf8 bit 0): vector 2 sets 0x501; an I/O exit per try
        movw    $nmi_isr, 2 * 4
        movw    %cs, 2 * 4 + 2
        movb    $0, 0x501
        mov     $1, %al
        out     %al, $0xf8
        mov     $100000, %ecx
1:      cmpb    $1, 0x501
        je      2f
        in      $0x80, %al
        dec     %ecx
        jnz     1b
2:      mov     $16, %bl
        test    %ecx, %ecx
        jz      fail
        # STPCLK# (0xf8 bit 1) until the VMM's Stop Grant Acknowledge,
        # counted in 0xf8 bits 7:0
        mov     $2, %al
        out     %al, $0xf8
        mov     $100000, %ecx
1:      in      $0xf8, %al
        cmp     $1, %al
        je      2f
        dec     %ecx
        jnz     1b
2:      mov     $17, %bl
        test    %ecx, %ecx
        jz      fail
        # the HLT of step 5 went out as a Halt Transaction (0xf8 bits 15:8)
        in      $0xf8, %ax
        test    %ah, %ah
        mov     $18, %bl
        jz      fail
        # A20M# (port 0x92 bit 1 = 0 since reset): 0xffff:0x8010 wraps to
        # 0x8000; with FAST_A20 it is 0x108000 (fresh RAM: 0)
        movl    $0x12345678, 0x8000
        mov     $0xffff, %ax
        mov     %ax, %es
        cmpl    $0x12345678, %es:0x8010
        mov     $19, %bl
        jne     fail
        mov     $2, %al
        out     %al, $0x92
        mov     $100000, %ecx
1:      cmpl    $0, %es:0x8010
        je      2f
        in      $0x80, %al
        dec     %ecx
        jnz     1b
2:      mov     $20, %bl
        test    %ecx, %ecx
        jz      fail
        # INIT# (port 0x92 bit 0; A20M# again): the vCPU restarts
        movb    $1, 0x600
        mov     $1, %al
        out     %al, $0x92
        sti
1:      hlt
        jmp     1b

        # INIT# keeps the chipset: PAM1 still 3, 0xc0010 the shadow RAM
after_init:
        cmpl    $0x600dc0de, %es:0x10
        mov     $21, %bl
        jne     fail
        # triple fault (IDT limit 0): the Shutdown Transaction, the PIIX4
        # answers with INIT#
        movb    $2, 0x600
        lidt    %cs:idt_none
        int     $3

        # board reset (440BX hard reset), halted until the vCPU restarts
after_shutdown:
        movb    $3, 0x600
        mov     $6, %al
        mov     $0xcf9, %dx
        out     %al, %dx
        sti
1:      hlt
        jmp     1b

        # the reset set PAM1 to 0: 0xc0000 on the bus again (floats high)
after_reset:
        cmpl    $0xffffffff, %es:0x10
        mov     $15, %bl
        jne     fail
        xor     %bl, %bl
fail:   mov     %bl, %al
        out     %al, $0xf4
        jmp     .

isr:    movb    $1, 0x500
        iret
nmi_isr: movb   $1, 0x501
        iret
idt_none: .word 0
        .long   0

msg:    .asciz  "c2-vmm: serial ok\n"
rep_msg: .ascii "c2-vmm: string I/O ok\n"
rep_end:

        .org    0xfff0
        ljmp    $0xf000, $start
        .org    0x10000
