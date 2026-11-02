// Simple dual-port RAM, asynchronous read (MLAB on Cyclone V), zero at
// power-up. A module of its own: Quartus Lite infers no such RAM declared
// in a generate block.
module x86_ram_async #(
    parameter int W = 8,
    parameter int N = 128
) (
    input  logic                 clk,
    input  logic                 we,
    input  logic [$clog2(N)-1:0] wa,
    input  logic [W-1:0]         wd,
    input  logic [$clog2(N)-1:0] ra,
    output logic [W-1:0]         q
);
    (* ramstyle = "MLAB, no_rw_check" *) logic [W-1:0] mem [N];
    initial for (int i = 0; i < N; i++) mem[i] = '0;
    always_ff @(posedge clk) if (we) mem[wa] <= wd;
    assign q = mem[ra];
endmodule
