// Types shared by the x86 core (plan/x86_core.md M2).
package x86_pkg;
    localparam int ROB_N = 32;   // reorder buffer entries
    localparam int RS_N = 16;    // unified reservation station entries
    localparam int SQ_N = 8;     // store queue entries
    localparam int TAG_W = $clog2(ROB_N);
    localparam int SQ_W = $clog2(SQ_N);

    // architectural registers renamed by the core: EAX..EDI, then TMP (the
    // internal register between the uops of one instruction)
    localparam logic [3:0] R_ESP = 4'd4, R_TMP = 4'd8, R_TMP2 = 4'd9;
    localparam int NREG = 10;

    // K_MD: x86_muldiv; K_DF: DF = dst[0] at retire, then a flush (decode reads DF)
    typedef enum logic [2:0] {K_ALU, K_LD, K_ST, K_BR, K_HLT, K_ILL, K_MD, K_DF} kind_t;
    // A_LEA: s1 + s2 << scale + imm, no flags; A_ZX8..A_SX16: zero / sign
    // extend b from 8 / 16 bits, no flags; shifts / rotates: a by b[4:0];
    // A_SETCC: cond (uop.cond) as 0/1; A_CMOV: cond ? b : a; A_SIGN: the
    // sign of b (osz) in every bit (CDQ / CWD); A_MUL..A_IDIVR: x86_muldiv
    typedef enum logic [5:0] {A_ADD, A_OR, A_ADC, A_SBB, A_AND, A_SUB, A_XOR, A_CMP,
                              A_TEST, A_INC, A_DEC, A_MOV, A_LEA,
                              A_ZX8, A_ZX16, A_SX8, A_SX16,
                              A_SHL, A_SHR, A_SAR, A_ROL, A_ROR, A_NOT, A_NEG,
                              A_SETCC, A_CMOV, A_SIGN, A_SHLD, A_SHRD,
                              A_BSF, A_BSR, A_BSWAP, A_BT, A_BTS, A_BTR, A_BTC,
                              A_MUL, A_IMUL, A_MULH, A_IMULH, A_IMUL2,
                              A_DIV, A_IDIV, A_DIVR, A_IDIVR} aop_t;

    // operand size: ALU width, memory access size
    localparam logic [1:0] SZ8 = 2'd0, SZ16 = 2'd1, SZ32 = 2'd2;
    // loads: merge into the old destination (s3), zero or sign extend
    localparam logic [1:0] LX_MERGE = 2'd0, LX_ZERO = 2'd1, LX_SIGN = 2'd2;

    // arithmetic flags as the core keeps them, EFLAGS bit order is in eflags()
    typedef struct packed {
        logic of, sf, zf, af, pf, cf;
    } flags_t;

    typedef struct packed {
        kind_t       kind;
        aop_t        aop;
        logic [3:0]  cond;       // K_BR: Jcc condition (opcode low nibble)
        logic        uncond;     // K_BR: JMP/CALL/RET
        logic        indirect;   // K_BR: target = s1 (RET)
        logic        pred_taken; // K_BR: frontend followed the target
        logic        ecxz;       // K_BR: taken when s1 is 0, else s1 - 1 written (REP)
        logic        loopc;      // K_BR: s1 - 1 written, taken when s1 != 1 (and cond if rflags)
        logic [3:0]  dst;
        logic        wdst;
        logic [3:0]  s1, s2, s3; // ALU a/b; memory base/index/store data
        logic        us1, us2, us3;
        logic [1:0]  scale;      // memory index scale
        logic [1:0]  osz;        // SZ8 / SZ16 / SZ32
        logic        hi1, hi2, hi3;   // SZ8 source is AH..BH: bits 15:8
        logic        dhi;        // SZ8 result goes to bits 15:8 of dst
        logic [1:0]  lext;       // K_LD: LX_*
        logic [31:0] imm;        // ALU b when !us2; memory displacement; branch target
        logic [31:0] imm2;       // store data when !us3
        logic        rflags, wflags;
        logic        eop;        // last uop of its x86 instruction
        logic [31:0] next_eip;   // EIP after the instruction (branch fall-through)
    } uop_t;

    // a SZ8 / SZ16 result written into the old 32-bit register value
    function automatic logic [31:0] merge(input logic [31:0] old, input logic [31:0] v,
                                          input logic [1:0] sz, input logic hi);
        case (sz)
            SZ8:     return hi ? {old[31:16], v[7:0], old[7:0]} : {old[31:8], v[7:0]};
            SZ16:    return {old[31:16], v[15:0]};
            default: return v;
        endcase
    endfunction

    function automatic logic [31:0] extend(input logic [31:0] v, input logic [1:0] sz,
                                           input logic sx);
        case (sz)
            SZ8:     return {{24{sx & v[7]}}, v[7:0]};
            SZ16:    return {{16{sx & v[15]}}, v[15:0]};
            default: return v;
        endcase
    endfunction

    function automatic logic [31:0] eflags(input flags_t f);
        return {20'd0, f.of, 3'd0, f.sf, f.zf, 1'b0, f.af, 1'b0, f.pf, 1'b1, f.cf};
    endfunction

    // Jcc condition codes 0-F (Intel SDM Vol. 2, Jcc)
    function automatic logic cond_taken(input logic [3:0] cc, input flags_t f);
        logic t;
        case (cc[3:1])
            3'd0: t = f.of;
            3'd1: t = f.cf;
            3'd2: t = f.zf;
            3'd3: t = f.cf | f.zf;
            3'd4: t = f.sf;
            3'd5: t = f.pf;
            3'd6: t = f.sf != f.of;
            default: t = f.zf | (f.sf != f.of);
        endcase
        return t ^ cc[0];
    endfunction
endpackage
