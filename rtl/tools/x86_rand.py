#!/usr/bin/env python3
# Usage: rtl/tools/x86_rand.py <seed> <out.S>
# Random terminating flat 32-bit program in the M2 decoder subset
# (rtl/x86/x86_decode.sv): EDI = 64-byte buffer base, EBP = loop counter,
# ESP = stack; EAX..ESI are free (8/16-bit forms included). Unaligned
# buffer offsets and mixed sizes exercise store-to-load forwarding and
# partial overlaps.
import random
import sys

FREE = ["%eax", "%ebx", "%ecx", "%edx", "%esi"]
REGS = {"b": ["%al", "%cl", "%dl", "%bl", "%ah", "%ch", "%dh", "%bh"],
        "w": ["%ax", "%cx", "%dx", "%bx", "%si"], "l": FREE}
ALU = ["add", "or", "adc", "sbb", "and", "sub", "xor", "cmp"]
JCC = ["jo", "jno", "jb", "jae", "je", "jne", "jbe", "ja",
       "js", "jns", "jp", "jnp", "jl", "jge", "jle", "jg"]


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: x86_rand.py <seed> <out.S>")
    rnd = random.Random(int(sys.argv[1]))
    labels = iter(range(1 << 30))
    subs = []

    def reg():
        return rnd.choice(FREE)

    def sreg(sfx):
        return rnd.choice(REGS[sfx])

    def mem():
        return "%d(%%edi)" % rnd.randrange(61)

    def imm(sfx="l"):
        lim = {"b": 7, "w": 15, "l": 31}[sfx]
        return "$%d" % rnd.choice([rnd.randrange(-128, 128), rnd.randrange(-2**lim, 2**lim)])

    def insn():
        k = rnd.randrange(28)
        x = rnd.choice("lllbw")   # operand size suffix of forms 0-9
        a = rnd.choice(ALU) + x
        if k == 0:
            return ["%s %s, %s" % (a, sreg(x), sreg(x))]
        if k == 1:
            return ["%s %s, %s" % (a, imm(x), sreg(x))]
        if k == 2:
            return ["%s %s, %s" % (a, mem(), sreg(x))]
        if k == 3:
            return ["%s %s, %s" % (a, sreg(x), mem())]
        if k == 4:
            return ["%s %s, %s" % (a, imm(x), mem())]
        if k == 5:
            return ["test%s %s, %s" % (x, rnd.choice([sreg(x), imm(x)]), sreg(x))]
        if k == 6:
            return ["%s%s %s" % (rnd.choice(["inc", "dec"]), x, sreg(x))]
        if k == 7:
            return ["%s%s %s" % (rnd.choice(["inc", "dec"]), x, mem())]
        if k == 8:
            return ["mov%s %s, %s" % (x, rnd.choice([sreg(x), imm(x), mem()]), sreg(x))]
        if k == 9:
            return ["mov%s %s, %s" % (x, rnd.choice([sreg(x), imm(x)]), mem())]
        if k == 10:
            return ["lea %d(%s,%s,%d), %s" % (rnd.randrange(-300, 300), reg(), reg(),
                                             rnd.choice([1, 2, 4, 8]), reg())]
        if k == 11:   # indexed buffer access
            i = reg()
            return ["and $15, %s" % i, "mov (%%edi,%s,4), %s" % (i, reg())]
        if k == 12:
            src = rnd.choice([reg(), imm(), mem()])
            return ["push%s %s" % ("l" if src.startswith("$") or "(" in src else "", src),
                    *run(rnd.randrange(3)), "pop %s" % reg()]
        if k == 13:   # movzx / movsx: from 8 or 16 bits into 32, from 8 into 16
            src, dst = rnd.choice(["bl", "wl", "bw"])
            return ["mov%s%s%s %s, %s" % (rnd.choice("zs"), src, dst,
                                          rnd.choice([sreg(src), mem()]), sreg(dst))]
        if k == 14:   # shifts / rotates by imm, CL or 1
            cnt = rnd.choice(["$%d" % rnd.randrange(32), "%cl", ""])
            dst = rnd.choice([sreg(x), mem()])
            op = rnd.choice(["shl", "sal", "shr", "sar", "rol", "ror"]) + x
            return ["%s %s%s" % (op, cnt + ", " if cnt else "", dst)]
        if k == 15:
            return ["%s%s %s" % (rnd.choice(["not", "neg"]), x, rnd.choice([sreg(x), mem()]))]
        if k == 16:
            return ["set%s %s" % (rnd.choice(JCC)[1:], rnd.choice([sreg("b"), mem()]))]
        if k == 17:
            y = rnd.choice("lw")
            return ["cmov%s%s %s, %s" % (rnd.choice(JCC)[1:], y, rnd.choice([sreg(y), mem()]), sreg(y))]
        if k == 18:
            return [rnd.choice(["cltd", "cwtl", "cbtw", "cwtd"])]
        if k == 19:
            return ["xchg%s %s, %s" % (x, sreg(x), rnd.choice([sreg(x), mem()]))]
        if k == 20:   # 2/3-operand IMUL
            y = rnd.choice("lw")
            src = rnd.choice([sreg(y), mem()])
            return [rnd.choice(["imul%s %s, %s" % (y, src, sreg(y)),
                                "imul%s %s, %s, %s" % (y, imm(y), src, sreg(y))])]
        if k == 21:   # one-operand MUL / IMUL: eDX:eAX or AX
            return ["%s%s %s" % (rnd.choice(["mul", "imul"]), x, rnd.choice([sreg(x), mem()]))]
        if k == 22:   # DIV / IDIV, set up so no divide error can occur
            sgn = rnd.randrange(2)
            m = rnd.randrange(2)
            d = mem() if m else {"b": rnd.choice(["%cl", "%bl", "%ch", "%bh"]),
                                 "w": rnd.choice(["%cx", "%bx", "%si"]),
                                 "l": rnd.choice(["%ecx", "%ebx", "%esi"])}[x]
            setup = {"b": ["cbtw"] if sgn else ["movzbl %al, %eax"],
                     "w": ["cwtd"] if sgn else ["xorw %dx, %dx"],
                     "l": ["cltd"] if sgn else ["xorl %edx, %edx"]}[x]
            mask = {"b": "$0x7f", "w": "$0x7fff", "l": "$0x7fff"}[x]
            fix = ["and%s %s, %s" % (x, mask, d), "or%s $2, %s" % (x, d)] if sgn \
                else ["or%s $1, %s" % (x, d)]
            return [*fix, *setup, "%s%s %s" % ("idiv" if sgn else "div", x, d)]
        if k == 23:   # SHLD / SHRD (16-bit counts above 16 included)
            y = rnd.choice("lw")
            cnt = rnd.choice(["$%d" % rnd.randrange(32), "%cl"])
            return ["%s%s %s, %s, %s" % (rnd.choice(["shld", "shrd"]), y, cnt, sreg(y),
                                         rnd.choice([sreg(y), mem()]))]
        if k == 24:   # [REP] MOVS / STOS / LODS (DF = 0), ESI / EDI inside the buffer
            sz = rnd.choice("bwl")
            n = rnd.randrange(7)
            r = rnd.randrange(3) != 0
            w = {"b": 1, "w": 2, "l": 4}[sz] * (n if r else 1)
            lines = ["push %edi", "lea %d(%%edi), %%esi" % rnd.randrange(65 - w),
                     "lea %d(%%edi), %%edi" % rnd.randrange(65 - w), "mov $%d, %%ecx" % n,
                     ("rep " if r else "") + rnd.choice(["movs", "stos", "lods"]) + sz, "pop %edi"]
            return (["cld"] if rnd.randrange(4) == 0 else []) + lines
        if k == 25:   # BSF / BSR (zero sources included), BSWAP
            if rnd.randrange(3) == 0:
                return ["bswap %s" % reg()]
            y = rnd.choice("lw")
            src = rnd.choice([sreg(y), mem()])
            zero = ["mov%s $0, %s" % (y, src)] if rnd.randrange(4) == 0 else []
            return [*zero, "%s%s %s, %s" % (rnd.choice(["bsf", "bsr"]), y, src, sreg(y))]
        if k == 26:   # BT / BTS / BTR / BTC; a register offset on a register only
            y = rnd.choice("lw")
            op = rnd.choice(["bt", "bts", "btr", "btc"]) + y
            if rnd.randrange(2):
                return ["%s %s, %s" % (op, sreg(y), sreg(y))]
            return ["%s $%d, %s" % (op, rnd.randrange(256), rnd.choice([sreg(y), mem()]))]
        return ["nop"]

    def run(n):
        out = []
        for _ in range(n):
            x = insn()
            if rnd.randrange(16) == 0:   # segment prefix, a no-op in the flat model
                x.insert(len(x) - 1, ".byte 0x%x" % rnd.choice([0x26, 0x2E, 0x36, 0x3E]))
            out += x
        return out

    def block():
        k = rnd.randrange(6)
        if k == 0:
            l = next(labels)
            return ["mov $%d, %%ebp" % rnd.randrange(1, 9), "L%d:" % l, *run(rnd.randrange(1, 8)),
                    "dec %ebp", "jnz L%d" % l]
        if k == 1:
            l = next(labels)
            return [*run(rnd.randrange(1, 3)), "%s L%d" % (rnd.choice(JCC), l),
                    *run(rnd.randrange(1, 6)), "L%d:" % l]
        if k == 2:
            l = next(labels)
            body = run(rnd.randrange(1, 6))
            if rnd.randrange(2):   # frame pointer: LEAVE restores ESP, EBP
                body = ["push %ebp", "mov %esp, %ebp", *body, "pushl $7", "leave"]
            subs.append(["S%d:" % l, *body, "rep ret" if rnd.randrange(4) == 0 else "ret"])
            if rnd.randrange(2):
                return ["call S%d" % l]
            r = reg()
            return ["lea S%d, %s" % (l, r), "call *%s" % r]
        if k == 3:
            l, r = next(labels), reg()
            return ["lea L%d, %s" % (l, r), "jmp *%s" % r, *run(2), "L%d:" % l]
        if k == 4:   # LOOP / LOOPE / LOOPNE: ECX - 1 = EBP, so it ends; JECXZ
            l = next(labels)
            if rnd.randrange(3) == 0:
                return [*(["mov $0, %ecx"] if rnd.randrange(2) else []), "jecxz L%d" % l,
                        *run(rnd.randrange(1, 4)), "L%d:" % l]
            return ["mov $%d, %%ebp" % rnd.randrange(1, 9), "L%d:" % l, *run(rnd.randrange(1, 6)),
                    "dec %ebp", *run(rnd.randrange(2)), "lea 1(%ebp), %ecx",
                    "%s L%d" % (rnd.choice(["loop", "loope", "loopne"]), l)]
        return run(rnd.randrange(1, 10))

    out = [".code32", ".globl _start", "_start:", "mov $0x9000, %edi"]
    out += ["mov %s, %s" % (imm(), r) for r in FREE]
    out += ["movl %s, %d(%%edi)" % (imm(), 4 * i) for i in range(17)]
    for _ in range(40):
        out += block()
    out.append("hlt")
    for s in subs:
        out += s
    with open(sys.argv[2], "w") as f:
        f.write("".join((x if x.endswith(":") or x.startswith(".") else "        " + x) + "\n"
                        for x in out))


main()
