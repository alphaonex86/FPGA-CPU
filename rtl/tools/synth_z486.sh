#!/bin/bash
# Usage: rtl/tools/synth_z486.sh <x87 0|1> <out dir> [recipe]
# Compiles the z486 CPU (rtl/ext/z486, clone of github.com/nand2mario/z486)
# alone on 5CEFA9F23C8 the way its boards/de10nano/scripts/build_cpu.tcl
# does on the DE10-Nano (same sources, ROM images, 85 MHz target, every
# port but clk virtual), for the base comparison in plan/cpu_core.md.
set -eu
[[ ${DEVICE:-5CEFA9F23C8} == 5CEFA9F23C8 ]] || { echo "z486 is measured on 5CEFA9F23C8 only"; exit 1; }
. "$(dirname "$0")/quartus_run.sh"
z=$(realpath "$(dirname "$0")/../ext/z486")
[[ -f $z/z486.sv ]] || { echo "clone github.com/nand2mario/z486 into rtl/ext/z486"; exit 1; }
x87=$1
out=$2
recipe=${3:-default}
[[ $x87 == 0 || $x87 == 1 ]] || { echo "x87 must be 0 or 1"; exit 1; }
mkdir -p "$out"
cd "$out"
{
    echo 'set_global_assignment -name FAMILY "Cyclone V"'
    echo 'set_global_assignment -name DEVICE 5CEFA9F23C8'
    echo 'set_global_assignment -name TOP_LEVEL_ENTITY z486'
    echo 'set_global_assignment -name NUM_PARALLEL_PROCESSORS ALL'
    echo 'set_global_assignment -name VERILOG_MACRO "Z486_ALTERA=1"'
    echo "set_global_assignment -name SEARCH_PATH $z"
    echo "set_global_assignment -name SEARCH_PATH $z/x87"
    echo "set_parameter -name ENABLE_X87 $x87"
    echo 'set_parameter -name CLOCK_RATE_MHZ 85'
    grep -v '^\(#\|boards/common/\|$\)' "$z/boards/common/rtl_sources.f" |
        sed "s|^|set_global_assignment -name SYSTEMVERILOG_FILE $z/|"
    echo 'set_global_assignment -name SDC_FILE core.sdc'
    # every top port but clk virtual (build_cpu.tcl's list predates
    # line_din, device_mmio_*, x87_ferr ...)
    awk '/^module z486/{m=1} m && /^\);/{exit}
         m && /^[ \t]*(input|output|inout)[ \t]/ {sub(/\/\/.*/, ""); gsub(/,/, "")
             if ($NF != "clk") print "set_instance_assignment -name VIRTUAL_PIN ON -to " $NF (/\[/ ? "[*]" : "")}' \
        "$z/z486.sv"
} > core.qsf
for f in pla_entry_rom.hex pla_group_entry.hex ucode.mif x87/x87_ucode.mif \
    x87/x87_command_decode.mif x87/x87_logexp_tables.mif; do
    cp "$z/$f" .
done
cat > core.sdc <<'EOF'
create_clock -name clk -period 11.765 [get_ports clk]
set_false_path -from [get_ports reset_n]
set data_inputs [remove_from_collection [all_inputs] [get_ports {clk reset_n}]]
set_input_delay -clock clk 0.0 $data_inputs
set_output_delay -clock clk 0.0 [all_outputs]
derive_clock_uncertainty
EOF
quartus_compile "$recipe"
