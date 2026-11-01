// Types shared by the x86 core (plan/x86_core.md M2).
package x86_pkg;
    localparam int ROB_N = 32;   // reorder buffer entries
    localparam int RS_N = 16;    // unified reservation station entries
    localparam int SQ_N = 8;     // store queue entries
    localparam int TAG_W = $clog2(ROB_N);
    localparam int SQ_W = $clog2(SQ_N);

    // architectural registers renamed by the core: EAX..EDI, then TMP (the
    // internal register between the uops of one instruction)
    localparam logic [3:0] R_ESP = 4'd4, R_TMP = 4'd8;
    localparam int NREG = 9;

    typedef enum logic [2:0] {K_ALU, K_LD, K_ST, K_BR, K_HLT, K_ILL} kind_t;
    typedef enum logic [3:0] {A_ADD, A_OR, A_ADC, A_SBB, A_AND, A_SUB, A_XOR, A_CMP,
                              A_TEST, A_INC, A_DEC, A_MOV, A_LEA} aop_t;   // A_LEA: s1 + s2 << scale + imm, no flags

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
        logic [3:0]  dst;
        logic        wdst;
        logic [3:0]  s1, s2, s3; // ALU a/b; memory base/index/store data
        logic        us1, us2, us3;
        logic [1:0]  scale;      // memory index scale
        logic [31:0] imm;        // ALU b when !us2; memory displacement; branch target
        logic [31:0] imm2;       // store data when !us3
        logic        rflags, wflags;
        logic        eop;        // last uop of its x86 instruction
        logic [31:0] next_eip;   // EIP after the instruction (branch fall-through)
    } uop_t;

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
