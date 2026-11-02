# Writes build.tcl's c2_card_flash.bin into the AX7A035B's SPI flash over
# JTAG (verified), then boots the FPGA from it. The card enumerates on PCIe
# only when the bitstream is loaded at host power-up: reboot the host after.
# Usage: rtl/tools/vivado.sh rtl/c2/xilinx/program.tcl <out_dir> [flash part]
# The manual lists an N25Q128 (3.3 V), sold now as MT25QL128; another part
# found on the board: get_cfgmem_parts {*128*spi-x1_x2_x4}.
set out [file normalize [lindex $argv 0]]
set part [expr {[llength $argv] > 1 ? [lindex $argv 1] : "mt25ql128-spi-x1_x2_x4"}]
set bin $out/c2_card_flash.bin
if {![file readable $bin]} { error "no $bin: run build.tcl first" }

open_hw_manager
connect_hw_server
open_hw_target
set dev [lindex [get_hw_devices xc7a35t_0] 0]
if {$dev eq ""} { error "no xc7a35t on the JTAG chain: [get_hw_devices]" }
current_hw_device $dev
refresh_hw_device $dev
set mem [create_hw_cfgmem -hw_device $dev [lindex [get_cfgmem_parts $part] 0]]
set_property -dict [list PROGRAM.ADDRESS_RANGE use_file PROGRAM.FILES [list $bin] PROGRAM.UNUSED_PIN_TERMINATION pull-none \
    PROGRAM.BLANK_CHECK 0 PROGRAM.ERASE 1 PROGRAM.CFG_PROGRAM 1 PROGRAM.VERIFY 1 PROGRAM.CHECKSUM 0] $mem
# the flash is reached through a JTAG-to-SPI bitstream loaded first
create_hw_bitstream -hw_device $dev [get_property PROGRAM.HW_CFGMEM_BITFILE $dev]
program_hw_devices $dev
program_hw_cfgmem -hw_cfgmem $mem
boot_hw_device $dev
puts "C2 card: flash written and verified, FPGA booted from it"
