# C2 Mu cartridge timing (c2mu_top.sv; pins from hw/slot1-c2mu/pins.csv by
# build_c2mu.tcl). The P6 pin timing is cyclonev/c2_cart_gtl_top.sdc's
# (plan/slot1_c2.md D37): Pentium II edge-finger timing [p2 Table 12:
# valid 0.71-4.66 ns, setup 1.97, hold 1.61; t_spec 10 ns], cartridge traces
# 0.1-0.3 ns, SN74GTL16612 clocked both ways by a CY2309 [ti_sn74gtl16612,
# infineon_cy2305: transceiver clock -0.8..+1.2 ns from BCLK at the fingers].
create_clock -name bclk -period 15.000 [get_ports bclk]
create_clock -name osc50 -period 20.000 [get_ports osc50]
create_clock -name pcie_ref -period 10.000 [get_ports pcie_clk_p]
# txoutclk_x0y0 (the IP's PIPE clock root) exists in implementation only
set_clock_groups -asynchronous \
    -group [get_clocks -include_generated_clocks {pcie_ref txoutclk_x0y0}] \
    -group [get_clocks -include_generated_clocks osc50] \
    -group [get_clocks -include_generated_clocks bclk]

set t_spec 10.0
set tr_min 0.1; set tr_max 0.3
set clk_min -0.8; set clk_max 1.2
set p6_rx [get_ports {ads_n bnr_n bpri_n trdy_n dbsy_n drdy_n rs_n[*] reset_n}]
set_input_delay -clock bclk -max [expr {$t_spec - 1.97 + 2 * $tr_max - $tr_min}] $p6_rx
set_input_delay -clock bclk -min [expr {1.61 + 2 * $tr_min - $tr_max}] $p6_rx
# D#: from the DATA chips' B -> A register
set_input_delay -clock bclk -max [expr {$clk_max + 6.1 + $tr_max - $tr_min}] [get_ports {d_n[*]}]
set_input_delay -clock bclk -min [expr {$clk_min + 2.3 + $tr_min - $tr_max}] [get_ports {d_n[*]}]
# outputs into the A -> B registers at the next BCLK
set p6_out [get_ports {a_n[*] req_n[*] d_n[*] ads_tx_n drdy_tx_n br0_tx_n}]
set_output_delay -clock bclk -max [expr {1.3 + $tr_max - ($clk_min - $tr_max)}] $p6_out
set_output_delay -clock bclk -min [expr {-1.6 + $tr_min - ($clk_max - $tr_min)}] $p6_out
set p6_oeab [get_ports {addr_oeab_n data_oeab_n}]
set_output_delay -clock bclk -max [expr {5.6 + $tr_max - ($clk_min + 1.9 + $tr_min)}] $p6_oeab
set_output_delay -clock bclk -min 0.0 $p6_oeab
set p6_oeba [get_ports {addr_oeba_n data_oeba_n}]
set_output_delay -clock bclk -max [expr {7.4 + $tr_max - 15.0}] $p6_oeba
set_output_delay -clock bclk -min 0.0 $p6_oeba
# I/O registers in the I/O cells
set_property IOB TRUE [get_ports {ads_n bnr_n bpri_n trdy_n dbsy_n drdy_n rs_n[*] reset_n d_n[*]}]

# static or asynchronous to their receiver: TX enable (VTT / PLL lock), the
# spare TX channels, LEAB, the A[12:5]# straps (sampled around RESET#),
# REQ# in, the CMOS pins, the Mu and LED lines
set_false_path -to [get_ports {tx_oeab_n tx_spare_n[*] ab_le led mu_pwr_on mu_rst}]
set_false_path -from [get_ports {a_n[*] req_n[*] intr nmi a20m_n init_n smi_n stpclk_n vtt_sense mu_pson pcie_perst_n}]

# configuration: SPI x4 flash, compressed so PCIe is up before the Mu boots
set_property CONFIG_VOLTAGE 3.3 [current_design]
set_property CFGBVS VCCO [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4 [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE 50 [current_design]
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
