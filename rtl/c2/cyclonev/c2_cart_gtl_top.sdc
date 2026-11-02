# C2 cartridge on its dedicated PCB (c2_cart_gtl_top.sv, plan/slot1_c2.md
# D33/D35/D37). BCLK 66 MHz and the J5 link as in c2_cart_top.sdc.
create_clock -name bclk -period 15.0 [get_ports bclk]
derive_pll_clocks
create_clock -name link_dclk -period 20.0 [get_ports link_dclk]
set_input_delay -clock link_dclk -clock_fall -max 2.0 [get_ports {link_down[*]}]
set_input_delay -clock link_dclk -clock_fall -min -2.0 [get_ports {link_down[*]}]
create_generated_clock -name link_uclk -source [get_ports link_dclk] -invert [get_ports link_uclk]
set_output_delay -clock link_uclk -max 2.0 [get_ports {link_up[*]}]
set_output_delay -clock link_uclk -min -2.0 [get_ports {link_up[*]}]
set_clock_groups -asynchronous -group [get_clocks {bclk *bclk_pll*}] -group {link_dclk link_uclk}

set_false_path -from [get_ports {intr nmi a20m_n init_n smi_n stpclk_n}]
# P6 pins: the Pentium II edge-finger timing as in c2_cart_top.sdc [p2
# Table 12: valid 0.71-4.66 ns, setup 1.97, hold 1.61; the chipset's own
# timing does not scale with the period, t_spec 10 ns], cartridge traces
# 0.1-0.3 ns (also finger -> BCLK pin), SN74GTL16612 clocked both ways
# [ti_sn74gtl16612 GTL+ tables: CLKAB -> B 1.9-5.5 ns, A setup / hold to
# CLKAB 1.3 / 1.6 ns, CLKBA -> A 2.3-6.1 ns, B setup / hold to CLKBA
# 2.3 / 0.3 ns, OEAB -> B 2.0-5.6 ns, OEBA -> A 2.3-7.4 / 2.5-6.4 ns].
set t_spec 10.0
set tr_min 0.1; set tr_max 0.3
# observed control lines: straight from the fingers
set p6_rx  [get_ports {ads_n bnr_n bpri_n trdy_n dbsy_n drdy_n rs_n[*] reset_n}]
set_input_delay -clock bclk -max [expr {$t_spec - 1.97 + 2 * $tr_max - $tr_min}] $p6_rx
set_input_delay -clock bclk -min [expr {1.61 + 2 * $tr_min - $tr_max}] $p6_rx
# Transceiver clocks: BCLK through a CY2309 zero-delay buffer, one output
# per chip [infineon_cy2305: REF -> outputs +-0.35 ns, output skew 0.25,
# jitter 0.2; REF threshold VDD/2 against BCLK's 1.25 V: up to 0.4 late].
# clk_*: the edge at the chips after BCLK at the fingers. The bus checks:
# B setup / hold to CLKBA, and the CLKAB -> B output inside the P6 valid
# window at the fingers (hold 0.71 ns; setup: data by t_spec - 4.66 ns
# before the next edge, the chipset's setup at 100 MHz)
set clk_min -0.8; set clk_max 1.2
if {$clk_min - 2.3 < $t_spec - 1.97 + $tr_max - 15.0 || $clk_max + 0.3 > 1.61 + $tr_min ||
    $clk_min + 1.9 + $tr_min < 0.71 || $clk_max + 5.5 + $tr_max > 15.0 - ($t_spec - 4.66)} {
    post_message -type critical_warning "transceiver clock outside the P6 bus window"
}
# D#: from the DATA chips' B -> A register
set_input_delay -clock bclk -max [expr {$clk_max + 6.1 + $tr_max - $tr_min}] [get_ports {d_n[*]}]
set_input_delay -clock bclk -min [expr {$clk_min + 2.3 + $tr_min - $tr_max}] [get_ports {d_n[*]}]
# outputs into the A -> B registers at the next BCLK: the agent's clock
# runs 1.75 ns late so the PVT spread of the FPGA outputs fits
set p6_out [get_ports {a_n[*] req_n[*] d_n[*] ads_tx_n drdy_tx_n br0_tx_n}]
set_output_delay -clock bclk -max [expr {1.3 + $tr_max - ($clk_min - $tr_max)}] $p6_out
set_output_delay -clock bclk -min [expr {-1.6 + $tr_min - ($clk_max - $tr_min)}] $p6_out
# direction pins (the agent turns them a BCLK ahead, OEAB# holds a BCLK
# after the data): OEAB# enables B before the clocked data leaves CLKAB;
# OEBA# (the A side back to the FPGA) settles within the next BCLK
set p6_oeab [get_ports {addr_oeab_n data_oeab_n}]
set_output_delay -clock bclk -max [expr {5.6 + $tr_max - ($clk_min + 1.9 + $tr_min)}] $p6_oeab
set_output_delay -clock bclk -min 0.0 $p6_oeab
set p6_oeba [get_ports {addr_oeba_n data_oeba_n}]
set_output_delay -clock bclk -max [expr {7.4 + $tr_max - 15.0}] $p6_oeba
set_output_delay -clock bclk -min 0.0 $p6_oeba
# TX enable: on once the PLL locks; the spare TX channels: constant
set_false_path -to [get_ports {tx_oeab_n tx_spare_n[*] ab_le}]
# A[12:5]# in: the configuration straps, static around the end of RESET#;
# REQ# is not read
set_false_path -from [get_ports {a_n[*] req_n[*]}]

derive_clock_uncertainty
