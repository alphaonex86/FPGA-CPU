# socket3-cyclonev timing (s3_top.sv). 486 AC at 33 MHz, at the socket pins, from the CLK rising edge
# [amd_am5x86_19751C AC table; the same in intel_dx4_write_back_enhanced]: CPU outputs valid 3-14 ns
# (t6, t8a, t10); the chipset meets setup 5 ns / hold 3 ns on RDY#, BRDY#, KEN# and read data (t14-t17,
# t22 / t23), taken for every sampled input (the others ask for more setup: BOFF# 8, HOLD / AHOLD 6). CLK and every signal cross one SN74CB3T3245 (0.25 ns
# max [ti_sn74cb3t3245]) and 20-60 mm of track (0.1-0.4 ns): the difference stays within SKEW.
set period 30.000
set skew 0.6
create_clock -name clk -period $period [get_ports clk]
derive_pll_clocks
derive_clock_uncertainty
set bus_out [get_ports {a[*] d[*] dp[*] be_n[*] ads_n m_io_n d_c_n w_r_n blast_n lock_n plock_n pcd pwt cache_n hlda breq pchk_n}]
set_output_delay -clock clk -max [expr {$period - 14.0 + $skew}] $bus_out
set_output_delay -clock clk -min [expr {-3.0 + $skew}] $bus_out
set bus_in [get_ports {a[*] d[*] dp[*] rdy_n brdy_n ken_n hold ahold boff_n eads_n bs8_n bs16_n reset}]
set_input_delay -clock clk -max [expr {$period - 5.0 + $skew}] $bus_in
set_input_delay -clock clk -min [expr {3.0 - $skew}] $bus_in
# the PLL clock runs s3_top's PHASE (> 0) after the pin clock: an input is taken at its next edge, not
# at the one PHASE after the launch (the hold check then stands at that one, as it must)
set_multicycle_path -setup -from [get_clocks clk] -to [get_clocks {*pll*}] 2
# the output enables (s3_bus.sv): a float may take 20 ns [19751C float delays], and write data is
# enabled a clock ahead of its T2: 6 ns more than a valid delay
set_max_delay -from [get_registers {*bus|a_oe* *bus|d_oe* *bus|ctl_oe*}] -to [get_ports {a[*] d[*] dp[*] be_n[*] ads_n m_io_n d_c_n w_r_n blast_n lock_n plock_n pcd pwt cache_n}] [expr {$period + 6.0}]
# asynchronous or static pins
set_false_path -from [get_ports {a20m_n stpclk_n vcore_ok}]
set_false_path -to [get_ports {ferr_n hitm_n smiact_n tdo}]
