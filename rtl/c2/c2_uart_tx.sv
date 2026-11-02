// UART transmitter, 8N1, CLOCKS_PER_BIT clocks per bit (50 MHz / 115200 = 434).
module c2_uart_tx #(
    parameter int CLOCKS_PER_BIT = 434
) (
    input  logic       clk,
    input  logic       rst,
    input  logic       valid,
    input  logic [7:0] data,
    output logic       ready,
    output logic       tx
);
    logic [8:0] shift;          // data then stop; ones shift in
    logic [3:0] bits_left;      // bit periods still to send
    logic [$clog2(CLOCKS_PER_BIT)-1:0] count;

    assign ready = bits_left == '0;

    always_ff @(posedge clk) begin
        if (rst) begin
            bits_left <= '0;
            tx        <= 1;
        end else if (ready) begin
            if (valid) begin   // start bit now
                tx        <= 0;
                shift     <= {1'b1, data};
                bits_left <= 4'd10;
                count     <= '0;
            end
        end else if (count == CLOCKS_PER_BIT - 1) begin
            count     <= '0;
            tx        <= shift[0];
            shift     <= {1'b1, shift[8:1]};
            bits_left <= bits_left - 1'b1;
        end else
            count <= count + 1'b1;
    end
endmodule
