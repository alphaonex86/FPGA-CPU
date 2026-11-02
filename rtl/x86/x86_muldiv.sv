// Multiply / divide unit, issue port 3 (plan/x86_core.md M2).
// Inputs from the uop: a = s1, b = s2 or imm, c = s3.
// - A_MUL / A_IMUL: low half of a * b (a = eAX; SZ8 gives AX), the high
//   half kept; A_MULH / A_IMULH: that kept high half (the uop depends on
//   the MUL's result and the MUL on the previous EDX, so the pair stays in
//   order); A_IMUL2: 2/3-operand IMUL, low half. input register + 2
//   stages (DSP), one per cycle.
// - A_DIV / A_IDIV: quotient of {c, a} / b (SZ8: AX / b, result {rem,
//   quot}); iterative, 1 quotient bit per cycle, busy meanwhile. A_DIVR /
//   A_IDIVR: the remainder of the last division (the uop depends on that
//   DIV's result, so it always follows it). Divide error: fault.
// The value is merged into the old register: a for MUL/IMUL/DIV/IDIV,
// c otherwise; SZ8 results are 16 bits. Flags (QEMU compute_all_mul):
// CF = OF = high half significant, ZF/SF/PF of the low half, AF = 0; DIV
// leaves flags alone (the uop does not write them). The inputs are
// registered first (s_*): the unit, its DSP blocks included, then places
// away from the issue / bypass logic (unregistered, the core did not route).
module x86_muldiv
    import x86_pkg::*;
(
    input  logic             clk,
    input  logic             kill,       // flush: drop everything in flight
    input  logic             start,
    input  aop_t             op,
    input  logic [1:0]       sz,
    input  logic [31:0]      a, b, c,
    input  logic [TAG_W-1:0] tag,
    output logic             busy,       // a division runs: start nothing
    output logic             done,
    output logic [TAG_W-1:0] done_tag,
    output logic [31:0]      done_value,
    output flags_t           done_flags,
    output logic             done_fault
);
    function automatic logic is_div(input aop_t o);
        return o == A_DIV || o == A_IDIV;
    endfunction
    function automatic logic is_signed(input aop_t o);
        return o == A_IMUL || o == A_IMULH || o == A_IMUL2 || o == A_IDIV || o == A_IDIVR;
    endfunction
    function automatic logic [31:0] old_of(input aop_t o, input logic [31:0] x, input logic [31:0] z);
        return o == A_MUL || o == A_IMUL || is_div(o) ? x : z;
    endfunction
    function automatic logic msb(input logic [31:0] v, input logic [1:0] s);
        return s == SZ8 ? v[7] : s == SZ16 ? v[15] : v[31];
    endfunction
    function automatic logic [5:0] width(input logic [1:0] s);
        return s == SZ8 ? 6'd8 : s == SZ16 ? 6'd16 : 6'd32;
    endfunction

    // ---------------- multiply pipeline (also carries A_DIVR) ----------------
    logic             m1_v, m2_v, m3_v;
    aop_t             m1_op, m2_op;
    logic [1:0]       m1_sz, m2_sz;
    logic [TAG_W-1:0] m1_tag, m2_tag, m3_tag;
    logic [31:0]      m1_old, m2_old, m3_value;
    logic [32:0]      m1_a, m1_b;
    logic [63:0]      m2_p;
    flags_t           m3_flags;

    // ---------------- divider ----------------
    logic             d_run;
    logic [5:0]       d_cnt;
    aop_t             d_op;
    logic [1:0]       d_sz;
    logic [TAG_W-1:0] d_tag;
    logic [31:0]      d_old, d_div, d_lo, d_q;
    logic [32:0]      d_rem;
    logic             d_negq, d_negr, d_fin, d_fault;
    logic [31:0]      last_r;   // remainder of the last division
    logic [31:0]      last_hi;  // high half of the last A_MUL / A_IMUL

    // ---------------- input register ----------------
    logic             s_v;
    aop_t             s_op;
    logic [1:0]       s_sz;
    logic [31:0]      s_a, s_b, s_c;
    logic [TAG_W-1:0] s_tag;

    assign busy = s_v && is_div(s_op) || d_run || d_fin;

    // stage 1 (with the product): operands extended to 33 bits
    always_comb begin
        logic [31:0] ea, eb;
        m1_v = s_v && !kill && !is_div(s_op);
        m1_op = s_op;
        m1_sz = s_sz;
        m1_tag = s_tag;
        m1_old = old_of(s_op, s_a, s_c);
        ea = extend(s_a, s_sz, is_signed(s_op));
        eb = extend(s_b, s_sz, is_signed(s_op));
        m1_a = {is_signed(s_op) & ea[31], ea};
        m1_b = {is_signed(s_op) & eb[31], eb};
    end

    always_ff @(posedge clk) begin
        s_v <= start && !kill;
        s_op <= op;
        s_sz <= sz;
        s_a <= a;
        s_b <= b;
        s_c <= c;
        s_tag <= tag;
        // stage 2: product
        m2_v <= m1_v && !kill;
        m2_op <= m1_op;
        m2_sz <= m1_sz;
        m2_tag <= m1_tag;
        m2_old <= m1_old;
        m2_p <= 64'($signed(m1_a) * $signed(m1_b));
        // stage 3: result and flags
        m3_v <= m2_v && !kill;
        m3_tag <= m2_tag;
        begin
            logic [31:0] lo, hi, y;
            logic [5:0]  w;
            w = width(m2_sz);
            lo = extend(m2_p[31:0], m2_sz, 1'b0);
            hi = extend(32'(m2_p >> w), m2_sz, 1'b0);
            case (m2_op)
                A_MULH, A_IMULH: y = last_hi;
                A_IMUL2:         y = lo;
                A_DIVR, A_IDIVR: y = last_r;
                default:         y = m2_sz == SZ8 ? {16'd0, m2_p[15:0]} : lo;
            endcase
            m3_value <= merge(m2_old, y, m2_sz == SZ8 ? SZ16 : m2_sz, 1'b0);
            if (m2_v && (m2_op == A_MUL || m2_op == A_IMUL)) last_hi <= hi;
            m3_flags.cf <= is_signed(m2_op) ? hi != extend({32{msb(lo, m2_sz)}}, m2_sz, 1'b0) : hi != 32'd0;
            m3_flags.of <= is_signed(m2_op) ? hi != extend({32{msb(lo, m2_sz)}}, m2_sz, 1'b0) : hi != 32'd0;
            m3_flags.zf <= lo == 32'd0;
            m3_flags.sf <= msb(lo, m2_sz);
            m3_flags.pf <= ~^lo[7:0];
            m3_flags.af <= 1'b0;
        end

        // divider: setup, then one quotient bit per cycle, then fix-up
        d_fin <= 1'b0;
        if (kill) d_run <= 1'b0;
        else if (s_v && is_div(s_op)) begin
            logic [31:0] nhi, nlo, dv;
            logic [63:0] n;
            logic        sn, sd, sgn;
            logic [5:0]  w;
            w = width(s_sz);
            sgn = s_op == A_IDIV;
            dv = extend(s_b, s_sz, sgn);
            if (s_sz == SZ8) begin
                nhi = extend(s_a >> 8, SZ8, 1'b0);
                nlo = extend(s_a, SZ8, 1'b0);
            end else begin
                nhi = extend(s_c, s_sz, 1'b0);
                nlo = extend(s_a, s_sz, 1'b0);
            end
            sn = sgn && msb(nhi, s_sz);
            sd = sgn && dv[31];
            if (sn) begin   // dividend magnitude, 2w bits
                n = -(({32'd0, nhi} << w) | {32'd0, nlo});
                nhi = extend(32'(n >> w), s_sz, 1'b0);
                nlo = extend(n[31:0], s_sz, 1'b0);
            end
            d_div <= sd ? extend(-dv, s_sz, 1'b0) : extend(dv, s_sz, 1'b0);
            d_rem <= {1'b0, nhi};
            d_lo <= nlo << (6'd32 - w);
            d_q <= '0;
            d_cnt <= w;
            d_negq <= sn ^ sd;
            d_negr <= sn;
            d_op <= s_op;
            d_sz <= s_sz;
            d_tag <= s_tag;
            d_old <= old_of(s_op, s_a, s_c);
            d_run <= 1'b1;
            d_fault <= 1'b0;
        end else if (d_run) begin
            // divide by zero, quotient overflow: noted, the steps run anyway
            // (a fixed length keeps d_fin clear of the multiply pipeline)
            if (d_cnt == width(d_sz) && (d_div == 32'd0 || d_rem[31:0] >= d_div)) d_fault <= 1'b1;
            begin
                logic [32:0] r;
                r = {d_rem[31:0], d_lo[31]};
                d_lo <= d_lo << 1;
                if (r >= {1'b0, d_div}) begin
                    d_rem <= r - {1'b0, d_div};
                    d_q <= {d_q[30:0], 1'b1};
                end else begin
                    d_rem <= r;
                    d_q <= {d_q[30:0], 1'b0};
                end
                d_cnt <= d_cnt - 6'd1;
                if (d_cnt == 6'd1) begin
                    d_run <= 1'b0;
                    d_fin <= 1'b1;
                end
            end
        end
    end

    // division result (cycle after the last step)
    logic [31:0] q_s, r_s, d_y;
    logic        q_ovf;
    always_comb begin
        logic [5:0]  w;
        logic [31:0] lim;
        w = width(d_sz);
        q_s = extend(d_negq ? -d_q : d_q, d_sz, 1'b0);
        r_s = extend(d_negr ? -d_rem[31:0] : d_rem[31:0], d_sz, 1'b0);
        lim = 32'd1 << (w - 6'd1);   // signed quotient magnitude limit
        q_ovf = d_op == A_IDIV && (d_negq ? d_q > lim : d_q >= lim);
        d_y = d_sz == SZ8 ? {16'd0, r_s[7:0], q_s[7:0]} : q_s;
    end

    always_ff @(posedge clk)
        if (d_fin) last_r <= r_s;

    always_comb begin
        done = !kill && (m3_v || d_fin);
        done_tag = d_fin ? d_tag : m3_tag;
        done_value = d_fin ? merge(d_old, d_y, d_sz == SZ8 ? SZ16 : d_sz, 1'b0) : m3_value;
        done_flags = m3_flags;
        done_fault = d_fin && (d_fault || q_ovf);
    end
endmodule
