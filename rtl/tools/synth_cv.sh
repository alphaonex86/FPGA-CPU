#!/bin/bash
# Usage: rtl/tools/synth_cv.sh <verilog> <out dir> [period ns] [recipe]
# Compiles one SpinalHDL core netlist alone on $DEVICE (default 5CEFA9F23C8;
# A5EB013BB23BE4SCS = DE25-Nano), every port but clk a virtual pin; recipe
# default | perf, quartus_run.sh)
# and prints its area and slow-model fmax: plan/cpu_core.md.
set -eu
. "$(dirname "$0")/quartus_run.sh"
src=$(realpath "$1")
out=$2
period=${3:-10.0}
recipe=${4:-default}
top=$(sed -n 's/^module \([A-Za-z_0-9]*\).*/\1/p' "$src" | head -1)   # SpinalHDL: top first
[[ -n $top ]] || { echo "no module in $src"; exit 1; }
grep -q "input  *wire *clk\b\|input wire clk\b" "$src" || { echo "$top: no clk port"; exit 1; }
mkdir -p "$out"
cd "$out"
cat > core.qsf <<EOF
set_global_assignment -name FAMILY "$FAMILY"
set_global_assignment -name DEVICE $DEVICE
set_global_assignment -name TOP_LEVEL_ENTITY $top
set_global_assignment -name VERILOG_FILE $src
set_global_assignment -name VERILOG_MACRO "SYNTHESIS=1"
set_global_assignment -name SDC_FILE core.sdc
set_global_assignment -name NUM_PARALLEL_PROCESSORS ALL
EOF
# one VIRTUAL_PIN per top port but clk (a "*" wildcard also takes clk off
# the global clock network)
awk '/^module /{n++}
     n == 1 && /^  (input|output|inout) / {
         p = ($3 ~ /^\[/) ? $4 : $3; sub(/,$/, "", p)
         if (p != "clk") print "set_instance_assignment -name VIRTUAL_PIN ON -to " p ($3 ~ /^\[/ ? "[*]" : "")
     }
     n == 1 && /^\);/ {exit}' "$src" >> core.qsf
echo "create_clock -name clk -period $period [get_ports clk]" > core.sdc
quartus_compile "$recipe"
