// Asynchronous FIFO, Gray-coded pointers (2^AW entries). Used for the link
// bytes that arrive on the other board's returned clock. A write while full
// is dropped and raises overflow (sticky, write clock).
module c2_afifo #(
    parameter int W  = 8,
    parameter int AW = 3
) (
    input  logic         wclk,
    input  logic         wrst,
    input  logic         we,
    input  logic [W-1:0] wd,
    output logic         overflow,
    input  logic         rclk,
    input  logic         rrst,
    input  logic         re,
    output logic [W-1:0] rd,
    output logic         empty
);
    logic [W-1:0] mem [2 ** AW];
    logic [AW:0]  wbin, wgray, rbin, rgray;
    logic [AW:0]  wgray_r1, wgray_r2, rgray_w1, rgray_w2;   // synchronizers

    function automatic logic [AW:0] gray(input logic [AW:0] b);
        return b ^ (b >> 1);
    endfunction

    // 2^AW written ahead of the (synchronized) read pointer; AW >= 2
    wire full = wgray == {~rgray_w2[AW:AW - 1], rgray_w2[AW - 2:0]};

    always_ff @(posedge wclk) begin
        if (wrst) begin
            wbin     <= '0;
            wgray    <= '0;
            rgray_w1 <= '0;
            rgray_w2 <= '0;
            overflow <= 0;
        end else begin
            {rgray_w2, rgray_w1} <= {rgray_w1, rgray};
            if (we && full) overflow <= 1;
            else if (we) begin
                mem[wbin[AW - 1:0]] <= wd;
                wbin  <= wbin + 1'b1;
                wgray <= gray(wbin + 1'b1);
            end
        end
    end

    always_ff @(posedge rclk) begin
        if (rrst) begin
            rbin     <= '0;
            rgray    <= '0;
            wgray_r1 <= '0;
            wgray_r2 <= '0;
        end else begin
            {wgray_r2, wgray_r1} <= {wgray_r1, wgray};
            if (re && !empty) begin
                rbin  <= rbin + 1'b1;
                rgray <= gray(rbin + 1'b1);
            end
        end
    end

    assign empty = rgray == wgray_r2;
    assign rd    = mem[rbin[AW - 1:0]];
endmodule
