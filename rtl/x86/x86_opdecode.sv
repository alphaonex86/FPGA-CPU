// Length of an x86 instruction counted from its opcode byte win[0] (no
// prefixes), for each address size (asz16) and operand size (osz16):
// one-byte / 0F / 0F38 / 0F3A maps, ModRM, SIB, displacement, immediate.
// VEX / EVEX / XOP encodings are flagged unsupported (they raise #UD here).
module x86_opdecode (
    input  logic [8*11-1:0]      win,   // win[8*i +: 8] = byte i, opcode first
    output logic [1:0][1:0][3:0] len,   // len[asz16][osz16], at most 11
    output logic [1:0]           map,   // 0 one-byte, 1 0F, 2 0F38, 3 0F3A
    output logic                 unsup
);
    typedef enum logic [2:0] {I_NONE, I_B, I_W, I_Z, I_ENTER, I_FAR, I_MOFFS, I_GRP3} imm_t;

    function automatic logic modrm_1b(input logic [7:0] op);
        casez (op)
            8'b00???0??, 8'h62, 8'h63, 8'h69, 8'h6B, 8'b1000????, 8'hC0, 8'hC1,
            8'hC4, 8'hC5, 8'hC6, 8'hC7, 8'b110100??, 8'b11011???, 8'hF6, 8'hF7,
            8'hFE, 8'hFF: return 1'b1;
            default: return 1'b0;
        endcase
    endfunction

    function automatic imm_t imm_1b(input logic [7:0] op);
        casez (op)
            8'b00???100, 8'h6A, 8'h6B, 8'b0111????, 8'h80, 8'h82, 8'h83, 8'hA8,
            8'b10110???, 8'hC0, 8'hC1, 8'hC6, 8'hCD, 8'hD4, 8'hD5,
            8'b111000??, 8'hE4, 8'hE5, 8'hE6, 8'hE7, 8'hEB: return I_B;
            8'b00???101, 8'h68, 8'h69, 8'h81, 8'hA9, 8'b10111???, 8'hC7,
            8'hE8, 8'hE9: return I_Z;
            8'hC2, 8'hCA: return I_W;
            8'hC8: return I_ENTER;
            8'h9A, 8'hEA: return I_FAR;
            8'b101000??: return I_MOFFS;
            8'hF6, 8'hF7: return I_GRP3;
            default: return I_NONE;
        endcase
    endfunction

    // 0F map: every opcode has ModRM except these
    function automatic logic modrm_0f(input logic [7:0] op);
        casez (op)
            8'h05, 8'h06, 8'h07, 8'h08, 8'h09, 8'h0B, 8'h0E, 8'h30, 8'h31, 8'h32,
            8'h33, 8'h34, 8'h35, 8'h37, 8'h77, 8'b1000????, 8'hA0, 8'hA1, 8'hA2,
            8'hA8, 8'hA9, 8'hAA, 8'b11001???: return 1'b0;
            default: return 1'b1;
        endcase
    endfunction

    function automatic imm_t imm_0f(input logic [7:0] op);
        casez (op)
            8'h0F, 8'b011100??, 8'hA4, 8'hAC, 8'hBA, 8'hC2, 8'hC4, 8'hC5,
            8'hC6: return I_B;
            8'b1000????: return I_Z;
            default: return I_NONE;
        endcase
    endfunction

    // MOV to/from CR/DR/TR: the mod field is ignored, always register form
    function automatic logic reg_only_0f(input logic [7:0] op);
        casez (op)
            8'b001000??, 8'h24, 8'h26: return 1'b1;
            default: return 1'b0;
        endcase
    endfunction

    function automatic logic [7:0] b(input int i);
        return win[8*i +: 8];
    endfunction

    int         mrm;
    logic [7:0] op, op2, modrm, sib;
    logic       has_modrm, reg_only, mem;
    imm_t       ic;
    int         ea16, ea32, imm;

    always_comb begin
        op = b(0);
        op2 = b(1);
        map = 2'd0;
        mrm = 1;
        has_modrm = modrm_1b(op);
        ic = imm_1b(op);
        reg_only = 1'b0;
        if (op == 8'h0F) begin
            if (op2 == 8'h38 || op2 == 8'h3A) begin
                map = op2 == 8'h38 ? 2'd2 : 2'd3;
                mrm = 3;
                has_modrm = 1'b1;
                ic = op2 == 8'h3A ? I_B : I_NONE;
            end else begin
                map = 2'd1;
                mrm = 2;
                has_modrm = modrm_0f(op2);
                ic = imm_0f(op2);
                reg_only = reg_only_0f(op2);
            end
        end

        modrm = b(mrm);
        sib = b(mrm + 1);
        unsup = map == 2'd0 && ((op == 8'hC4 || op == 8'hC5 || op == 8'h62) && modrm[7:6] == 2'b11
                                || op == 8'h8F && modrm[5:3] != 3'd0);

        // bytes after the opcode: ModRM + SIB + displacement
        mem = has_modrm && !reg_only && modrm[7:6] != 2'b11;
        ea16 = !has_modrm ? 0 : !mem ? 1
             : modrm[7:6] == 2'b01 ? 2
             : modrm[7:6] == 2'b10 || modrm[2:0] == 3'b110 ? 3 : 1;
        ea32 = !has_modrm ? 0 : !mem ? 1
             : (modrm[2:0] == 3'b100 ? 2 : 1)
               + (modrm[7:6] == 2'b01 ? 1
                  : modrm[7:6] == 2'b10 || modrm[2:0] == 3'b101
                    || modrm[2:0] == 3'b100 && sib[2:0] == 3'b101 ? 4 : 0);

        for (int a = 0; a < 2; a++)
            for (int o = 0; o < 2; o++) begin
                case (ic)
                    I_B: imm = 1;
                    I_W: imm = 2;
                    I_Z: imm = o != 0 ? 2 : 4;
                    I_ENTER: imm = 3;
                    I_FAR: imm = o != 0 ? 4 : 6;
                    I_MOFFS: imm = a != 0 ? 2 : 4;
                    I_GRP3: imm = modrm[5:4] != 2'b00 ? 0 : op == 8'hF6 ? 1 : o != 0 ? 2 : 4;
                    default: imm = 0;
                endcase
                len[a][o] = 4'(mrm + (a != 0 ? ea16 : ea32) + imm);
            end
    end
endmodule
