# C2 cartridge (c2_cart_top.sv). BCLK at 66 MHz (plan/slot1.md D27): the P6
# control pins sit on both die edges and the I/O cell registers (needed for
# the board timing) put a die crossing in every one-clock reaction (NM46);
# the J5 link at 50 MHz, mirrored from rtl/c2/xilinx/ax7a035b.xdc: data
# change at the received clock's falling edge (+-2 ns cable and board skew)
# and are captured at its rising edge.
create_clock -name bclk -period 15.0 [get_ports bclk]
derive_pll_clocks
create_clock -name link_dclk -period 20.0 [get_ports link_dclk]
set_input_delay -clock link_dclk -clock_fall -max 2.0 [get_ports {link_down[*]}]
set_input_delay -clock link_dclk -clock_fall -min -2.0 [get_ports {link_down[*]}]
create_generated_clock -name link_uclk -source [get_ports link_dclk] -invert [get_ports link_uclk]
set_output_delay -clock link_uclk -max 2.0 [get_ports {link_up[*]}]
set_output_delay -clock link_uclk -min -2.0 [get_ports {link_up[*]}]
set_clock_groups -asynchronous -group [get_clocks {bclk *bclk_pll*}] -group {link_dclk link_uclk}

# the CMOS pins are asynchronous (synchronized inside)
set_false_path -from [get_ports {intr nmi a20m_n init_n smi_n stpclk_n}]
# P6 pins: the cartridge stands in for the processor, so it meets the
# Pentium II timing at the edge fingers [p2 Table 12, for its 100 MHz bus:
# output valid 0.71-4.66 ns, input setup 1.97 ns, hold 1.61 ns after BCLK
# there]. The chipset's own clock-to-output and setup do not scale with
# the period, so at a slower BCLK its data still arrives by 10 - 1.97 ns
# and ours may come (period - 10) ns later. Through the pass-gate (0-0.3
# ns, a FET switch's Ron x C [cb3t tpd 0.25 ns]) and the cartridge traces
# (0.1-0.3 ns, also finger -> BCLK pin).
set t_bclk [get_clock_info -period [get_clocks bclk]]
set t_spec 10.0
set x_min 0.0;  set x_max 0.3
set tr_min 0.1; set tr_max 0.3
set p6_in  [get_ports {d_n[*] req_n[*] ads_n br0_n drdy_n bnr_n bpri_n trdy_n dbsy_n rs_n[*] reset_n}]
set p6_out [get_ports {a_n[*] d_n[*] req_n[*] ads_n br0_n drdy_n}]
set_input_delay  -clock bclk -max [expr {$t_spec - 1.97 + $x_max + $tr_max - $tr_min}] $p6_in
set_input_delay  -clock bclk -min [expr {1.61 + $x_min + $tr_min - $tr_max}] $p6_in
set_output_delay -clock bclk -max [expr {$t_spec - (4.66 - 2 * $tr_max - $x_max)}] $p6_out
set_output_delay -clock bclk -min [expr {-(0.71 - 2 * $tr_min - $x_min)}] $p6_out
# A[12:5]# in: the configuration straps, static around the end of RESET#
set_false_path -from [get_ports {a_n[*]}]

derive_clock_uncertainty
