#!/bin/bash
# Usage: rtl/tools/s3_bus_test.sh [seeds, default 8]
# s3_bus unit test (rtl/tests/s3/bus_tb.sv): random operations against a 486 slave with RDY#, wait
# states, BOFF#, HOLD, AHOLD + EADS#, STPCLK# and BS8# / BS16#; then one run per mix: no RDY#, RDY# only, heavy interference, undisturbed, every page narrow.
set -eu
cd "$(dirname "$0")/.."
out=build/s3sim/bus
mkdir -p "$out"
nice -n 19 verilator --cc --exe --build -j 4 -Wall -Wno-UNUSEDSIGNAL --assert --top-module bus_tb --Mdir "$out/obj" \
    s3/s3_bus.sv tests/s3/bus_tb.sv tests/s3/bus_tb.cpp -o bus_tb > "$out/build.log" 2>&1 || { grep -m20 -A3 "%Error\|%Warning" "$out/build.log"; exit 1; }
for seed in $(seq 1 "${1:-8}"); do
    "$out/obj/bus_tb" "+seed=$seed"
done
"$out/obj/bus_tb" +seed=101 +rdy=0
"$out/obj/bus_tb" +seed=102 +rdy=100 +boff=0 +hold=0 +ahold=0 +stp=0
"$out/obj/bus_tb" +seed=103 +boff=200 +hold=100 +ahold=100 +stp=50
"$out/obj/bus_tb" +seed=104 +rdy=0 +boff=0 +hold=0 +ahold=0 +stp=0 +bs=0
"$out/obj/bus_tb" +seed=105 +bs=100
echo "PASS  s3_bus"
