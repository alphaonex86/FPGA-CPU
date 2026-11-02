# ALINX AX7A035B (xc7a35tfgg484-2) for ax7a035b_top.sv; pins from the
# AX7A035B manual REV 1.1 (FPGAlist/c2_cards/README.md). PCIe lanes and
# GTP channels: placed by the IP's own constraints (lane 0 = X0Y3 = RX D9/C9).

# PCIe reference clock from the slot (MGTREFCLK1_216)
set_property PACKAGE_PIN F10 [get_ports pcie_clk_p]
set_property PACKAGE_PIN E10 [get_ports pcie_clk_n]
create_clock -name pcie_ref -period 10.000 [get_ports pcie_clk_p]

# 200 MHz oscillator, bank 34 (1.5 V, DDR3)
set_property -dict {PACKAGE_PIN R4 IOSTANDARD DIFF_SSTL15} [get_ports sys_clk_p]
set_property -dict {PACKAGE_PIN T4 IOSTANDARD DIFF_SSTL15} [get_ports sys_clk_n]
create_clock -name sys_clk -period 5.000 [get_ports sys_clk_p]

set_property -dict {PACKAGE_PIN F15 IOSTANDARD LVCMOS33} [get_ports reset_key_n]
set_property -dict {PACKAGE_PIN L13 IOSTANDARD LVCMOS33} [get_ports {led_n[0]}]
set_property -dict {PACKAGE_PIN M13 IOSTANDARD LVCMOS33} [get_ports {led_n[1]}]
set_property -dict {PACKAGE_PIN K14 IOSTANDARD LVCMOS33} [get_ports {led_n[2]}]
set_property -dict {PACKAGE_PIN K13 IOSTANDARD LVCMOS33} [get_ports {led_n[3]}]
# USB UART: FPGA L15 -> CP2102 RXD
set_property -dict {PACKAGE_PIN L15 IOSTANDARD LVCMOS33} [get_ports uart_tx]

# J11 link (plan/slot1_c2.md "Cable link v0"): odd pins 3-17 down data,
# 19 up clock (MRCC), 21 down clock, 23-35 + 36 up data, even 4-34 ground
set_property PACKAGE_PIN G21 [get_ports {down_d[0]}]
set_property PACKAGE_PIN C22 [get_ports {down_d[1]}]
set_property PACKAGE_PIN F19 [get_ports {down_d[2]}]
set_property PACKAGE_PIN D20 [get_ports {down_d[3]}]
set_property PACKAGE_PIN A18 [get_ports {down_d[4]}]
set_property PACKAGE_PIN B20 [get_ports {down_d[5]}]
set_property PACKAGE_PIN F18 [get_ports {down_d[6]}]
set_property PACKAGE_PIN E19 [get_ports {down_d[7]}]
set_property PACKAGE_PIN C18 [get_ports up_clk]
set_property PACKAGE_PIN B17 [get_ports down_clk]
set_property PACKAGE_PIN D17 [get_ports {up_d[0]}]
set_property PACKAGE_PIN A15 [get_ports {up_d[1]}]
set_property PACKAGE_PIN B15 [get_ports {up_d[2]}]
set_property PACKAGE_PIN A13 [get_ports {up_d[3]}]
set_property PACKAGE_PIN E16 [get_ports {up_d[4]}]
set_property PACKAGE_PIN C14 [get_ports {up_d[5]}]
set_property PACKAGE_PIN F16 [get_ports {up_d[6]}]
set_property PACKAGE_PIN E17 [get_ports {up_d[7]}]
set_property PACKAGE_PIN G22 [get_ports {j11_gnd[0]}]
set_property PACKAGE_PIN B22 [get_ports {j11_gnd[1]}]
set_property PACKAGE_PIN F20 [get_ports {j11_gnd[2]}]
set_property PACKAGE_PIN C20 [get_ports {j11_gnd[3]}]
set_property PACKAGE_PIN A19 [get_ports {j11_gnd[4]}]
set_property PACKAGE_PIN A20 [get_ports {j11_gnd[5]}]
set_property PACKAGE_PIN E18 [get_ports {j11_gnd[6]}]
set_property PACKAGE_PIN D19 [get_ports {j11_gnd[7]}]
set_property PACKAGE_PIN C19 [get_ports {j11_gnd[8]}]
set_property PACKAGE_PIN B18 [get_ports {j11_gnd[9]}]
set_property PACKAGE_PIN C17 [get_ports {j11_gnd[10]}]
set_property PACKAGE_PIN A16 [get_ports {j11_gnd[11]}]
set_property PACKAGE_PIN B16 [get_ports {j11_gnd[12]}]
set_property PACKAGE_PIN A14 [get_ports {j11_gnd[13]}]
set_property PACKAGE_PIN D16 [get_ports {j11_gnd[14]}]
set_property PACKAGE_PIN C15 [get_ports {j11_gnd[15]}]
set_property IOSTANDARD LVCMOS33 [get_ports {down_d[*] down_clk up_d[*] up_clk j11_gnd[*]}]
set_property -dict {DRIVE 8 SLEW SLOW} [get_ports {down_d[*] down_clk j11_gnd[*]}]

# link timing: each side launches data on its clock's rising edge and sends
# that clock inverted, so data change at the received clock's falling edge
# (+-2 ns of cable and board skew) and are captured at its rising edge
create_clock -name up_clk -period 20.000 [get_ports up_clk]
set_input_delay -clock up_clk -clock_fall -max 2.000 [get_ports {up_d[*]}]
set_input_delay -clock up_clk -clock_fall -min -2.000 [get_ports {up_d[*]}]
create_generated_clock -name down_clk -source [get_pins down_clk_oddr/C] -divide_by 1 -invert [get_ports down_clk]
set_output_delay -clock down_clk -max 2.000 [get_ports {down_d[*]}]
set_output_delay -clock down_clk -min -2.000 [get_ports {down_d[*]}]

# key, LEDs and UART: static or asynchronous to their receiver
set_false_path -from [get_ports reset_key_n]
set_false_path -to [get_ports {led_n[*] uart_tx}]

# clock domains: PCIe (from the reference clock), link (200 MHz oscillator),
# returned cartridge clock; crossings are the toggle handshake and FIFOs.
# txoutclk_x0y0 (the IP's PIPE clock root) exists in implementation only:
# "No clocks matched" in synthesis, where the IP is a black box
set_clock_groups -asynchronous \
    -group [get_clocks -include_generated_clocks {pcie_ref txoutclk_x0y0}] \
    -group [get_clocks -include_generated_clocks sys_clk] \
    -group [get_clocks up_clk]

# configuration: SPI x4 flash, compressed so PCIe enumerates in time
set_property CONFIG_VOLTAGE 3.3 [current_design]
set_property CFGBVS VCCO [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4 [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE 50 [current_design]
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
