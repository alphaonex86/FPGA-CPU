# Generates the 7 Series PCIe IP of the C2 card (AX7A035B: xc7a35tfgg484-2):
# x2 Gen2, 64-bit AXI4-Stream at 125 MHz, one 8 KB 32-bit memory BAR0
# (sw/c2-vmm/bus.h), 100 MHz reference clock from the slot.
# Usage: rtl/tools/vivado.sh rtl/c2/xilinx/pcie_ip.tcl <out_dir>
set out [lindex $argv 0]
file mkdir $out
create_project -in_memory -part xc7a35tfgg484-2
set_property target_language Verilog [current_project]
create_ip -name pcie_7x -vendor xilinx.com -library ip -module_name c2_pcie -dir $out
set_property -dict [list \
    CONFIG.Maximum_Link_Width {X2} \
    CONFIG.Link_Speed {5.0_GT/s} \
    CONFIG.Interface_Width {64_bit} \
    CONFIG.User_Clk_Freq {125} \
    CONFIG.Bar0_Enabled {true} \
    CONFIG.Bar0_Type {Memory} \
    CONFIG.Bar0_64bit {false} \
    CONFIG.Bar0_Prefetchable {false} \
    CONFIG.Bar0_Scale {Kilobytes} \
    CONFIG.Bar0_Size {8} \
    CONFIG.Device_ID {7022} \
    CONFIG.Class_Code_Base {05} \
    CONFIG.Class_Code_Sub {80} \
    CONFIG.Ref_Clk_Freq {100_MHz} \
] [get_ips c2_pcie]
generate_target {synthesis instantiation_template} [get_ips c2_pcie]
report_property [get_ips c2_pcie] CONFIG.*
