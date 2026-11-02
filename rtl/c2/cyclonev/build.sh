#!/bin/bash
# Usage: rtl/c2/cyclonev/build.sh <out_dir>
# Compiles the C2 cartridge bitstream (c2_cart_top.sv) with Quartus Lite;
# fails on a critical warning, an unplaced, ignored or incomplete pin
# assignment, an inferred latch or a timing violation.
set -eu
[[ $# -eq 1 ]] || { echo "usage: $0 <out_dir>"; exit 1; }
here=$(realpath "$(dirname "$0")")
QUARTUS=${QUARTUS:-$HOME/altera_lite/25.1std/quartus/bin}
mkdir -p "$1"
cd "$1"
python3 -I "$here/gen_qsf.py" c2_cart.qsf
echo 'PROJECT_REVISION = "c2_cart"' > c2_cart.qpf
nice -n 19 "$QUARTUS/quartus_sh" --flow compile c2_cart > flow.log 2>&1 || {
    grep -m10 "^Error" flow.log || true; echo "FAIL see $PWD/flow.log"; exit 1; }
# 15706: an assignment to a missing node; 169085 / 176015: an unplaced pin;
# 176250 / 176225: an ignored or unpackable fast I/O register; 15714: an
# incomplete I/O assignment
if grep -E "Critical Warning|Warning \((15706|169085|176015|176250|176225|15714)\)|inferring latch" flow.log c2_cart.fit.rpt; then
    echo "FAIL see $PWD/flow.log"; exit 1; fi
grep -E "Logic utilization|Total registers|Total pins" c2_cart.fit.summary
if grep -q "Timing requirements not met" c2_cart.sta.rpt flow.log; then
    grep -B2 -A12 "Setup Summary" c2_cart.sta.rpt | head -30; echo "FAIL timing"; exit 1; fi
grep -A8 "Setup Summary" c2_cart.sta.rpt | grep -m4 "^; [a-z]"
echo "C2 cartridge: $PWD/c2_cart.sof"
