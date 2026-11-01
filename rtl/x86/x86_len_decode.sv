// Length of the x86 instruction starting at win[0] (plan/x86_core.md M1):
// legacy prefixes then x86_opdecode, in 16- or 32-bit code (d32 = CS.D).
// Serial prefix scan: the readable reference that x86_predecode is checked
// against (rtl/tests/x86/tb/predecode_check.sv).
module x86_len_decode (
    input  logic [8*15-1:0] win,       // win[8*i +: 8] = byte i
    input  logic            d32,
    output logic [3:0]      len,       // valid when !unsup && !too_long
    output logic [3:0]      npfx,      // legacy prefix bytes
    output logic [1:0]      map,       // 0 one-byte, 1 0F, 2 0F38, 3 0F3A
    output logic            unsup,
    output logic            too_long   // > 15 bytes: #GP
);
    function automatic logic is_prefix(input logic [7:0] x);
        case (x)
            8'h26, 8'h2E, 8'h36, 8'h3E, 8'h64, 8'h65, 8'h66, 8'h67,
            8'hF0, 8'hF2, 8'hF3: return 1'b1;
            default: return 1'b0;
        endcase
    endfunction

    logic                  osz16, asz16;
    logic [8*25-1:0]       padded;   // bytes past the window read as 0
    logic [8*11-1:0]       opwin;
    logic [1:0][1:0][3:0]  oplen;
    logic [4:0]            total;

    x86_opdecode od (.win(opwin), .len(oplen), .map(map), .unsup(unsup));

    always_comb begin
        // prefixes: at most 14 so the opcode stays inside the window
        npfx = 4'd0;
        osz16 = !d32;
        asz16 = !d32;
        for (int i = 0; i < 14; i++)
            if (npfx == i[3:0] && is_prefix(win[8*i +: 8])) begin
                npfx = npfx + 4'd1;
                if (win[8*i +: 8] == 8'h66) osz16 = d32;
                if (win[8*i +: 8] == 8'h67) asz16 = d32;
            end
        padded = {80'd0, win};
        opwin = padded[8*npfx +: 8*11];
        total = {1'b0, npfx} + {1'b0, oplen[asz16][osz16]};
        // a 15th prefix byte leaves no room for the opcode
        too_long = total > 5'd15 || npfx == 4'd14 && is_prefix(win[8*14 +: 8]);
        len = too_long ? 4'd0 : total[3:0];
    end
endmodule
