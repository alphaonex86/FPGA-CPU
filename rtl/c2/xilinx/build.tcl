# Builds the C2 card bitstream for the ALINX AX7A035B (xc7a35tfgg484-2):
# PCIe IP, synthesis, implementation, timing report, .bit and SPI flash .bin.
# Usage: rtl/tools/vivado.sh rtl/c2/xilinx/build.tcl <out_dir> [rom.hex]
# With a ROM (32-bit words, sw/c2-vmm/test_rtl.sh makes test_rom.hex) the
# LOOPBACK variant: cartridge and test devices inside the card FPGA.
set out [file normalize [lindex $argv 0]]
set rom [expr {[llength $argv] > 1 ? [file normalize [lindex $argv 1]] : ""}]
if {$rom ne "" && ![file readable $rom]} { error "no ROM $rom" }
set here [file dirname [file normalize [info script]]]
set c2 [file dirname $here]
file mkdir $out
create_project -in_memory -part xc7a35tfgg484-2
set_property target_language Verilog [current_project]

set ip_dir $out/ip
source $here/pcie_ip.tcl
synth_ip [get_ips c2_pcie]

read_verilog -sv [list $c2/c2_afifo.sv $c2/c2_req_sync.sv $c2/c2_card.sv $c2/c2_cart.sv $c2/c2_loop_target.sv \
    $c2/c2_uart_tx.sv $here/c2_tlp.sv $here/ax7a035b_top.sv]
read_xdc $here/ax7a035b.xdc
set blocks {tlp sync card pcie}
if {$rom eq ""} {
    synth_design -top ax7a035b_top
} else {
    synth_design -top ax7a035b_top -generic LOOPBACK=1 -generic "ROM_HEX=\"$rom\""
    lappend blocks loop.cart loop.target loop.uart
}
opt_design
# a constant clock or reset trims whole blocks without an error: check them
foreach block $blocks {
    set n [llength [get_cells -quiet -hier -filter "PRIMITIVE_GROUP==FLOP_LATCH && NAME=~$block/*"]]
    puts "C2 card: $block keeps $n registers"
    if {$n < 20} { error "$block trimmed to $n registers: a constant clock or reset" }
}
place_design
route_design
report_timing_summary -file $out/timing.rpt
report_utilization -file $out/utilization.rpt
report_drc -file $out/drc.rpt
write_bitstream -force $out/c2_card.bit
write_cfgmem -force -format bin -interface SPIx4 -size 16 -loadbit "up 0x0 $out/c2_card.bit" $out/c2_card_flash.bin
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "C2 card: WNS $wns ns, WHS $whs ns"
if {$wns < 0 || $whs < 0} { error "timing not met" }
