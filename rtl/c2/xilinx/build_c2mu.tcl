# Builds the C2 Mu cartridge bitstream (c2mu_top.sv, xc7a100tfgg484-2):
# PCIe IP x4 Gen1 (64-bit at 125 MHz), pins from hw/slot1-c2mu/pins.csv
# (gen_c2mu_assign.py), synthesis, implementation, reports, .bit and the
# SPI x4 flash .bin. Fails on unmet timing, trimmed blocks, or PCIe lanes off
# the balls the board wires.
# Usage: rtl/tools/vivado.sh rtl/c2/xilinx/build_c2mu.tcl <out_dir>
set out [file normalize [lindex $argv 0]]
set here [file dirname [file normalize [info script]]]
set c2 [file dirname $here]
set root [file dirname [file dirname $c2]]
file mkdir $out
create_project -in_memory -part xc7a100tfgg484-2
set_property target_language Verilog [current_project]

set ip_dir $out/ip
set pcie_width X4
set pcie_speed 2.5_GT/s
source $here/pcie_ip.tcl
synth_ip [get_ips c2_pcie]

# pins.csv signal -> top port
proc port_of {sig kind} {
    set fixed {LINT[0]/INTR intr LINT[1]/NMI nmi PCIE_REFCLK_P pcie_clk_p PCIE_REFCLK_N pcie_clk_n}
    if {[dict exists $fixed $sig]} { return [dict get $fixed $sig] }
    if {$kind eq "tx"} {
        set tx {ADS# ads_tx_n DRDY# drdy_tx_n BR0# br0_tx_n DBSY# tx_spare_n[0] BNR# tx_spare_n[1]
                HIT# tx_spare_n[2] HITM# tx_spare_n[3]}
        return [dict get $tx $sig]
    }
    if {[regexp {^PCIE_(TX|RX)(\d)_(P|N)$} $sig -> dir k pn]} {
        return [string tolower "pcie_${dir}_$pn"]\[$k\]
    }
    if {[regexp {^(\w+)\[(\d+)\]#$} $sig -> base k]} { return "[string tolower $base]_n\[$k\]" }
    if {[regexp {^(\w+)#$} $sig -> base]} { return "[string tolower $base]_n" }
    return [string tolower $sig]
}
set f [open $root/hw/slot1-c2mu/pins.csv]
gets $f
set pin_rows {}
while {[gets $f line] >= 0} { lappend pin_rows [split $line ,] }
close $f

read_verilog -sv [list $c2/c2_afifo.sv $c2/c2_req_sync.sv $c2/c2_card.sv $c2/c2_cart.sv $c2/c2_bus_sync.sv \
    $c2/c2_p6_agent.sv $c2/cyclonev/c2_cart_core.sv $here/c2_clk_fwd.sv $here/c2_bclk_mmcm.sv $here/c2_tlp.sv \
    $here/c2_pcie_bridge.sv $here/c2mu_top.sv]
read_xdc $here/c2mu.xdc
synth_design -top c2mu_top
# pins (ports the RTL leaves out, e.g. unused CMOS inputs, stay unplaced balls)
set gt_balls {}
foreach row $pin_rows {
    lassign $row sig kind ball bank
    set port [port_of $sig $kind]
    if {$kind eq "spi" || ![llength [get_ports -quiet $port]]} continue
    if {$kind eq "pcie" && [string match pcie_?x_* $port]} { dict set gt_balls $port $ball; continue }
    set_property PACKAGE_PIN $ball [get_ports $port]
    if {$kind eq "rx"} {
        set_property IOSTANDARD SSTL18_I [get_ports $port]
    } elseif {$kind ne "pcie" || $port eq "pcie_perst_n"} {
        set_property IOSTANDARD LVCMOS33 [get_ports $port]
    }
}
set_property INTERNAL_VREF 0.90 [get_iobanks 15]
opt_design
foreach block {bridge/tlp bridge/sync bridge/pcie card core/cart core/agent core/bus_sync} {
    set n [llength [get_cells -quiet -hier -filter "PRIMITIVE_GROUP==FLOP_LATCH && NAME=~$block/*"]]
    puts "C2 Mu: $block keeps $n registers"
    if {$n < 20} { error "$block trimmed to $n registers: a constant clock or reset" }
}
# every top port on a pins.csv ball (else a pins.csv / port name mismatch);
# the GTP lanes are the IP's, checked after routing
set loose [get_ports -quiet -filter {IS_LOC_FIXED == 0 && NAME !~ pcie_tx_* && NAME !~ pcie_rx_*}]
if {[llength $loose]} { error "ports without a ball: $loose" }
place_design
route_design
dict for {port ball} $gt_balls {
    set got [get_property PACKAGE_PIN [get_ports $port]]
    if {$got ne $ball} { error "$port on $got, the board wires $ball (pins.csv)" }
}
report_timing_summary -file $out/timing.rpt
report_utilization -file $out/utilization.rpt
report_power -file $out/power.rpt
report_drc -file $out/drc.rpt
report_io -file $out/io.rpt
write_bitstream -force $out/c2mu.bit
write_cfgmem -force -format bin -interface SPIx4 -size 16 -loadbit "up 0x0 $out/c2mu.bit" $out/c2mu_flash.bin
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
puts "C2 Mu: WNS $wns ns, WHS $whs ns"
if {$wns < 0 || $whs < 0} { error "timing not met" }
