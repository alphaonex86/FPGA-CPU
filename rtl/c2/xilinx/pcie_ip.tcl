# The 7 Series PCIe IP of the C2 card (AX7A035B: xc7a35tfgg484-2): x2
# Gen2, 64-bit AXI4-Stream at 125 MHz, one 8 KB 32-bit memory BAR0
# (sw/c2-vmm/bus.h), 100 MHz reference clock from the slot.
# Sourced by build.tcl into its open project, ip_dir set.
file mkdir $ip_dir
create_ip -name pcie_7x -vendor xilinx.com -library ip -module_name c2_pcie -dir $ip_dir
# shared_logic_in_core exists in the Advanced mode only and is locked while
# en_ext_clk (the default) is set
set_property -dict {CONFIG.mode_selection Advanced CONFIG.en_ext_clk false} [get_ips c2_pcie]
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
    CONFIG.shared_logic_in_core {true} \
] [get_ips c2_pcie]
# the default keeps the PIPE clocking outside the core: user_clk would come
# from the (unused) pipe_userclk inputs and every user register be trimmed
if {[get_property CONFIG.shared_logic_in_core [get_ips c2_pcie]] ne "true"} {
    error "c2_pcie: shared logic (PIPE clock) not in the core"
}
generate_target {synthesis instantiation_template} [get_ips c2_pcie]
